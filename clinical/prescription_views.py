from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import OuterRef, Subquery
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from adc_core.http_support import EXPECTED_ERRORS, add_error
from clinical import prescriptions as cmd
from clinical import dispensing
from clinical.dispensing_views import case_history
from clinical.encounter_views import clinical_render
from clinical.form_binding import check_patient_form, patient_form_binding
from clinical.prescription_access import active_duties, pharmacist, prescriber, require_rehearsal
from clinical.prescription_forms import PrescriptionConfirmForm, PrescriptionDecisionForm, PrescriptionForm, PrescriptionItems
from clinical.prescription_models import Prescription, PrescriptionDecision, PrescriptionDuty, PrescriptionVersion
from clinical.prescription_payload import catalogue_for
from scheduling.models import Visit
from workspaces.views import select_clinic


def _read_case(request, pk):
    ctx = request.workspace
    cases = Prescription.objects.select_related('visit__patient', 'visit__clinic', 'prescriber')
    if ctx.role == 'PHARMACIST':
        pharmacist(request.user, ctx.clinic_id)
        cases = cases.filter(visit__clinic_id=ctx.clinic_id).exclude(prescriber=request.user)
    else:
        cases = cases.filter(visit__dentist_id=request.user.dentist_id)
    case = get_object_or_404(cases, pk=pk)
    if ctx.role == 'DENTIST':
        prescriber(request.user, case.visit)
    return case


def _preview(request, data, token, *, visit, version=None):
    context = dict(data=data, visit=visit, version=version,
                   form=PrescriptionConfirmForm(initial={'proposal_token': token}))
    if version:
        context['action_label'] = PrescriptionDecision.Action(data['action']).label
        context['back'] = reverse('prescription_detail', args=[version.prescription_id])
    else:
        context['back'] = reverse('prescription_visit', args=[visit.pk])
    return clinical_render(request, 'clinical/prescription_confirm.html', context)


@login_required
@never_cache
@require_GET
def review_queue(request):
    require_rehearsal()
    clinic_id = request.workspace.clinic_id
    if clinic_id is None:
        return select_clinic(request)
    can_dispense = dispensing.enabled() and active_duties(request.user.pk, PrescriptionDuty.Kind.DISPENSE).filter(clinic_id=clinic_id).exists()
    if can_dispense and not active_duties(request.user.pk, PrescriptionDuty.Kind.REVIEW).filter(clinic_id=clinic_id).exists():
        return redirect('dispensing_queue')
    pharmacist(request.user, clinic_id)
    latest = PrescriptionVersion.objects.filter(prescription=OuterRef('prescription')).order_by('-number')
    rows = PrescriptionVersion.objects.filter(
        prescription__visit__clinic_id=clinic_id, pk=Subquery(latest.values('pk')[:1]),
    ).exclude(prescription__prescriber=request.user)
    show_history = request.GET.get('queue') == 'history'
    rows = rows.filter(decision__isnull=not show_history).select_related(
        'prescription__visit__patient', 'prescription__prescriber', 'decision',
    ).order_by('-submitted_at', '-pk')
    return clinical_render(request, 'clinical/prescription_queue.html',
                           dict(page=Paginator(rows, 20).get_page(request.GET.get('page')),
                                show_history=show_history, can_dispense=can_dispense))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def visit_prescription(request, pk):
    require_rehearsal()
    visit = get_object_or_404(Visit.objects.select_related('patient', 'clinic'),
                              pk=pk, dentist_id=request.user.dentist_id)
    prescriber(request.user, visit)
    case = Prescription.objects.filter(visit=visit).first()
    latest = cmd.current_version(case) if case else None
    record = cmd.current_record(visit)
    editable = bool(not settings.ADC_READ_ONLY and record and visit.status == 'CHECKED_IN' and
                    visit.patient.is_active and (latest is None or latest.state in cmd.REOPENABLE))
    data = request.POST if request.method == 'POST' else None
    previous = latest.pk if latest else None
    initial = dict(patient_binding=patient_form_binding(request.user, visit),
                   record_id=record.pk if record else None, previous=previous,
                   indication=latest.indication if latest else '')
    form = PrescriptionForm(data, initial=initial)
    previous_items = [
        dict(item=item['item_id'], dose=item['dose'], frequency=item['frequency'],
             days=item['days'], quantity=item['quantity']) for item in latest.items
    ] if latest else None
    items = PrescriptionItems(data, prefix='items', initial=previous_items, form_kwargs={'clinic_id': visit.clinic_id})
    status = 200
    if data is not None:
        if settings.ADC_READ_ONLY:
            raise PermissionDenied('当前实例仅供只读演示。')
        check_patient_form(request.user, visit, data.get('patient_binding', ''))
        form_ok, items_ok = form.is_valid(), items.is_valid()
        if form_ok and items_ok:
            entries = [
                dict(item_id=row['item'].pk, dose=row['dose'], frequency=row['frequency'],
                     days=row['days'], quantity=row['quantity'])
                for row in items.cleaned_data if row and not row.get('DELETE')
            ]
            values = form.cleaned_data
            try:
                preview, token = cmd.prepare_submit(request.user, visit, values['record_id'], values['previous'],
                                                    values['indication'], entries)
            except EXPECTED_ERRORS as exc:
                add_error(form, exc)
                status = 409
            else:
                return _preview(request, preview, token, visit=visit)
        else:
            status = 400
    return clinical_render(request, 'clinical/prescription_visit.html', dict(
        visit=visit, record=record, latest=latest, form=form, items=items, editable=editable,
        allergy_ready=editable and bool(cmd.confirmed_allergy_snapshot(visit, request.user.pk)),
        has_catalogue=catalogue_for(visit.clinic_id).exists(),
    ), status=status)


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def detail(request, pk):
    require_rehearsal()
    case = _read_case(request, pk)
    versions = list(case.versions.select_related('record__history', 'decision__actor'))
    number = request.GET.get('version')
    if not versions or (number and (len(number) > 10 or not number.isdecimal())):
        raise Http404('未找到处方版本。')
    version = versions[0] if not number else next((row for row in versions if row.number == int(number)), None)
    if version is None:
        raise Http404('未找到处方版本。')
    is_pharmacist = request.workspace.role == 'PHARMACIST'
    current = version.pk == versions[0].pk
    editable = current and version.state == 'PENDING' and not settings.ADC_READ_ONLY
    form = PrescriptionDecisionForm(
        request.POST if request.method == 'POST' else None, pharmacist=is_pharmacist,
        initial={'version_id': version.pk},
    )
    status = 200
    if request.method == 'POST':
        if settings.ADC_READ_ONLY:
            raise PermissionDenied('当前实例仅供只读演示。')
        if form.is_valid():
            values = form.cleaned_data
            if values['version_id'] != version.pk:
                form.add_error(None, '处方已出现新版本，请核对当前版本。')
                status = 409
            else:
                try:
                    data, token = cmd.prepare_decision(request.user, version, values['action'], values['reason'])
                except EXPECTED_ERRORS as exc:
                    add_error(form, exc)
                    status = 409
                else:
                    return _preview(request, data, token, visit=case.visit, version=version)
        else:
            status = 400
    return clinical_render(request, 'clinical/prescription_detail.html', dict(
        case=case, visit=case.visit, version=version, versions=versions, current=current,
        confirmed_allergy=cmd.submitted_allergy_snapshot(version) if editable else None,
        pharmacist=is_pharmacist, editable=editable, form=form, history=case_history(version),
        can_dispense=is_pharmacist and dispensing.enabled() and active_duties(
            request.user.pk, PrescriptionDuty.Kind.DISPENSE).filter(clinic_id=case.visit.clinic_id).exists(),
        can_revise=current and version.state in cmd.REOPENABLE and case.visit.status == 'CHECKED_IN'
        and case.visit.patient.is_active and not settings.ADC_READ_ONLY,
    ), status=status)


@login_required
@never_cache
@sensitive_post_parameters()
@require_POST
def confirm(request):
    require_rehearsal()
    form = PrescriptionConfirmForm(request.POST)
    if form.is_valid():
        try:
            version, replay = cmd.confirm(request.user, **form.cleaned_data)
        except EXPECTED_ERRORS as exc:
            add_error(form, exc)
        else:
            messages.success(request, '该次确认已有结果。' if replay else '处方办理结果已保存。')
            return redirect(f"{reverse('prescription_detail', args=[version.prescription_id])}?version={version.number}")
    return clinical_render(request, 'clinical/prescription_confirm.html',
                           dict(form=form, blocked=True), status=409)
