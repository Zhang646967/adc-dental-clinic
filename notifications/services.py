"""Current-role/current-clinic inbox and scoped dispatch status. No business actions."""
from django.db import transaction
from django.db.models import F, Count, Min, Q
from django.db.models.functions import Greatest
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from accounts.policies import lock_clinic_grant
from adc_core.rules import RuleError
from care.audit import emit
from coordination.task_services import require_task_actor
from coordination.task_rules import STATES
from notifications.models import NotificationOutbox, InboxMessage
from notifications.rules import title, positive_int, DELIVERY_LABELS, ERROR_LABELS, validate_retry, NOTICE_BOUNDARY
from scheduling.availability_rules import display_time
from scheduling.front_coordination_rules import safe_page


def _identity(actor):
    ctx = require_task_actor(actor)
    return (actor.pk, ctx.role, ctx.clinic_id, str(ctx.pk), ctx.revision)


def _inbox(actor, identity):
    return InboxMessage.objects.filter(recipient_id=actor.pk, role=identity[1],clinic_id=identity[2],
        grant__user_id=actor.pk,grant__role=identity[1],grant__scope_kind='CLINIC',
        grant__clinic_id=identity[2],grant__is_active=True,recipient__is_active=True,
        clinic__is_active=True,event__clinic_id=identity[2],event__task__slot__clinic_id=identity[2])


def list_inbox(*, actor, mode='unread',page='1'):
    identity=_identity(actor)
    if mode not in ('unread','all'): raise RuleError('消息筛选无效。')
    base=_inbox(actor,identity)
    unread=base.filter(read_at__isnull=True).count()
    qs=base.filter(read_at__isnull=True) if mode=='unread' else base
    qs=qs.select_related('event__task').order_by('-event__occurred_at','-event_id','-pk')
    total=qs.count();number,start,pages=safe_page(page,total)
    rows=[]
    for msg in qs[start:start+20]:
        e=msg.event
        rows.append(dict(id=msg.pk,task_id=e.task_id,slot_id=e.task.slot_id,title=title(e.action),
            event_state=STATES.get(e.event_state,'需核对'),current_state=STATES.get(e.task.state,'需核对'),
            event_revision=e.task_revision,current_revision=e.task.revision,
            occurred_at=display_time(e.occurred_at),delivered_at=display_time(msg.delivered_at),
            read_at=display_time(msg.read_at) if msg.read_at else '',read=msg.read_at is not None))
    if identity!=_identity(actor): raise PermissionDenied('工作上下文已变化，不返回旧消息。')
    return dict(rows=rows,total=total,unread=unread,mode=mode,number=number,pages=pages,
                observed_at=display_time(timezone.now()),boundary=NOTICE_BOUNDARY)


@transaction.atomic
def mark_read(*, actor, message_id):
    identity=_identity(actor)
    lock_clinic_grant(actor, identity[2], roles=(identity[1],))
    positive_int(message_id)
    # Only the message is locked; task state is never locked or changed for acknowledgement.
    message=_inbox(actor,identity).select_for_update(of=('self',)).filter(pk=message_id).first()
    if message is None: raise PermissionDenied('消息不存在或不属于当前本人身份与诊所。')
    if message.read_at is None:
        message.read_at=max(timezone.now(),message.delivered_at)
        message.save(update_fields=['read_at'])
    return message.pk


def delivery_status(*, actor, page='1'):
    identity=_identity(actor)
    if identity[1]!='MANAGER': raise PermissionDenied('请以当前店主管身份核对通知派发。')
    qs=NotificationOutbox.objects.filter(clinic_id=identity[2],task__slot__clinic_id=identity[2])
    now=timezone.now()
    due_filter=Q(state='PENDING',next_attempt_at__lte=now)
    overview=qs.aggregate(**{s:Count('pk',filter=Q(state=s)) for s in ('PENDING','FAILED','NO_RECIPIENTS','DELIVERED')},
        due=Count('pk',filter=due_filter),oldest_due=Min(Greatest('occurred_at','next_attempt_at'),filter=due_filter))
    counts={s:overview[s] for s in ('PENDING','FAILED','NO_RECIPIENTS','DELIVERED')}
    total=qs.count();number,start,pages=safe_page(page,total)
    rows=[]
    for e in qs.select_related('task').order_by('-occurred_at','-pk')[start:start+20]:
        rows.append(dict(id=e.pk,task_id=e.task_id,slot_id=e.task.slot_id,title=title(e.action),
            status=DELIVERY_LABELS.get(e.state,'需核对'),occurred_at=display_time(e.occurred_at),
            completed_at=display_time(e.completed_at) if e.completed_at else '',
            next_attempt_at=display_time(e.next_attempt_at) if e.next_attempt_at else '',
            attempts=e.attempts,retry_round=e.retry_round,delivered=e.delivered_count,
            suppressed=e.suppressed_count,error=ERROR_LABELS.get(e.error_code,'需受控核对'),can_retry=e.state=='FAILED'))
    if identity!=_identity(actor): raise PermissionDenied('工作上下文已变化。')
    oldest=overview['oldest_due']
    return dict(rows=rows,total=total,counts=counts,number=number,pages=pages,
        pending=counts.get('PENDING',0),failed=counts.get('FAILED',0),no_recipients=counts.get('NO_RECIPIENTS',0),
        due=overview['due'],scheduled_retry=counts['PENDING']-overview['due'],
        oldest_due_seconds=max(0,int((now-oldest).total_seconds())) if oldest else 0,
        oldest=display_time(oldest) if oldest else '',observed_at=display_time(now))


@transaction.atomic
def retry_delivery(*, actor, event_id, expected_round, confirmed):
    identity=_identity(actor)
    if identity[1]!='MANAGER': raise PermissionDenied('需要当前店主管身份。')
    lock_clinic_grant(actor,identity[2],roles=('MANAGER',))
    if confirmed is not True: raise RuleError('请明确确认只重试通知，不重做任务或预约。')
    positive_int(event_id)
    event=NotificationOutbox.objects.select_for_update(of=('self',)).filter(pk=event_id,clinic_id=identity[2],task__slot__clinic_id=identity[2]).first()
    if event is None: raise PermissionDenied('通知不属于当前诊所。')
    try: validate_retry(event.state,event.retry_round,expected_round)
    except ValueError as exc: raise RuleError(str(exc)) from exc
    event.state='PENDING';event.attempts=0;event.retry_round+=1
    event.completed_at=None;event.next_attempt_at=timezone.now();event.error_code=''
    event.save(update_fields=['state','attempts','retry_round','completed_at','next_attempt_at','error_code'])
    emit(actor,'NOTICE_RETRY_REQUESTED',event,summary={'retry_round':event.retry_round,'task_id':event.task_id})
    return event.pk
