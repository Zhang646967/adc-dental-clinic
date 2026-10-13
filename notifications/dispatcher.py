"""Bounded PostgreSQL inbox dispatcher; no broker or external transport.
Event lock + all inbox inserts + completion state commit atomically. A crash
before commit leaves the event eligible; a crash after commit may lose the
process receipt, so restart reads the stored state instead of replaying it.
There is no leased/stuck PROCESSING state. Handled failures roll back a
savepoint before retry scheduling.
"""
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.utils import timezone
from accounts.models import RoleAssignment
from notifications.models import NotificationOutbox, InboxMessage
from notifications.rules import EVENT_TYPES, bounded_batch, retry_time, validate_event


def _delivery_targets(event):
    targets = validate_event(action=event.action, event_state=event.event_state, task_id=event.task_id,
        clinic_id=event.clinic_id,task_revision=event.task_revision,recipients=event.recipients)
    source = event.source_event
    if (source.subject_type != 'coordinationtask' or source.subject_key != str(event.task_id)
        or source.event_type != EVENT_TYPES[event.action]
        or event.task.slot.clinic_id != event.clinic_id):
        raise ValueError('Invalid event association')
    summary=source.change_summary
    if (not isinstance(summary,dict) or summary.get('task_revision')!=event.task_revision
        or summary.get('state_after')!=event.event_state or summary.get('action')!=event.action
        or summary.get('slot_id')!=event.task.slot_id or source.occurred_at!=event.occurred_at):
        raise ValueError('Source event fingerprint mismatch')
    # Snapshot eligibility is necessary but not sufficient: recheck current grants.
    eligible = {g.pk: g for g in RoleAssignment.objects.filter(pk__in=[r['grant_id'] for r in targets],
        is_active=True, user__is_active=True, clinic_id=event.clinic_id, scope_kind='CLINIC',
        clinic__is_active=True)}
    return [r for r in targets if r['grant_id'] in eligible
            and eligible[r['grant_id']].user_id == r['user_id'] and eligible[r['grant_id']].role == r['role']], len(targets)


def _deliver(event, now):
    targets, count = _delivery_targets(event)
    for r in targets:
        msg, _ = InboxMessage.objects.get_or_create(event=event, grant_id=r['grant_id'], defaults={
            'recipient_id':r['user_id'],'role':r['role'],'clinic_id':event.clinic_id,'delivered_at':now})
        if (msg.recipient_id,msg.role,msg.clinic_id)!=(r['user_id'],r['role'],event.clinic_id):
            raise ValueError('Stored message ownership mismatch')
    return len(targets), count - len(targets)


def dispatch_one():
    if settings.ADC_READ_ONLY:
        raise PermissionDenied('只读实例不派发或写入通知。')
    if connection.vendor != 'postgresql':
        raise RuntimeError('PostgreSQL is required; there is no SQLite dispatcher fallback.')
    with transaction.atomic():
        now = timezone.now()
        event = (NotificationOutbox.objects.select_for_update(skip_locked=True)
            .filter(state='PENDING',next_attempt_at__lte=now).order_by('occurred_at','pk').first())
        if event is None:
            return None
        event.attempts += 1
        try:
            with transaction.atomic():
                sent, skipped = _deliver(event,now)
        except Exception as exc:
            # Only whitelisted error codes persist. Never save raw exceptions/SQL/payload.
            invalid = isinstance(exc, (ValueError, TypeError, KeyError))
            event.error_code = 'INVALID_EVENT' if invalid else 'DELIVERY_ERROR'
            event.next_attempt_at = None if invalid else retry_time(event.attempts,now)
            event.state = 'FAILED' if event.next_attempt_at is None else 'PENDING'
            event.completed_at = now if event.state == 'FAILED' else None
            event.delivered_count = 0; event.suppressed_count = 0
        else:
            event.delivered_count = sent; event.suppressed_count = skipped
            event.state = 'DELIVERED' if sent else 'NO_RECIPIENTS'
            event.error_code = '' if sent else 'NO_RECIPIENTS'
            event.next_attempt_at = None; event.completed_at = now
        event.save(update_fields=['attempts','next_attempt_at','state','completed_at','delivered_count','suppressed_count','error_code'])
        # Connection loss here rolls the entire attempt back, never reports delivery.
        return {'event_id':event.pk,'state':event.state,'attempts':event.attempts,
                'delivered':event.delivered_count,'suppressed':event.suppressed_count}


def dispatch_batch(batch_size=25, *, should_stop=None):
    results=[]
    for _ in range(bounded_batch(batch_size)):
        # Admit no next event after a stop request. Never interrupt dispatch_one:
        # its inbox rows and completion state must commit or roll back together.
        if should_stop is not None and should_stop():
            break
        result=dispatch_one()
        if result is None:
            break
        results.append(result)
    return results
