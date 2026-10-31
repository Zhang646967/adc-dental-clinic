from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_GET
from adc_core.http_support import EXPECTED_ERRORS, add_error
from adc_core.proposals import read_proposal
from clinical import consents
from clinical.consent_forms import ConsentActionForm
from clinical.consent_selectors import details
from clinical.encounter_views import clinical_render
from clinical.form_binding import check_patient_form, patient_form_binding
from clinical.plan_forms import ConfirmPlanActionForm


@login_required
@never_cache
@require_GET
def worklist(request):
    from django.core.paginator import Paginator
    from django.db.models import Exists, OuterRef
    from clinical.consent_models import ConsentVersion, ConsentEvent
    from clinical.plan_locks import readable_services
    from workspaces.context import require_active
    require_active(request.user, ('DENTIST',))
    rows = ConsentVersion.objects.filter(prepared_by=request.user,
        source_record__encounter__visit__dentist_id=request.user.dentist_id,
        step_version__service_id__in=readable_services(request.user)).select_related(
        'source_record__encounter__visit__patient', 'source_record__encounter__visit__clinic', 'step_version').annotate(
        needs_answer=Exists(ConsentEvent.objects.filter(consent_id=OuterRef('consent_id'), action='QUESTION', answer__isnull=True)))
    pending = request.GET.get('queue', 'pending') != 'all'
    if pending:rows = rows.filter(needs_answer=True)
    rows = rows.order_by('consent_id', '-revision').distinct('consent_id')
    return clinical_render(request, 'clinical/consent_worklist.html', dict(page=Paginator(rows, 20).get_page(request.GET.get('page')), pending=pending))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def workspace(request, step_id, pk=None):
    doctor = pk is not None
    d = details(request.user, step_id, visit_id=pk, revision=request.GET.get('revision'))
    step = d['step'];visit = None
    if doctor:
        from clinical.encounter_selectors import encounter_details
        visit = encounter_details(request.user, pk)['visit']
    back = reverse('clinical_consent', kwargs=dict(pk=pk, step_id=step_id)) if doctor else reverse('portal_consent', kwargs=dict(step_id=step_id))
    context = dict(d, medical=d['data'], base_template='base.html' if doctor else 'portal/base.html', doctor=doctor, back=back,
                   visit=visit, patient_binding=patient_form_binding(request.user, visit) if visit else '')
    if request.method == 'POST' and request.POST.get('phase') == 'confirm':
        form = ConfirmPlanActionForm(request.POST);data = None
        if form.is_valid():
            try:
                data = read_proposal(request.user, consents.CONTRACT, ('DENTIST', 'PATIENT'), form.cleaned_data['proposal_token'])['data']
                if data['step'] != step_id or data['visit'] != pk:raise PermissionDenied('请在原患者及步骤页面确认。')
                event, replay = consents.confirm(actor=request.user, **form.cleaned_data)
            except EXPECTED_ERRORS as exc:add_error(form, exc)
            else:messages.success(request, '医疗沟通／决定已保留。' + ('已核对原提交结果。' if replay else ''));return redirect(back)
        return clinical_render(request, 'clinical/consent_preview.html', dict(context, confirm_form=form, preview=data if form.is_valid() else None), status=409)
    form = ConsentActionForm(request.POST or None, doctor=doctor, initial=dict(version=d['version'].pk if d['version'] else None))
    if request.method == 'POST':
        if doctor:check_patient_form(request.user, visit, request.POST.get('patient_binding', ''))
        if form.is_valid():
            action, version, values = form.values()
            try:p = consents.prepare(actor=request.user, action=action, step_id=step_id, visit_id=pk, version_id=version, fields=values)
            except EXPECTED_ERRORS as exc:add_error(form, exc)
            else:return clinical_render(request, 'clinical/consent_preview.html', dict(context, preview=p['data'], confirm_form=ConfirmPlanActionForm(initial=dict(proposal_token=p['proposal_token']))))
    return clinical_render(request, 'clinical/consent.html', dict(context, form=form), status=400 if form.errors else 200)
