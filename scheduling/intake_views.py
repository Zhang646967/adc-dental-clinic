"""Current-clinic MANAGER only. Explicit state change, no automatic actions."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import render, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST
from adc_core.http_support import EXPECTED_ERRORS, add_error
from scheduling.availability_services import require_availability_actor
from scheduling.availability_rules import display_time
from scheduling.intake_rules import ACTIONS
from scheduling.intake_forms import IntakeChangeForm, IntakeConfirmForm
from scheduling.intake_services import inspect_intake, prepare_intake, confirm_intake

@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def change(request,pk,action):
    if action not in ACTIONS: raise Http404
    snapshot,state_token = inspect_intake(actor=request.user,slot_id=pk)
    form = IntakeChangeForm(request.POST if request.method=='POST' else None, action=action,
                            initial={'state_token':state_token})
    if request.method=='POST' and form.is_valid():
        try:
            preview=prepare_intake(actor=request.user,slot_id=pk,state_token=form.cleaned_data['state_token'],
                action=action,reason=form.cleaned_data['reason'])
        except EXPECTED_ERRORS as exc: add_error(form,exc)
        else:
            return render(request,'scheduling/intake_confirm.html',dict(preview=preview,
                form=IntakeConfirmForm(initial={'proposal_token':preview['proposal_token']}),
                read_only=settings.ADC_READ_ONLY))
    s=snapshot.slot
    return render(request,'scheduling/intake_change.html',dict(slot_id=pk,clinic=s.clinic.name,
        dentist=s.dentist.name,start=display_time(s.starts_at),end=display_time(s.ends_at),
        paused=s.booking_paused, action=action, action_label=ACTIONS[action],
        form=form,impact=snapshot.impact,read_only=settings.ADC_READ_ONLY))

@login_required
@never_cache
@sensitive_post_parameters()
@require_POST
def confirm(request,pk):
    require_availability_actor(request.user)
    form=IntakeConfirmForm(request.POST)
    if form.is_valid():
        try:
            result=confirm_intake(actor=request.user,slot_id=pk,
                proposal_token=form.cleaned_data['proposal_token'],confirmed=form.cleaned_data['confirmed'])
        except EXPECTED_ERRORS as exc: add_error(form,exc)
        except DatabaseError:
            return render(request,'scheduling/availability_recovery.html',dict(slot_id=pk,
                problem='暂时无法核对接收状态，不代表前次操作失败；请先查看原出诊，不自动重发。'),status=503)
        else:
            text='原操作此前已完成，没有重新执行。请核对当前接收状态。' if result.repeated else (
                '已暂停新增预约和新邀约；已有预约、接诊及仍有效的邀约保持。' if result.paused else
                '已恢复接收新预约。尚未形成的安排仍需重新选择、核验并明确确认。')
            messages.success(request,text)
            return redirect('availability_detail',pk=pk)
    return render(request,'scheduling/availability_recovery.html',dict(slot_id=pk,errors=form.errors,
        problem='本次接收状态确认未执行，请重新核对；前次已成功的操作不会因此被撤销。'),status=409)
