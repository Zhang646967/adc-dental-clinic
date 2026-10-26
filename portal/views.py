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
from scheduling.resources import service_for
from scheduling.models import Visit
from portal.forms import BookingConfirmationForm, CancelForm, SlotFilterForm
from portal.policies import patient_access, form_authority, read_form_authority
from portal.services import public_options, preview_booking, confirm_booking, cancel_booking

class PortalLoginView(LoginView):
    login_channel='PATIENT'
    template_name = "portal/login.html"
    def get_success_url(self):
        return reverse("select_role")

    def chosen_service(self):
        from scheduling.service_content import positive_id
        from portal.service_catalogue import public_profiles
        raw=self.request.POST.get('booking_service','') if self.request.method=='POST' else self.request.GET.get('service','')
        selected=positive_id(raw)
        return next((p for p in public_profiles() if p.service_id==selected),None) if selected else None

    def get_context_data(self,**kwargs):
        from portal.auth_views import login_context
        context=super().get_context_data(**kwargs)
        context.update(login_context(self.request,form=context['form'],booking_service=self.chosen_service()))
        return context

    def post(self,request,*args,**kwargs):
        if request.POST.get('action') in ('send','confirm'):
            from portal.auth_views import sms
            return sms(request,inline=True)
        return super().post(request,*args,**kwargs)

    def get(self,request,*args,**kwargs):
        # A signed-in patient can continue without another password prompt.
        # Only read an existing context: GET never activates a role or creates it.
        if request.user.is_authenticated:
            from workspaces.context import existing_context,valid_context
            ctx=existing_context(request)
            if ctx and ctx.role=='PATIENT' and valid_context(request.user,ctx):
                profile=self.chosen_service()
                if profile and profile.category!='CHILDREN':
                    return redirect(reverse('portal_slots')+'?service='+str(profile.service_id))
        return super().get(request,*args,**kwargs)

    def form_valid(self,form):
        response=super().form_valid(form)
        if response.status_code!=302:return response
        if response.url==reverse('patient_account'):
            from portal.account_access import remember_pending_service
            remember_pending_service(self.request,self.chosen_service().service_id if self.chosen_service() else None)
            return response
        # The ordinary authenticated activation completes first. This typed
        # service hint cannot choose a role, clinic scope or arbitrary URL.
        from portal.booking_intent import remember_service,destination_after_activation
        profile=self.chosen_service()
        if profile and profile.category!='CHILDREN':
            remember_service(self.request,profile.service_id)
            destination=destination_after_activation(self.request)
            if destination:return redirect(destination)
        return response

@login_required(login_url="portal_login")
@require_GET
def home(request):
    from portal.patient_dashboard import dashboard
    overview=dashboard(request.user)
    from workspaces.worklists import workspace_worklist
    return render(request,"portal/home.html",dict(overview, worklist=workspace_worklist(request.user)))

@login_required(login_url="portal_login")
@require_GET
def appointments(request):
    access=patient_access(request.user)
    qs=access.scope(Visit.objects.all()).select_related("clinic","dentist")
    queue=request.GET.get('queue','active')
    if queue not in ('active','history','all'): raise Http404
    counts={'active':qs.filter(status__in=['SCHEDULED','CHECKED_IN']).count(),'all':qs.count()}
    counts['history']=counts['all']-counts['active']
    if queue=='active':qs=qs.filter(status__in=['SCHEDULED','CHECKED_IN']).order_by('scheduled_start','pk')
    elif queue=='history':qs=qs.exclude(status__in=['SCHEDULED','CHECKED_IN'])
    return render(request,"portal/appointments.html",{"page":Paginator(qs,10).get_page(request.GET.get("page")),
        'queue':queue,'queues':[(k,n,counts[k]) for k,n in [('active','待就诊与在诊'),('history','历史与改期记录'),('all','全部')]]})

@login_required(login_url="portal_login")
@require_GET
def slots(request):
    patient_access(request.user)
    form=SlotFilterForm(request.GET or None,actor=request.user)
    rows=[];profile=None;searched=False;query_failed=False
    if form.is_valid():
        searched=True
        profile=form.cleaned_data['service'].patient_presentation
        try: rows=public_options(request.user,form.cleaned_data['clinic'].pk if form.cleaned_data.get('clinic') else None,form.cleaned_data["day"],
            form.cleaned_data['service'].pk if form.cleaned_data.get('service') else None,
            form.cleaned_data['dentist'].pk if form.cleaned_data.get('dentist') else None)
        except EXPECTED_ERRORS as exc:
            add_error(form,exc);query_failed=True
    return render(request,"portal/slots.html",{'rows':rows,'form':form,'selected_profile':profile,
        'searched':searched,'query_failed':query_failed})

@login_required(login_url="portal_login")
@require_http_methods(["GET","POST"])
def booking_preview(request):
    patient_access(request.user)
    if request.method=="POST":
        form=BookingConfirmationForm(request.POST)
        if form.is_valid():
            try: v=confirm_booking(actor=request.user,token=form.cleaned_data["token"],patient_request=form.cleaned_data['patient_request'],require_published_service=True)
            except EXPECTED_ERRORS as exc: add_error(form,exc)
            else:
                messages.success(request,"预约已经保存。相同确认页的重复提交不会再建一条。")
                return redirect("portal_visit",pk=v.pk)
        return render(request,"portal/confirm.html",{"form":form,"failed":True})
    try:
        from portal.service_catalogue import public_profiles
        from scheduling.service_content import positive_id
        selected=positive_id(request.GET.get('service',''))
        profile=next((p for p in public_profiles() if p.service_id==selected),None)
        if not profile:raise RuleError('请先选择已开放的预约服务。')
        from portal.service_catalogue import require_self_service
        require_self_service(selected,actor=request.user)
        start=parse_datetime(request.GET.get("start",""))
        if start is None or timezone.is_naive(start): raise RuleError("请选择有效时段。")
        slot,end,token=preview_booking(user=request.user,slot_id=int(request.GET.get("slot","0")),start=start,service_id=int(request.GET["service"]) if request.GET.get("service") else None)
    except (ValueError, *EXPECTED_ERRORS):
        messages.error(request,"该时段已变化，请重新选择。")
        return redirect("portal_slots")
    return render(request,"portal/confirm.html",{"slot":slot,"start":start,"end":end,
        "service_label":profile.title,"selected_profile":profile,
        "form":BookingConfirmationForm(initial={"token":token})})

@login_required(login_url="portal_login")
@require_GET
def visit(request,pk):
    access=patient_access(request.user)
    v=get_object_or_404(access.scope(Visit.objects.select_related("clinic","dentist")),pk=pk)
    from portal.rescheduling import related_context
    return render(request,"portal/visit.html",dict(related_context(request.user,v),visit=v,
        can_cancel=v.status=="SCHEDULED" and v.scheduled_start>timezone.now()))

@login_required(login_url="portal_login")
@require_http_methods(["GET","POST"])
def cancel(request,pk):
    access=patient_access(request.user)
    v=get_object_or_404(access.scope(Visit.objects.select_related("clinic","dentist")),pk=pk)
    form=CancelForm(request.POST or None,initial={"expected_version":v.lock_version,"patient_authority":form_authority(request.user)})
    if request.method=="POST" and form.is_valid():
        try: cancel_booking(actor=request.user,visit_id=v.pk,expected_version=form.cleaned_data["expected_version"],reason=form.cleaned_data["reason"],authority=read_form_authority(request.user,form.cleaned_data.get("patient_authority")))
        except EXPECTED_ERRORS as exc: add_error(form,exc)
        else:
            messages.success(request,"本次预约已取消，历史记录仍保留。")
            return redirect("portal_visit",pk=v.pk)
    return render(request,"portal/cancel.html",{"visit":v,"form":form})

@login_required(login_url="portal_login")
@require_GET
def help_page(request):
    access=patient_access(request.user)
    own=access.scope(Visit.objects.all()).filter(pk=request.GET.get('visit')).select_related('clinic').first() if request.GET.get('visit','').isdigit() else None
    return render(request,"portal/help.html",{'help_visit':own})
