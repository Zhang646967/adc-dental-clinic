"""Scoped task UI. No route accepts arbitrary redirect URLs or writes on GET."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from datetime import timedelta
from django.utils import timezone
from django.http import Http404
from django.shortcuts import render,redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from adc_core.http_support import EXPECTED_ERRORS,add_error
from adc_core.rules import RuleError
from coordination.task_forms import TaskChangeForm,TaskConfirmForm
from coordination.task_rules import ACTIONS
from coordination.task_services import require_task_actor,list_tasks,inspect_task,prepare_task,confirm_task
from scheduling.front_coordination_rules import origin_id


def recovery(request,slot_id=None,task_id=None,*,problem,errors=None,status=409):
    return render(request,'coordination/tasks/recovery.html',dict(slot_id=slot_id,task_id=task_id,
        problem=problem,errors=errors),status=status)

@login_required
@never_cache
@require_GET
def listing(request):
    require_task_actor(request.user)
    raw=request.GET.get('slot','');slot_id=origin_id(raw) if raw else None
    if raw and slot_id is None:
        return recovery(request,problem='出诊编号无效，请返回任务列表重新查询。',status=400)
    try:
        result=list_tasks(actor=request.user,mode=request.GET.get('mode','active'),slot_id=slot_id,page=request.GET.get('page','1'))
    except RuleError as exc: return recovery(request,problem=str(exc),status=400)
    except DatabaseError: return recovery(request,problem='本次任务查询不可用，不代表任务或预约办理失败，请稍后重新核对。',status=503)
    return render(request,'coordination/tasks/list.html',dict(result=result))

@login_required
@never_cache
@require_GET
def detail(request,slot_id,task_id):
    require_task_actor(request.user)
    try: data,_=inspect_task(actor=request.user,slot_id=slot_id,task_id=task_id)
    except (DatabaseError,ValueError):
        return recovery(request,slot_id,task_id,problem='本次关联事实读取不完整，结果未知；不自动重发任何操作。',status=503)
    return render(request,'coordination/tasks/detail.html',dict(data=data,read_only=settings.ADC_READ_ONLY))

@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def change(request,slot_id,task_id=None,action='open'):
    if action not in ACTIONS or ((task_id is None)!=(action=='open')): raise Http404
    require_task_actor(request.user)
    try: data,token=inspect_task(actor=request.user,slot_id=slot_id,task_id=task_id)
    except (DatabaseError,ValueError):
        return recovery(request,slot_id,task_id,problem='暂时无法核对任务事实；没有自动创建或办理预约。',status=503)
    allowed=any(row['key']==action for row in data['actions'])
    if not allowed:
        problem=next((r['reason'] for r in data['blocked'] if r['action']==ACTIONS[action]),'当前身份或任务状态不允许此操作。')
        return recovery(request,slot_id,task_id,problem=problem,status=409)
    form=TaskChangeForm(request.POST if request.method=='POST' else None,action=action,initial={
        'state_token':token,'due_at':data.get('due_at') or timezone.now()+timedelta(hours=4)})
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:
            preview=prepare_task(actor=request.user,slot_id=slot_id,task_id=task_id,state_token=d['state_token'],
                action=action,reason=d['reason'],purpose=d.get('purpose',''),target_kind=d.get('target_kind',''),target_id=d.get('target_id'),due_at=d.get('due_at'))
        except EXPECTED_ERRORS as exc: add_error(form,exc)
        except DatabaseError: return recovery(request,slot_id,task_id,problem='预览读取不可用，尚未保存；请重新查询。',status=503)
        else:
            return render(request,'coordination/tasks/confirm.html',dict(preview=preview,
                form=TaskConfirmForm(initial={'proposal_token':preview['proposal_token']}),read_only=settings.ADC_READ_ONLY))
    return render(request,'coordination/tasks/change.html',dict(data=data,action=action,action_label=ACTIONS[action],form=form,read_only=settings.ADC_READ_ONLY))

@login_required
@never_cache
@sensitive_post_parameters()
@require_POST
def confirm(request,slot_id,task_id=None):
    require_task_actor(request.user)
    form=TaskConfirmForm(request.POST)
    if form.is_valid():
        try:
            result=confirm_task(actor=request.user,slot_id=slot_id,task_id=task_id,
                proposal_token=form.cleaned_data['proposal_token'],confirmed=form.cleaned_data['confirmed'])
        except EXPECTED_ERRORS as exc: add_error(form,exc)
        except DatabaseError:
            return recovery(request,slot_id,task_id,problem='暂时不能核对提交结果。先按原出诊查询任务；不要重复创建，也不要推断预约办理失败。',status=503)
        else:
            messages.success(request,'原任务操作此前已完成，本次没有重复写入；请核对当前状态。' if result.repeated else
                             '协调任务已更新。预约、邀约和出诊接收状态未被本操作改变。')
            return redirect('coordination_task_detail',slot_id=result.slot_id,task_id=result.task_id)
    return recovery(request,slot_id,task_id,problem='本次确认未执行；请重新读取任务及关联事实。',errors=form.errors,status=409)
