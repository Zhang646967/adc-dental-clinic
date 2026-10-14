from django.contrib import messages
from django.contrib.auth.decorators import login_required
from workspaces.views import WorkspaceLoginView as LoginView
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_http_methods
from adc_core.http_support import EXPECTED_ERRORS, add_error
from adc_core.rules import RuleError
from registry.models import Clinic
from scheduling.models import Visit
from portal.forms import BookingConfirmationForm, CancelForm, SlotFilterForm
from portal.policies import patient_access
from portal.services import public_options, preview_booking, confirm_booking, cancel_booking

class PortalLoginView(LoginView):
    template_name = "portal/login.html"
    def get_success_url(self):
        return reverse("select_role")

@login_required(login_url="portal_login")
@require_GET
def home(request):
    access=patient_access(request.user)
    visits=Visit.objects.filter(patient_id=access.patient_id).select_related("clinic","dentist")
    from workspaces.worklists import workspace_worklist
    return render(request,"portal/home.html",{"patient":access.patient,"worklist":workspace_worklist(request.user),
        "upcoming":visits.filter(status="SCHEDULED", scheduled_start__gte=timezone.now()).order_by("scheduled_start")[:3],
        "visits_total":visits.count()})

@login_required(login_url="portal_login")
@require_GET
def appointments(request):
    access=patient_access(request.user)
    qs=Visit.objects.filter(patient_id=access.patient_id).select_related("clinic","dentist")
    return render(request,"portal/appointments.html",{"page":Paginator(qs,10).get_page(request.GET.get("page"))})

@login_required(login_url="portal_login")
@require_GET
def slots(request):
    patient_access(request.user)
    form=SlotFilterForm(request.GET)
    rows=[]
    if form.is_valid(): rows=public_options(request.user,form.cleaned_data["clinic"],form.cleaned_data["day"])
    return render(request,"portal/slots.html",{"rows":rows,"form":form,"clinics":Clinic.objects.filter(is_active=True)})

@login_required(login_url="portal_login")
@require_http_methods(["GET","POST"])
def booking_preview(request):
    patient_access(request.user)
    if request.method=="POST":
        form=BookingConfirmationForm(request.POST)
        if form.is_valid():
            try: v=confirm_booking(actor=request.user,token=form.cleaned_data["token"])
            except EXPECTED_ERRORS as exc: add_error(form,exc)
            else:
                messages.success(request,"预约已经保存。相同确认页的重复提交不会再建一条。")
                return redirect("portal_visit",pk=v.pk)
        return render(request,"portal/confirm.html",{"form":form,"failed":True})
    try:
        start=parse_datetime(request.GET.get("start",""))
        if start is None or timezone.is_naive(start): raise RuleError("请选择有效时段。")
        slot,end,token=preview_booking(user=request.user,slot_id=int(request.GET.get("slot","0")),start=start)
    except (ValueError, *EXPECTED_ERRORS):
        messages.error(request,"该时段已变化，请重新选择。")
        return redirect("portal_slots")
    return render(request,"portal/confirm.html",{"slot":slot,"start":start,"end":end,
        "form":BookingConfirmationForm(initial={"token":token})})

@login_required(login_url="portal_login")
@require_GET
def visit(request,pk):
    access=patient_access(request.user)
    v=get_object_or_404(Visit.objects.select_related("clinic","dentist"),pk=pk,patient_id=access.patient_id)
    return render(request,"portal/visit.html",{"visit":v,"can_cancel":v.status=="SCHEDULED" and v.scheduled_start>timezone.now()})

@login_required(login_url="portal_login")
@require_http_methods(["GET","POST"])
def cancel(request,pk):
    access=patient_access(request.user)
    v=get_object_or_404(Visit.objects.select_related("clinic","dentist"),pk=pk,patient_id=access.patient_id)
    form=CancelForm(request.POST or None,initial={"expected_version":v.lock_version})
    if request.method=="POST" and form.is_valid():
        try: cancel_booking(actor=request.user,visit_id=v.pk,expected_version=form.cleaned_data["expected_version"],reason=form.cleaned_data["reason"])
        except EXPECTED_ERRORS as exc: add_error(form,exc)
        else:
            messages.success(request,"本次预约已取消，历史记录仍保留。")
            return redirect("portal_visit",pk=v.pk)
    return render(request,"portal/cancel.html",{"visit":v,"form":form})

@login_required(login_url="portal_login")
@require_GET
def help_page(request):
    patient_access(request.user)
    return render(request,"portal/help.html",{})
