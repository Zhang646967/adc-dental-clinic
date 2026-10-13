"""Manager-only, clinic-scoped availability screens. No clinical/patient lists."""
from urllib.parse import urlencode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from adc_core.http_support import EXPECTED_ERRORS, add_error
from care.models import AuditEvent
from scheduling.intake_rules import ACTIONS as INTAKE_ACTIONS, REASONS as INTAKE_REASONS
from scheduling.models import AvailabilitySlot
from scheduling.availability_forms import SlotChangeForm, SlotConfirmForm
from scheduling.availability_rules import ACTIONS, LOCAL_ZONE, REASONS, display_time
from scheduling.availability_services import (EVENTS, require_availability_actor, inspect_availability,
    prepare_availability_change, confirm_availability_change)


def _card(snapshot):
    slot=snapshot.slot
    return {'id':slot.pk,'clinic':slot.clinic.name,'dentist':slot.dentist.name,
        'employee_no':slot.dentist.employee_no,'start':display_time(slot.starts_at),
        'end':display_time(slot.ends_at),'active':slot.is_active,'paused':slot.booking_paused,'future':slot.starts_at>snapshot.observed_at,
        'intake_editable':slot.is_active and slot.ends_at>snapshot.observed_at}


def _data(snapshot):
    return {'slot':_card(snapshot),'impact':snapshot.impact,'blocked':snapshot.blocked,
        'observed_at':display_time(snapshot.observed_at),'read_only':settings.ADC_READ_ONLY,
        'can_replace':not snapshot.blocked and snapshot.facts['clinic_active'] and snapshot.facts['dentist_active']}


@login_required
@never_cache
@require_GET
def listing(request):
    ctx=require_availability_actor(request.user)
    mode=request.GET.get('mode','future')
    if mode not in ('future','inactive','all'):mode='future'
    qs=AvailabilitySlot.objects.filter(clinic_id=ctx.clinic_id).select_related('clinic','dentist').order_by('starts_at','id')
    if mode=='future':qs=qs.filter(is_active=True,ends_at__gt=timezone.now())
    elif mode=='inactive':qs=qs.filter(is_active=False)
    page=Paginator(qs,25).get_page(request.GET.get('page'))
    now=timezone.now()
    rows=[{'id':s.pk,'dentist':s.dentist.name,'employee_no':s.dentist.employee_no,
        'start':display_time(s.starts_at),'end':display_time(s.ends_at),'active':s.is_active,'paused':s.booking_paused,
        'started':s.starts_at<=now} for s in page]
    require_availability_actor(request.user)
    base=reverse('availability_list')
    prev=base+'?'+urlencode({'mode':mode,'page':page.previous_page_number()}) if page.has_previous() else ''
    nxt=base+'?'+urlencode({'mode':mode,'page':page.next_page_number()}) if page.has_next() else ''
    return render(request,'scheduling/availability_list.html',{'rows':rows,'mode':mode,'page':page,
        'previous_url':prev,'next_url':nxt,'read_only':settings.ADC_READ_ONLY})


@login_required
@never_cache
@require_GET
def detail(request,pk):
    snapshot,_=inspect_availability(actor=request.user,slot_id=pk)
    rows=AuditEvent.objects.filter(subject_type='availabilityslot',subject_key=str(pk),event_type__in=(*EVENTS, 'SLOT_INTAKE_PAUSED', 'SLOT_INTAKE_RESUMED')).order_by('-id')[:10]
    history=[{'action':(ACTIONS|INTAKE_ACTIONS).get(e.change_summary.get('action'),'出诊维护'),
        'at':display_time(e.occurred_at),'reason':(REASONS|INTAKE_REASONS).get(e.change_summary.get('reason_code'),'已记录的依据'),
        'replacement':e.change_summary.get('replacement_id')} for e in rows]
    source=AuditEvent.objects.filter(subject_type='availabilityslot',subject_key=str(pk),event_type='SLOT_CREATED').order_by('-id').first()
    predecessor=source.change_summary.get('predecessor_slot_id') if source else None
    require_availability_actor(request.user)
    return render(request,'scheduling/availability_detail.html',_data(snapshot)|{'history':history,'predecessor':predecessor})


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def change(request,pk,action):
    if action not in ACTIONS:raise Http404
    snapshot,state_token=inspect_availability(actor=request.user,slot_id=pk)
    if snapshot.blocked:
        return render(request,'scheduling/availability_blocked.html',_data(snapshot),status=409)
    slot=snapshot.slot
    form=SlotChangeForm(request.POST if request.method=='POST' else None,action=action,initial={
        'state_token':state_token,'start':slot.starts_at.astimezone(LOCAL_ZONE).replace(tzinfo=None),
        'end':slot.ends_at.astimezone(LOCAL_ZONE).replace(tzinfo=None)})
    if request.method=='POST' and form.is_valid():
        try:
            preview=prepare_availability_change(actor=request.user,slot_id=pk,state_token=form.cleaned_data['state_token'],
                action=action,reason_code=form.cleaned_data['reason_code'],start=form.cleaned_data.get('start'),end=form.cleaned_data.get('end'))
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            return render(request,'scheduling/availability_confirm.html',{'preview':preview,
                'form':SlotConfirmForm(initial={'proposal_token':preview.proposal_token}),'read_only':settings.ADC_READ_ONLY})
    return render(request,'scheduling/availability_change.html',_data(snapshot)|{'form':form,'action':action,'action_label':ACTIONS[action]})


@login_required
@never_cache
@sensitive_post_parameters()
@require_POST
def confirm(request,pk):
    require_availability_actor(request.user)
    form=SlotConfirmForm(request.POST)
    if form.is_valid():
        try:
            result=confirm_availability_change(actor=request.user,slot_id=pk,
                proposal_token=form.cleaned_data['proposal_token'],confirmed=form.cleaned_data['confirmed'])
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        except DatabaseError:
            return render(request,'scheduling/availability_recovery.html',{'slot_id':pk,
                'problem':'暂时无法核对保存结果，不代表此前一定失败。请先查询原时段及其维护记录；不要自动重试或重复新增。'},status=503)
        else:
            messages.success(request,'该操作此前已完成，没有重复执行；请核对当前状态。' if result.repeated else
                '原时段已停用并保留历史；替代时段已建立。原预约、候补和账单没有被修改。' if result.replacement_id else
                '原出诊时段已停用并保留历史，没有取消或改动患者预约。')
            return redirect('availability_detail',pk=result.source_id)
    return render(request,'scheduling/availability_recovery.html',{'slot_id':pk,'errors':form.errors,
        'problem':'本次确认未执行。请先核对原出诊及关联业务，再重新开始；先前已经成功的操作不会被撤销。'},status=409)
