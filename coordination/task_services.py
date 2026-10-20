"""SU34-36: current-clinic manager/frontdesk task workflow.
Canonical write locks: actor -> context -> active grant -> source slot -> task.
No Visit/WaitOffer/slot/clinical/financial/account mutations. Transactional notice intent only; no transport.
"""
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from accounts.policies import bindings, lock_clinic_grant
from adc_core.commands import business_errors
from adc_core.rules import RuleError
from care.audit import emit
from care.models import AuditEvent
from coordination.models import CoordinationTask
from coordination.task_facts import observe_locked, check_statement_target
from coordination.task_rules import (CONTRACT, ACTIVE_STATES, STATES, PURPOSES, ACTIONS, REASONS,
    ACTION_REASONS, MANAGER_ACTIONS, FRONT_ACTIONS, TaskError, review_gate, validate_step,
    validate_options, validate_payload)
from scheduling.availability_rules import digest, display_time, positive_id, parse_time
from scheduling.coordination import lock_slots
from scheduling.models import AvailabilitySlot
from workspaces.context import require_active, valid_context
from workspaces.models import WorkspaceContext

SALT = 'adc.coordination.task.b131'
MAX_AGE = 900
EVENT_TYPES = dict(open='TASK_CREATED',claim='TASK_CLAIMED',progress='TASK_REPORTED',
    release='TASK_RELEASED',submit='TASK_SUBMITTED',return_='TASK_REQUEUED',
    approve='TASK_APPROVED',cancel='TASK_CANCELLED')
EVENT_TYPES['return'] = EVENT_TYPES.pop('return_')

@dataclass(frozen=True)
class TaskResult:
    task_id: int
    slot_id: int
    state: str
    event_id: int
    repeated: bool


def require_task_actor(actor):
    ctx = getattr(actor,'_adc_workspace',None)
    if ctx is None or ctx.role not in ('MANAGER','FRONT_DESK') or ctx.clinic_id is None:
        raise PermissionDenied('请以当前诊所主管或前台身份进入协调任务。')
    require_active(actor,('MANAGER','FRONT_DESK'),ctx.clinic_id)
    if not valid_context(actor,ctx) or not WorkspaceContext.objects.filter(pk=ctx.pk,user_id=actor.pk,
            role=ctx.role,clinic_id=ctx.clinic_id,revision=ctx.revision).exists():
        raise PermissionDenied('当前工作身份或诊所已经变化。')
    if not bindings(actor).filter(role=ctx.role,scope_kind='CLINIC',clinic_id=ctx.clinic_id).exists():
        raise PermissionDenied('当前诊所授权已失效。')
    return ctx


def _binding(actor):
    c = require_task_actor(actor)
    return dict(contract=CONTRACT,actor=actor.pk,role=c.role,context=str(c.pk),
                context_revision=c.revision,clinic=c.clinic_id)


def _owned_slot(actor,slot_id):
    ctx = require_task_actor(actor)
    try: positive_id(slot_id)
    except ValueError: raise PermissionDenied('出诊不存在或不属于当前诊所。') from None
    if not AvailabilitySlot.objects.filter(pk=slot_id,clinic_id=ctx.clinic_id).exists():
        raise PermissionDenied('出诊不存在或不属于当前诊所。')
    slot = lock_slots([slot_id])[slot_id]
    if slot.clinic_id != ctx.clinic_id: raise PermissionDenied('出诊范围已改变。')
    return slot


def _task_data(t):
    if t is None: return None
    return dict(id=t.pk,state=t.state,revision=t.revision,purpose=t.purpose,
                assignee_id=t.assignee_id,submitted_by_id=t.submitted_by_id,
                submitted_digest=t.submitted_digest,due_at=t.due_at.isoformat() if t.due_at else None)


def _locked_task(slot_id,task_id):
    if task_id is None: return None
    try: positive_id(task_id)
    except ValueError: raise PermissionDenied('任务不存在或不属于当前出诊。') from None
    t = CoordinationTask.objects.select_for_update().filter(pk=task_id,slot_id=slot_id).first()
    if t is None: raise PermissionDenied('任务不存在或不属于当前出诊。')
    return t


def _current(slot,task):
    obs = observe_locked(slot)
    active = CoordinationTask.objects.filter(slot=slot,state__in=ACTIVE_STATES).order_by('pk').values_list('pk',flat=True).first()
    state = digest(dict(observation=obs.digest,task=_task_data(task),active_task=active))
    return obs,state,active


def _transition(task,obs,*,action,actor,another_active=False):
    ctx = require_task_actor(actor)
    try:
        return validate_step(_task_data(task),action=action,actor_id=actor.pk,role=ctx.role,
            slot=obs.slot,impact=obs.impact,now=timezone.now(),observation_digest=obs.digest,
            another_active=another_active)
    except TaskError as exc: raise RuleError(str(exc)) from exc


@sensitive_variables()
def _load(token,*,proposal):
    try:
        if type(token) is not str or not 1 <= len(token) <= 6000: raise ValueError()
        return validate_payload(signing.loads(token,salt=SALT,max_age=MAX_AGE),proposal=proposal)
    except (signing.BadSignature,ValueError,TypeError,KeyError):
        raise RuleError('任务页面已过期、被更改或版本不符，请重新读取；不自动重发。') from None


def _bind_payload(actor,data,slot_id,task_id):
    identity = _binding(actor)
    if any(data.get(k)!=v for k,v in identity.items()) or data['slot']!=slot_id or data['task']!=task_id:
        raise PermissionDenied('主体、目标、诊所或工作上下文与确认不符。')
    return identity


def _visible(task,slot,obs):
    return dict(slot_id=slot.pk,clinic=slot.clinic.name,dentist=slot.dentist.name,
        start=display_time(slot.starts_at),end=display_time(slot.ends_at),
        paused=slot.booking_paused,active=slot.is_active,
        task_id=task.pk if task else None,status=STATES[task.state] if task else '尚未发起',
        purpose=PURPOSES[task.purpose] if task else '',
        assignee=task.assignee.username if task and task.assignee_id else '尚未受理',
        creator=task.created_by.username if task else '',
        due_at=task.due_at if task else None,
        overdue=bool(task and task.state in ACTIVE_STATES and task.due_at and task.due_at<timezone.now()),
        observed_at=display_time(obs.observed_at),impact=obs.impact,
        gate=review_gate(obs.slot,obs.impact,obs.observed_at))


@business_errors
@transaction.atomic
def inspect_task(*,actor,slot_id,task_id=None):
    identity = _binding(actor)
    slot = _owned_slot(actor,slot_id)
    task = _locked_task(slot_id,task_id)
    obs,state,active = _current(slot,task)
    # Avoid exposing raw relation rows and patient IDs, including to managers.
    data = _visible(task,slot,obs)
    actions, blocked = [],[]
    candidates = ('open',) if task is None else tuple(a for a in ACTIONS if a!='open')
    allowed_role = MANAGER_ACTIONS if identity['role']=='MANAGER' else FRONT_ACTIONS
    for action in candidates:
        if action not in allowed_role: continue
        try: _transition(task,obs,action=action,actor=actor,another_active=bool(active))
        except RuleError as exc: blocked.append(dict(action=ACTIONS[action],reason=str(exc)))
        else: actions.append(dict(key=action,label=ACTIONS[action]))
    qs = AuditEvent.objects.filter(subject_type='coordinationtask',subject_key=str(task.pk),
                                  event_type__in=EVENT_TYPES.values()).order_by('-pk') if task else AuditEvent.objects.none()
    history = []
    for event in qs.select_related('actor')[:30]:
        s=event.change_summary if isinstance(event.change_summary,dict) else {}
        action=s.get('action')
        if action not in ACTIONS: continue
        row=dict(action=ACTIONS[action],actor=event.actor.username if event.actor_id else '历史操作者',
                 at=display_time(event.occurred_at),reason=REASONS.get(s.get('reason_code'),'已记录依据'),
                 statement=action=='progress')
        if identity['role']=='FRONT_DESK' and s.get('target_kind') in ('visit','offer'):
            # Returned as plain reference only. Original business destination reauthorizes.
            row['target'] = ('预约' if s['target_kind']=='visit' else '邀约') + ' #' + str(s.get('target_id',''))
        history.append(row)
    data.update(actions=actions,blocked=blocked,active_task_id=active,history=history,
                terminal=bool(task and task.state not in ACTIVE_STATES),
                awaiting_review=bool(task and task.state=='READY'),role=identity['role'],
                history_total=qs.count(),is_owner=bool(task and task.assignee_id==actor.pk))
    state_token=signing.dumps(identity | dict(kind='state',slot=slot_id,task=task_id,state=state),salt=SALT)
    if _binding(actor)!=identity: raise PermissionDenied('工作范围已改变，不返回旧数据。')
    return data,state_token


@business_errors
@transaction.atomic
@sensitive_variables()
def prepare_task(*,actor,slot_id,task_id,state_token,action,reason,purpose='',target_kind='',target_id=None,due_at=None):
    data = _load(state_token,proposal=False)
    identity = _bind_payload(actor,data,slot_id,task_id)
    try: validate_options(action,reason,purpose=purpose,target_kind=target_kind,target_id=target_id)
    except ValueError as exc: raise RuleError(str(exc)) from exc
    slot = _owned_slot(actor,slot_id); task = _locked_task(slot_id,task_id)
    obs,state,active = _current(slot,task)
    if data['state']!=state: raise RuleError('任务、出诊或关联业务已变化；请重新核对，尚未保存。')
    new_state = _transition(task,obs,action=action,actor=actor,another_active=bool(active))
    if action=='progress':
        try: check_statement_target(obs,kind=target_kind,target_id=target_id)
        except TaskError as exc: raise RuleError(str(exc)) from exc
    deadline=None
    if action in ('open','claim','progress'):
        now=timezone.now()
        deadline=due_at
        if deadline is None:
            deadline=task.due_at if task and task.due_at and task.due_at>now else now+timedelta(hours=4)
            if slot.starts_at>now:deadline=min(deadline,slot.starts_at)
        if timezone.is_naive(deadline) or deadline<=now:raise RuleError('请填写未来的下次跟进期限。')
    payload = identity | dict(kind='proposal',slot=slot_id,task=task_id,state=state,
        operation=str(uuid4()),action=action,reason=reason,purpose=purpose,
        target_kind=target_kind,target_id=target_id,due_at=deadline.isoformat() if deadline else None)
    visible = _visible(task,slot,obs) | dict(action=action,action_label=ACTIONS[action],
        reason=REASONS[reason],after=STATES[new_state],purpose=PURPOSES[purpose] if purpose else PURPOSES[task.purpose],
        target_label=(('预约' if target_kind=='visit' else '邀约')+' #'+str(target_id)) if target_kind else '',
        due_at=deadline or (task.due_at if task else None),proposal_token=signing.dumps(payload,salt=SALT))
    if _binding(actor)!=identity: raise PermissionDenied('工作范围已改变。')
    return visible


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm_task(*,actor,slot_id,task_id,proposal_token,confirmed):
    if confirmed is not True: raise RuleError('请明确核对任务影响后再确认。')
    ctx = require_task_actor(actor)
    lock_clinic_grant(actor,ctx.clinic_id,roles=(ctx.role,))
    data = _load(proposal_token,proposal=True)
    _bind_payload(actor,data,slot_id,task_id)
    slot = _owned_slot(actor,slot_id); task = _locked_task(slot_id,task_id)
    event = AuditEvent.objects.filter(actor_id=actor.pk,subject_type='coordinationtask',
        event_type__in=EVENT_TYPES.values(),change_summary__slot_id=slot_id,
        change_summary__operation=data['operation']).first()
    if event:
        if event.change_summary.get('proposal_digest')!=digest(data):
            raise RuleError('原操作关联需要核对，不能重放。')
        previous=CoordinationTask.objects.filter(pk=event.subject_key,slot_id=slot_id).first()
        if previous is None or (task_id is not None and previous.pk!=task_id):
            raise RuleError('原任务结果需要核对。')
        return TaskResult(previous.pk,slot_id,previous.state,event.pk,True)
    obs,state,active = _current(slot,task)
    if state!=data['state']: raise RuleError('预览后事实已变化，本次未保存；请重新读取。')
    next_state = _transition(task,obs,action=data['action'],actor=actor,another_active=bool(active))
    action=data['action']; now=timezone.now()
    deadline=parse_time(data['due_at']) if data['due_at'] else None
    if action in ('open','claim','progress') and (deadline is None or deadline<=now):
        raise RuleError('跟进期限已到，请重新核对责任及下次期限。')
    if action=='progress':
        try: check_statement_target(obs,kind=data['target_kind'],target_id=data['target_id'])
        except TaskError as exc: raise RuleError(str(exc)) from exc
    if action=='open':
        task=CoordinationTask.objects.create(slot=slot,purpose=data['purpose'],opening_reason=data['reason'],
            creation_operation=data['operation'],created_by=actor,state='OPEN',due_at=deadline)
    else:
        task.state=next_state; task.revision+=1
        if deadline:task.due_at=deadline
        if action=='claim': task.assignee=actor
        if action in ('release','return'):
            task.assignee=None; task.submitted_by=None; task.submitted_at=None; task.submitted_digest=''
        if action=='submit':
            task.submitted_by=actor; task.submitted_at=now; task.submitted_digest=obs.digest
        if action in ('approve','cancel'):
            task.closed_by=actor; task.closed_at=now
        if action=='cancel':
            task.submitted_by=None; task.submitted_at=None; task.submitted_digest=''
        task.save(update_fields=['state','revision','assignee','submitted_by','submitted_at',
                                'submitted_digest','closed_by','closed_at','due_at','updated_at'])
    summary=dict(contract=CONTRACT,slot_id=slot_id,action=action,operation=data['operation'],
        proposal_digest=digest(data),reason_code=data['reason'],state_after=task.state,
        task_revision=task.revision,assignee_id=task.assignee_id,
        due_at=task.due_at.isoformat() if task.due_at else None,
        observation_digest=obs.digest,blocking_visits=obs.impact.blocking_visits,
        effective_offers=obs.impact.effective_offers,observed_at=obs.observed_at.isoformat())
    if action=='progress': summary.update(statement_only=True,target_kind=data['target_kind'],target_id=data['target_id'])
    event=emit(actor,EVENT_TYPES[action],task,reason=REASONS[data['reason']],summary=summary,occurred_at=now)
    from notifications.enqueue import enqueue_task_notice
    enqueue_task_notice(task=task,event=event,action=action)
    return TaskResult(task.pk,slot_id,task.state,event.pk,False)


def list_tasks(*,actor,mode='active',slot_id=None,page='1'):
    from scheduling.front_coordination_rules import safe_page
    identity=_binding(actor)
    if mode not in ('active','mine','history','all'): raise RuleError('任务筛选项无效。')
    qs=CoordinationTask.objects.filter(slot__clinic_id=identity['clinic'])
    if slot_id is not None:
        try: positive_id(slot_id)
        except ValueError: raise RuleError('请填写正确的出诊编号。') from None
        qs=qs.filter(slot_id=slot_id)
    if mode in ('active','mine'): qs=qs.filter(state__in=ACTIVE_STATES)
    elif mode=='history': qs=qs.exclude(state__in=ACTIVE_STATES)
    if mode=='mine': qs=qs.filter(assignee_id=actor.pk)
    from django.db.models import F
    qs=qs.select_related('slot__clinic','slot__dentist','assignee','created_by').order_by(F('due_at').asc(nulls_last=True),'slot__starts_at','pk')
    total=qs.count(); number,start,pages=safe_page(page,total)
    rows=[]
    for t in qs[start:start+20]:
        rows.append(dict(id=t.pk,slot_id=t.slot_id,status=STATES.get(t.state,'需核对'),purpose=PURPOSES.get(t.purpose,'需核对'),
            dentist=t.slot.dentist.name,start=display_time(t.slot.starts_at),end=display_time(t.slot.ends_at),
            assignee=t.assignee.username if t.assignee_id else '尚未受理',
            due_at=t.due_at,overdue=bool(t.due_at and t.due_at<timezone.now() and t.state in ACTIVE_STATES),
            paused=t.slot.booking_paused,slot_active=t.slot.is_active))
    if _binding(actor)!=identity: raise PermissionDenied('工作范围已变化，不返回旧任务列表。')
    return dict(rows=rows,total=total,number=number,pages=pages,mode=mode,slot_filter=slot_id or '',
                role=identity['role'],observed_at=display_time(timezone.now()))
