from scheduling.resources import enabled
from scheduling.front_coordination_links import offer_return_slot, return_context
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods,require_POST
from adc_core.http_support import EXPECTED_ERRORS,add_error
from coordination.models import WaitRequest,WaitOffer,SchedulePlan
from coordination.policies import entries_for,require_owner_or_front
from coordination.forms import JoinForm,ConfirmForm
from coordination import services
from portal.policies import form_authority,read_form_authority

def patient_stamp(request):
    return read_form_authority(request.user,request.POST.get('patient_authority','')) if request.workspace.role=='PATIENT' else None

def confirmation(request):
    return ConfirmForm(request.POST or None,initial={'patient_authority':form_authority(request.user)} if request.workspace.role=='PATIENT' else {})

def template_for(request):return 'portal/base.html' if request.workspace.role=='PATIENT' else 'base.html'

def entry_row(request,e):
    patient_visible=request.workspace.role in ('PATIENT','FRONT_DESK')
    offers=[]
    for o in e.offers.select_related('slot__dentist','slot__clinic').order_by('-id')[:5]:
        offers.append({'id':o.pk,'doctor':o.slot.dentist.name,'start':o.starts_at,'end':o.ends_at,
            'expires':o.expires_at,'state':o.state,'visit_id':o.visit_id,
            'status':o.get_state_display(),'active':o.state=='PENDING' and o.expires_at>timezone.now(),
            'may_answer':patient_visible and o.state=='PENDING' and o.expires_at>timezone.now()})
    return {'id':e.pk,'state':e.state,'label':e.get_state_display(),'clinic':e.clinic.name,
        'patient':e.patient.name if patient_visible else f'候补需求 #{e.pk}',
        'earliest':e.earliest,'latest':e.latest,'offers':offers,
        'can_withdraw':patient_visible and e.state in ('WAITING','OFFERED')}

@login_required
@require_http_methods(['GET'])
def listing(request):
    qs=entries_for(request.user).select_related('patient','clinic').order_by('-created_at')
    from django.core.paginator import Paginator
    page=Paginator(qs,20).get_page(request.GET.get('page'))
    return render(request,'coordination/waitlist.html',{'rows':[entry_row(request,e) for e in page],
        'page':page,'may_join':request.workspace.role in ('PATIENT','FRONT_DESK'),
         'may_recycle':request.workspace.role in ('MANAGER','FRONT_DESK'),
        'may_plan':request.workspace.role == 'FRONT_DESK',
        'waiting_count':qs.filter(state='WAITING').count(),
        'expired_count':WaitOffer.objects.filter(request__in=qs,state='PENDING',expires_at__lte=timezone.now()).count(),
        'has_open_wait':qs.filter(state__in=('WAITING','OFFERED')).exists(),
        'base_template':template_for(request),'confirm_form':ConfirmForm()})

@login_required
@require_http_methods(['GET','POST'])
def join(request):
    form=JoinForm(request.POST or None,user=request.user)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:services.join_waitlist(actor=request.user,clinic_id=d['clinic'].pk,
            dentist_id=d['preferred_dentist'].pk if d['preferred_dentist'] else None,
            patient_no=d.get('patient_no'),earliest=d['earliest'],latest=d['latest'],service_id=d['service'].pk if d.get('service') else None,authority=patient_stamp(request))
        except EXPECTED_ERRORS as e:add_error(form,e)
        else:messages.success(request,'候补已登记，尚未形成预约。');return redirect('waitlist')
    return render(request,'coordination/form.html',{'title':'登记候补偏好','form':form,
        'description':'请选择未来14天内可接受的时间范围，至少能容纳所选服务的完整时长；未启用资源模式时沿用30分钟。登记只是偏好，不是正式预约。',
        'window_limits':form.window_limits,
        'base_template':template_for(request),'button':'确认登记候补'})

@login_required
@require_http_methods(['GET','POST'])
def withdraw(request,pk):
    e=get_object_or_404(entries_for(request.user),pk=pk);require_owner_or_front(request.user,e)
    form=confirmation(request)
    if request.method=='POST' and form.is_valid():
        try:services.withdraw(actor=request.user,entry_id=e.pk,authority=patient_stamp(request))
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:messages.success(request,'候补已退出；既有正式预约不会被取消。');return redirect('waitlist')
    return render(request,'coordination/form.html',{'title':'退出这条候补？','description':'未确认的邀约也会撤回；不会取消已有正式预约。',
        'form':form,'base_template':template_for(request),'button':'确认退出候补'})

@login_required
@require_http_methods(['GET','POST'])
def offer(request,pk):
    o=get_object_or_404(WaitOffer.objects.select_related('request','slot__clinic','slot__dentist'),pk=pk,request__in=entries_for(request.user))
    require_owner_or_front(request.user,o.request)
    origin = offer_return_slot(request.user,request.GET.get("coord_slot"),o)
    form=confirmation(request)
    if request.method=='POST' and form.is_valid():
        action=request.POST.get('action')
        if action not in ('accept','decline'):raise PermissionDenied('未知操作')
        try:services.answer_offer(actor=request.user,offer_id=o.pk,accept=action=='accept',authority=patient_stamp(request))
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            messages.success(request,'已处理候补邀约；接受时产生正式预约，可在预约页面核对。')
            return redirect('front_coordination_detail',pk=origin) if origin else redirect('waitlist')
    replacement_sources=[]
    if request.workspace.role=='PATIENT':
        from scheduling.models import Visit
        sources=Visit.objects.filter(patient_id=o.request.patient_id,clinic_id=o.request.clinic_id,
            status='SCHEDULED',scheduled_start__gt=timezone.now())
        if o.request.service_id:
            sources=sources.filter(resource_plans__is_current=True,resource_plans__service_id=o.request.service_id)
        replacement_sources=list(sources.distinct().order_by('scheduled_start','pk')[:10])
    return render(request,'coordination/offer.html',{'offer':o,'form':form,'base_template':template_for(request),
        'replacement_sources':replacement_sources,
        'active':o.state=='PENDING' and o.expires_at>timezone.now(),**return_context(origin)})

@login_required
@require_http_methods(['GET','POST'])
def plans(request):
    from scheduling.availability_services import require_availability_actor
    cid=require_availability_actor(request.user).clinic_id
    form=confirmation(request)
    if request.method=='POST' and form.is_valid():
        try:p=services.create_plan(actor=request.user,clinic_id=cid)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return redirect('schedule_plan',pk=p.pk)
    return render(request,'coordination/plans.html',{'plans':SchedulePlan.objects.filter(clinic_id=cid).order_by('-created_at')[:30],'form':form,
        'resource_mode':enabled(cid)})

@login_required
@require_http_methods(['GET','POST'])
def plan(request,pk):
    from scheduling.availability_services import require_availability_actor
    cid=require_availability_actor(request.user).clinic_id
    p=get_object_or_404(SchedulePlan,pk=pk,clinic_id=cid)
    form=confirmation(request)
    if request.method=='POST' and form.is_valid():
        try:services.publish_plan(actor=request.user,plan_id=p.pk)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:messages.success(request,'已发出限时邀约，尚未替患者确认预约。');return redirect('schedule_plan',pk=p.pk)
    from scheduling.models import AvailabilitySlot
    rows=[]
    from datetime import datetime
    published_offers = {o.request_id:o for o in p.offers.all()}
    for s in p.suggestions:
        slot=AvailabilitySlot.objects.select_related('dentist').filter(pk=s['slot_id']).first()
        rows.append({'request_id':s['request_id'],'doctor':slot.dentist.name if slot else '时段已不可用',
            'start':datetime.fromisoformat(s['start']),'end':datetime.fromisoformat(s['end']),
            'offer':published_offers.get(s['request_id'])})
    return render(request,'coordination/plan.html',{'plan':p,'rows':rows,'form':form})

@login_required
@require_POST
def recycle(request):
    form=ConfirmForm(request.POST)
    if form.is_valid():
        try:n=services.expire_clinic_offers(actor=request.user,clinic_id=request.workspace.clinic_id)
        except EXPECTED_ERRORS as exc:messages.error(request,str(exc))
        else:messages.success(request,f'已回收 {n} 条过期邀约。需求可再次参与匹配。')
    else:messages.error(request,'请勾选确认后再回收。')
    return redirect('waitlist')
