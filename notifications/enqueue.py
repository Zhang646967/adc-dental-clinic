"""Single task-service hook. No dispatch/network inside the business transaction."""
from django.db import connection
from accounts.models import RoleAssignment
from adc_core.rules import RuleError
from notifications.models import NotificationOutbox
from notifications.rules import ACTIONS, EVENT_TYPES, MAX_RECIPIENTS, validate_event


def enqueue_task_notice(*, task, event, action):
    if not connection.in_atomic_block:
        raise RuntimeError('Notification intent must share the task transaction.')
    if (action not in ACTIONS or event.event_type != EVENT_TYPES[action]
        or event.subject_type != 'coordinationtask' or event.subject_key != str(task.pk)):
        raise ValueError('Task notification source mismatch.')
    clinic_id = task.slot.clinic_id
    rows = list(RoleAssignment.objects.filter(is_active=True, user__is_active=True,
        role__in=ACTIONS[action][1], scope_kind='CLINIC', clinic_id=clinic_id,
        clinic__is_active=True).order_by('pk').values('id','user_id','role')[:MAX_RECIPIENTS + 1])
    targets = [{'grant_id': r['id'], 'user_id': r['user_id'], 'role': r['role']} for r in rows]
    try:
        targets = validate_event(action=action,event_state=task.state,task_id=task.pk,
            clinic_id=clinic_id,task_revision=task.revision,recipients=targets)
    except ValueError as exc:
        # Never truncate silently. This aborts the associated task transition too.
        raise RuleError('通知收件范围需要核对，本次任务变更未保存。') from exc
    return NotificationOutbox.objects.create(source_event=event,task=task,clinic_id=clinic_id,
        task_revision=task.revision,action=action,event_state=task.state,
        occurred_at=event.occurred_at,recipients=targets)
