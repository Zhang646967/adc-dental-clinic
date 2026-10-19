from urllib.parse import urlencode
from django.urls import reverse
from scheduling.front_coordination_links import visit_return_slot, return_context, visit_chain_context
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError, ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db import connection
from django.db import DatabaseError
from django.db.models import Q, Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from datetime import timedelta
from accounts.policies import has_role, clinic_ids, bindings
from adc_core.forms import PatientForm, AppointmentForm, RescheduleForm, ActionForm, SlotForm
from adc_core.rules import RuleError
from patients.models import Patient
from patients.selectors import visible_patients
from patients.services import create_patient, PATIENT_FIELDS
from scheduling.selectors import visible_visits, can_read_visit_details, booking_slots
from scheduling.services import create_appointment, change_appointment, reschedule, create_slot
from scheduling.models import Visit
from scheduling.worklists import VisitFilterForm, filtered_visits, visit_filter_navigation
from scheduling.reschedule_forms import ReplacementSearchForm, RescheduleConfirmForm
from scheduling.reschedule_selectors import replacement_options, check_target, HORIZON_DAYS
from scheduling.reschedule_services import prepare_reschedule, confirm_reschedule

from adc_core.http_support import EXPECTED_ERRORS, add_error


@require_GET
def health(request):
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        return JsonResponse({"status": "ok", "version": settings.ADC_VERSION})
    except Exception:
        return JsonResponse({"status": "not_ready"}, status=503)

@login_required
@require_GET
def dashboard(request):
    from workspaces.views import home
    return home(request)

@login_required
@require_GET
def patient_list(request):
    qs = visible_patients(request.user)
    q = request.GET.get("q", "").strip()[:80]
    if q:
        qs = qs.filter(Q(patient_no=q) | Q(name__icontains=q))
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "patients.html", {"page": page, "q": q})

@login_required
@require_GET
def patient_lookup(request):
    if not has_role(request.user, "FRONT_DESK"):
        raise PermissionDenied
    number = request.GET.get("patient_no", "").strip()[:40]
    p = Patient.objects.filter(patient_no=number, is_active=True).first() if number else None
    # Minimal cross-chain identity; never attach the Patient ORM object to template.
    info = {"patient_no": p.patient_no, "name": p.name, "phone_suffix": p.phone[-4:]} if p else None
    return render(request, "patient_lookup.html", {"result": info, "submitted": bool(number)})

@login_required
@require_GET
def patient_detail(request, pk):
    p = get_object_or_404(visible_patients(request.user), pk=pk)
    return render(request, "patient_detail.html", {"patient": p, "allergies": p.allergy_links.filter(is_active=True).select_related("allergy")})

@login_required
@require_http_methods(["GET", "POST"])
def patient_create(request):
    if not has_role(request.user, "FRONT_DESK"):
        raise PermissionDenied
    form = PatientForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            p = create_patient(actor=request.user, clinic_id=d["clinic"].pk,
                               details={k: d[k] for k in PATIENT_FIELDS}, allergy_status=d["allergy_status"], allergy_ids=[a.pk for a in d["allergies"]])
        except EXPECTED_ERRORS as exc:
            add_error(form, exc)
        else:
            messages.success(request, "患者档案已创建。")
            return redirect("patient_detail", pk=p.pk)
    return render(request, "form.html", {"form": form, "title": "建立患者档案", "subtitle": "仅录入虚构演示数据；未知不等于无过敏。", "button": "保存患者档案"})

@login_required
@require_GET
def visit_list(request):
    form = VisitFilterForm(request.GET, role=request.workspace.role)
    valid = form.is_valid()
    qs = filtered_visits(request.user, form.cleaned_data) if valid else Visit.objects.none()
    has_details = request.workspace.role in ('FRONT_DESK', 'DENTIST')
    qs = qs.select_related('clinic', 'dentist', *(['patient'] if has_details else []))
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    # Metadata-only for managers/HQ: never render patient identity or free text there.
    rows = [{"id": v.pk, "visit_no": v.visit_no, "clinic": v.clinic.name, "dentist": v.dentist.name,
             "start": v.scheduled_start, "end": v.scheduled_end, "status": v.get_status_display(),
             "patient": v.patient.name if has_details else "受限",
             "has_details": has_details} for v in page]
    query = {k: str(v) for k, v in form.cleaned_data.items() if v} if valid else {}
    queue_shortcuts, filter_chips = visit_filter_navigation(form.cleaned_data if valid else {})
    return render(request, "visits.html", {"page": page, "rows": rows, "filter_form": form,
                  "queue_shortcuts": queue_shortcuts, "filter_chips": filter_chips,
                  "pagination_query": urlencode(query), "filters_valid": valid}, status=200 if valid else 400)

@login_required
@require_http_methods(["GET", "POST"])
def visit_create(request):
    if not has_role(request.user, "FRONT_DESK"):
        raise PermissionDenied
    form = AppointmentForm(request.POST or None, user=request.user, initial={"patient_no": request.GET.get("patient_no", "")[:40]})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            v = create_appointment(actor=request.user, patient_no=d["patient_no"], slot_id=d["slot"].pk,
                start=d["start"], end=d["end"], chief_complaint=d["chief_complaint"], special_needs=d["special_needs"],
                requests=[d["treatment_request"]] if d["treatment_request"] else [])
        except EXPECTED_ERRORS as exc:
            add_error(form, exc)
        else:
            messages.success(request, "预约已保存。")
            return redirect("visit_detail", pk=v.pk)
    return render(request, "form.html", {"form": form, "title": "创建预约", "subtitle": "时间采用北京时间；同时检查患者与牙医的跨店冲突。", "button": "确认预约"})

@login_required
@require_http_methods(["GET", "POST"])
def visit_detail(request, pk):
    v = get_object_or_404(visible_visits(request.user).select_related("clinic", "dentist", "patient"), pk=pk)
    if not can_read_visit_details(request.user, v):
        raise PermissionDenied("此页面包含受限业务详情。")
    origin = visit_return_slot(request.user, request.GET.get("coord_slot"), v)
    can_act = bindings(request.user).filter(role="FRONT_DESK", scope_kind="CLINIC", clinic_id=v.clinic_id).exists()
    form = ActionForm(request.POST or None, initial={"expected_version": v.lock_version})
    if request.method == "POST":
        if not can_act:
            raise PermissionDenied
        if form.is_valid():
            try:
                change_appointment(actor=request.user, visit_id=v.pk, **form.cleaned_data)
            except EXPECTED_ERRORS as exc:
                add_error(form, exc)
            else:
                messages.success(request, "预约结果已更新。")
                return redirect(reverse("visit_detail", args=[v.pk]) + ("?"+urlencode({"coord_slot":origin}) if origin else ""))
    return render(request, "visit_detail.html", {"visit": v, "form": form, "can_act": can_act,
                  "can_care": bindings(request.user).filter(role="DENTIST",scope_kind="SELF_DENTIST",user__dentist_id=v.dentist_id).exists(),
                  "events": v.events.order_by("-recorded_at")[:15], "requests": v.requests.all(), **return_context(origin), **visit_chain_context(request.user, v, origin)})

@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def visit_reschedule(request, pk):
    v = get_object_or_404(visible_visits(request.user), pk=pk)
    if not bindings(request.user).filter(role="FRONT_DESK", scope_kind="CLINIC", clinic_id=v.clinic_id).exists():
        raise PermissionDenied
    origin = visit_return_slot(request.user, request.GET.get("coord_slot"), v)
    action = request.POST.get('action', 'preview') if request.method == 'POST' else None
    if action == 'confirm':
        confirm = RescheduleConfirmForm(request.POST)
        if confirm.is_valid():
            try:
                result = confirm_reschedule(actor=request.user, visit_id=v.pk,
                    proposal_token=confirm.cleaned_data['proposal_token'], confirmed=confirm.cleaned_data['confirmed'])
            except EXPECTED_ERRORS as exc:
                add_error(confirm, exc)
            except DatabaseError:
                return render(request, 'scheduling/reschedule_recovery.html', {'visit': v,
                    'problem': '本次提交结果暂时不能核实。请先打开原预约查询关联记录，不要推断改期失败或反复创建。'}, status=503)
            else:
                origin = visit_return_slot(request.user, str(result.origin), result.visit) if result.origin else None
                messages.success(request, '这次改期此前已保存，本次返回关联预约的当前状态，没有重复创建。' if result.repeated else
                    '新预约已创建，原预约及改期原因已保留。')
                return redirect(reverse('visit_detail', args=[result.visit.pk]) + ('?'+urlencode({'coord_slot': origin}) if origin else ''))
        return render(request, 'scheduling/reschedule_recovery.html', {'visit': v, 'form': confirm,
            'problem': '本次确认未执行。先核对原预约当前状态，再重新选择并预览。', **return_context(origin)}, status=409)
    if request.method == 'POST' and action != 'preview':
        raise PermissionDenied('未知改期操作。')
    if v.status != 'SCHEDULED':
        return render(request, 'scheduling/reschedule_recovery.html', {'visit': v,
            'problem': '原预约当前不能普通改期。请打开原记录核对状态与直接关联的后继预约。', **return_context(origin)}, status=409)
    initial = {'expected_version': v.lock_version}
    selection_problem = ''
    if request.method == 'GET' and any(name in request.GET for name in ('slot', 'start', 'end')):
        try:
            slot = booking_slots(request.user).get(pk=int(request.GET.get('slot', '0')))
            start = parse_datetime(request.GET.get('start', ''))
            end = parse_datetime(request.GET.get('end', ''))
            if start is None or end is None or timezone.is_naive(start) or timezone.is_naive(end):
                raise RuleError('选定时间无效，请重新查询。')
            check_target(v, slot, start, end, timezone.now())
            initial.update(slot=slot.pk, start=start, end=end)
        except (ValueError, *EXPECTED_ERRORS):
            selection_problem = '选定时段已变化或无权使用，请重新查询；原预约未改变。'
    form = RescheduleForm(request.POST if request.method == 'POST' else None, user=request.user, initial=initial)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            preview = prepare_reschedule(actor=request.user, visit_id=v.pk, expected_version=d['expected_version'],
                new_slot_id=d['slot'].pk, start=d['start'], end=d['end'], reason=d['reason'], origin=origin)
        except EXPECTED_ERRORS as exc:
            add_error(form, exc)
        except DatabaseError:
            form.add_error(None, '本次预览不可用，尚未执行改期；请稍后重新核对。')
        else:
            return render(request, 'scheduling/reschedule_confirm.html', {'preview': preview,
                'form': RescheduleConfirmForm(initial={'proposal_token': preview['proposal_token']}),
                'read_only': settings.ADC_READ_ONLY, **return_context(origin)})
    now = timezone.localdate()
    source_day = timezone.localtime(v.scheduled_start).date()
    default_day = source_day if now <= source_day <= now+timedelta(days=HORIZON_DAYS) else now
    search = ReplacementSearchForm({'day': request.GET.get('day', default_day.isoformat()),
        'dentist': request.GET.get('dentist', '')}, actor=request.user, auto_id='id_search_%s')
    options = None
    if search.is_valid():
        try:
            options = replacement_options(actor=request.user, visit_id=v.pk, day=search.cleaned_data['day'],
                dentist_id=search.cleaned_data['dentist'].pk if search.cleaned_data['dentist'] else None)
        except EXPECTED_ERRORS as exc:
            add_error(search, exc)
        except DatabaseError:
            search.add_error(None, '候选读取暂时不可用，不能据此认定没有空闲时间。')
        if options:
            for row in options['rows']:
                query = {'day': search.cleaned_data['day'].isoformat(), 'dentist': search.cleaned_data['dentist'].pk if search.cleaned_data['dentist'] else '',
                         'slot': row['slot_id'], 'start': row['start_iso'], 'end': row['end_iso']}
                if origin: query['coord_slot'] = origin
                row['choose_url'] = reverse('visit_reschedule', args=[v.pk])+'?'+urlencode(query)
    return render(request, 'scheduling/reschedule.html', {'visit': v, 'form': form, 'search': search,
        'options': options, 'selection_problem': selection_problem, 'read_only': settings.ADC_READ_ONLY, **return_context(origin)})

@login_required
@require_http_methods(["GET", "POST"])
def slot_create(request):
    if not has_role(request.user, "MANAGER"):
        raise PermissionDenied
    form = SlotForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            create_slot(actor=request.user, clinic_id=d["clinic"].pk, dentist_id=d["dentist"].pk, start=d["start"], end=d["end"])
        except EXPECTED_ERRORS as exc:
            add_error(form, exc)
        else:
            messages.success(request, "出诊安排已保存，请到本店出诊列表核对。")
            return redirect("availability_list")
    return render(request, "form.html", {"form": form, "title": "新增出诊安排", "subtitle": "同一牙医的有效时段不能跨店重叠。已有安排请从“出诊安排”查看影响；有预约或有效邀约时不能直接调整。", "button": "保存出诊安排"})
