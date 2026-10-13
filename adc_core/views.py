from urllib.parse import urlencode
from django.urls import reverse
from scheduling.front_coordination_links import visit_return_slot, return_context, visit_chain_context
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError, ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Q, Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods
from accounts.policies import has_role, clinic_ids, bindings
from adc_core.forms import PatientForm, AppointmentForm, RescheduleForm, ActionForm, SlotForm
from adc_core.rules import RuleError
from patients.models import Patient
from patients.selectors import visible_patients
from patients.services import create_patient, PATIENT_FIELDS
from scheduling.selectors import visible_visits, can_read_visit_details
from scheduling.services import create_appointment, change_appointment, reschedule, create_slot
from scheduling.models import Visit

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
    qs = visible_visits(request.user).select_related("clinic", "dentist", "patient")
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    # Metadata-only for managers/HQ: never render patient identity or free text there.
    rows = [{"id": v.pk, "visit_no": v.visit_no, "clinic": v.clinic.name, "dentist": v.dentist.name,
             "start": v.scheduled_start, "end": v.scheduled_end, "status": v.get_status_display(),
             "patient": v.patient.name if can_read_visit_details(request.user, v) else "受限", 
             "has_details": can_read_visit_details(request.user, v)} for v in page]
    return render(request, "visits.html", {"page": page, "rows": rows})

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
@require_http_methods(["GET", "POST"])
def visit_reschedule(request, pk):
    v = get_object_or_404(visible_visits(request.user), pk=pk)
    if not bindings(request.user).filter(role="FRONT_DESK", scope_kind="CLINIC", clinic_id=v.clinic_id).exists():
        raise PermissionDenied
    origin = visit_return_slot(request.user, request.GET.get("coord_slot"), v)
    form = RescheduleForm(request.POST or None, user=request.user, initial={"expected_version": v.lock_version})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            new = reschedule(actor=request.user, visit_id=v.pk, expected_version=d["expected_version"], new_slot_id=d["slot"].pk, start=d["start"], end=d["end"], reason=d["reason"])
        except EXPECTED_ERRORS as exc:
            add_error(form, exc)
        else:
            messages.success(request, "新预约已创建；原预约及改期原因已保留。")
            return redirect(reverse("visit_detail", args=[new.pk]) + ("?"+urlencode({"coord_slot":origin}) if origin else ""))
    return render(request, "form.html", {"form": form, "title": "改期并保留历史", "subtitle": "新预约失败时，旧预约不会失效。", "button": "确认改期", **return_context(origin)})

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
