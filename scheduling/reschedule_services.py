"""Explicit reschedule preview/confirmation; reuse existing booking locks/command.

No new schema. A successful replay is established from the unique successor and
its original actor's immutable reschedule audit, never by reviving old state.
"""
from dataclasses import dataclass
from datetime import datetime

from django.core import signing
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from accounts.policies import lock_clinic_grant
from adc_core.commands import assert_revision, business_errors
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from care.models import AuditEvent
from scheduling.coordination import lock_slots
from scheduling.front_coordination_links import visit_return_slot
from scheduling.front_coordination_selectors import require_front_coordination
from scheduling.models import AvailabilitySlot, Visit
from scheduling.reschedule_selectors import owned_source, check_source, check_target
from scheduling.services import reschedule

SALT = 'adc.front.reschedule.preview.v1'
MAX_AGE = 900
CONTRACT = 'FRONT-RESCHEDULE-1'


@dataclass(frozen=True)
class RescheduleResult:
    visit: Visit
    repeated: bool
    origin: int | None


def _binding(actor):
    ctx = require_front_coordination(actor)
    return {'uid': actor.pk, 'workspace': str(ctx.pk), 'workspace_revision': ctx.revision, 'clinic': ctx.clinic_id}


def _time(value):
    if type(value) is not str or not 1 <= len(value) <= 40:
        raise ValueError
    value = datetime.fromisoformat(value)
    if value.utcoffset() is None:
        raise ValueError
    return value


@sensitive_variables('token', 'data')
def _load(token):
    try:
        if not isinstance(token, str) or len(token) > 8192:
            raise ValueError
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
        required = {'contract', 'uid', 'workspace', 'workspace_revision', 'clinic', 'visit', 'visit_version',
                    'slot', 'slot_clinic', 'slot_dentist', 'intake_revision', 'start', 'end', 'reason', 'origin'}
        if type(data) is not dict or set(data) != required or data['contract'] != CONTRACT:
            raise ValueError
        for key in ('uid', 'clinic', 'visit', 'slot', 'slot_clinic', 'slot_dentist'):
            if type(data[key]) is not int or not 0 < data[key] < 2**63:
                raise ValueError
        for key in ('workspace_revision', 'visit_version', 'intake_revision'):
            if type(data[key]) is not int or data[key] < 0:
                raise ValueError
        if type(data['workspace']) is not str or not data['workspace']:
            raise ValueError
        if type(data['reason']) is not str or not 1 <= len(data['reason'].strip()) <= 500:
            raise ValueError
        if data['origin'] is not None and (type(data['origin']) is not int or data['origin'] <= 0):
            raise ValueError
        if _time(data['start']) >= _time(data['end']):
            raise ValueError
        return data
    except (signing.BadSignature, ValueError, TypeError, KeyError, OverflowError) as exc:
        raise RuleError('确认页已过期或内容无效，请重新预览；原预约未因本次请求改变。') from exc


@sensitive_variables('reason')
def prepare_reschedule(*, actor, visit_id, expected_version, new_slot_id, start, end, reason, origin=None):
    with reporting_snapshot():
        binding = _binding(actor)
        old = owned_source(actor, visit_id)
        check_source(old)
        # This is an observation only. The command's revision guard is used
        # again after locking the source at confirmation.
        if type(expected_version) is not int or old.lock_version != expected_version:
            raise RuleError('记录已发生变化；请刷新后重新确认，不能覆盖他人操作。')
        if type(reason) is not str or not 1 <= len(reason.strip()) <= 500:
            raise RuleError('请记录1至500字的改期原因。')
        slot = AvailabilitySlot.objects.select_related('clinic', 'dentist').get(pk=new_slot_id, clinic_id=binding['clinic'])
        now = timezone.now()
        check_target(old, slot, start, end, now)
        origin = visit_return_slot(actor, str(origin), old) if origin is not None else None
        data = dict(binding, contract=CONTRACT, visit=old.pk, visit_version=old.lock_version,
                    slot=slot.pk, slot_clinic=slot.clinic_id, slot_dentist=slot.dentist_id,
                    intake_revision=slot.intake_revision, start=start.isoformat(), end=end.isoformat(),
                    reason=reason.strip(), origin=origin)
        return {'original': old, 'destination': slot, 'start': start, 'end': end, 'reason': reason.strip(),
                'observed_at': now, 'proposal_token': signing.dumps(data, salt=SALT, compress=True),
                'duration_changed': end-start != old.scheduled_end-old.scheduled_start}


@business_errors
@transaction.atomic
@sensitive_variables('proposal_token', 'data')
def confirm_reschedule(*, actor, visit_id, proposal_token, confirmed):
    if confirmed is not True:
        raise RuleError('请核对患者意愿、原安排与新安排后明确确认。')
    data = _load(proposal_token)
    binding = _binding(actor)
    if any(data[key] != value for key, value in binding.items()) or data['visit'] != visit_id:
        raise RuleError('工作身份、诊所或原预约已经变化，请重新预览。')
    lock_clinic_grant(actor, binding['clinic'])
    preview = Visit.objects.only('availability_slot_id').get(pk=visit_id, clinic_id=binding['clinic'])
    slots = lock_slots([preview.availability_slot_id, data['slot']])
    old = Visit.objects.select_for_update(of=('self',)).select_related('patient', 'clinic', 'dentist').get(
        pk=visit_id, clinic_id=binding['clinic'])
    start, end = _time(data['start']), _time(data['end'])
    if old.status == 'RESCHEDULED':
        following = Visit.objects.filter(replaces_visit_id=old.pk).first()
        if (following is not None and old.lock_version == data['visit_version'] + 1 and
                following.patient_id == old.patient_id and following.clinic_id == binding['clinic'] and
                following.availability_slot_id == data['slot'] and following.dentist_id == data['slot_dentist'] and
                following.scheduled_start == start and following.scheduled_end == end and
                AuditEvent.objects.filter(visit_id=old.pk, actor_id=actor.pk, event_type='VISIT_RESCHEDULED',
                    reason=data['reason'], change_summary={'replacement_id': following.pk}).exists()):
            return RescheduleResult(following, True, data['origin'])
        raise RuleError('原预约已有其他改期结果，请先打开关联记录核对。')
    assert_revision(old, data['visit_version'])
    check_source(old)
    target = slots[data['slot']]
    if (target.clinic_id != binding['clinic'] or target.clinic_id != data['slot_clinic'] or
            target.dentist_id != data['slot_dentist'] or target.intake_revision != data['intake_revision']):
        raise RuleError('目标出诊或接收状态已变化，请重新预览；原预约未改变。')
    # The existing command checks active resources, live holds, time conflicts
    # and row versions again, in the same transaction and shared lock protocol.
    new = reschedule(actor=actor, visit_id=old.pk, expected_version=data['visit_version'],
        new_slot_id=target.pk, start=start, end=end, reason=data['reason'])
    return RescheduleResult(new, False, data['origin'])
