"""Admission pause/resume. Actor -> workspace -> grant -> source slot.
No visit/offer/request, clinical data, account or financial writes.
"""
from dataclasses import dataclass
from uuid import uuid4
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from accounts.policies import lock_clinic_grant
from adc_core.commands import business_errors
from adc_core.rules import RuleError
from care.audit import emit
from care.models import AuditEvent
from scheduling.availability_services import require_availability_actor, inspect_availability
from scheduling.intake_rules import (CONTRACT, ACTIONS, REASONS, IntakeError,
                                    validate_payload, validate_transition)
from scheduling.availability_rules import display_time

SALT = 'adc.slot.intake.b131'
MAX_AGE = 900
EVENTS = ('SLOT_INTAKE_PAUSED', 'SLOT_INTAKE_RESUMED')

@dataclass(frozen=True)
class IntakeResult:
    slot_id: int
    paused: bool
    event_id: int
    repeated: bool


def _binding(actor):
    ctx = require_availability_actor(actor)
    return dict(contract=CONTRACT, actor=actor.pk, context=str(ctx.pk),
                revision=ctx.revision, clinic=ctx.clinic_id)


def _load(token, *, proposal):
    try:
        if type(token) is not str or not 1 <= len(token) <= 5000: raise IntakeError('无效令牌')
        return validate_payload(signing.loads(token, salt=SALT, max_age=MAX_AGE), proposal=proposal)
    except (IntakeError, signing.BadSignature, TypeError, ValueError):
        raise RuleError('接收控制页面已过期、被更改或版本不符；请重新核对原出诊。') from None


def _bound(actor, data, slot_id):
    identity = _binding(actor)
    if any(data[k] != value for k,value in identity.items()) or data['slot'] != slot_id:
        raise PermissionDenied('当前身份、诊所或目标与确认内容不符。')
    return identity


def _transition(snapshot, action, reason):
    s = snapshot.slot
    try:
        value = validate_transition(active=s.is_active, paused=s.booking_paused,
            ends_at=s.ends_at, now=timezone.now(), clinic_active=s.clinic.is_active,
            dentist_active=s.dentist.is_active, action=action, reason=reason)
        if action == 'resume' and (snapshot.impact.anomalies or snapshot.impact.too_many):
            raise IntakeError('关联资料需要受控核对，暂不能恢复接收。')
    except IntakeError as exc:
        raise RuleError(str(exc)) from exc
    return value


@business_errors
@transaction.atomic
def inspect_intake(*, actor, slot_id):
    identity = _binding(actor)
    snapshot,_ = inspect_availability(actor=actor, slot_id=slot_id)
    if _binding(actor) != identity: raise PermissionDenied('当前工作范围已变化。')
    state = signing.dumps(identity | dict(kind='state',slot=slot_id,state=snapshot.state), salt=SALT)
    return snapshot, state


@business_errors
@transaction.atomic
@sensitive_variables()
def prepare_intake(*, actor, slot_id, state_token, action, reason):
    data = _load(state_token, proposal=False)
    identity = _bound(actor, data, slot_id)
    snapshot,_ = inspect_availability(actor=actor, slot_id=slot_id)
    if snapshot.state != data['state']:
        raise RuleError('出诊或关联业务已经变化，请重新核对后预览；尚未保存。')
    paused = _transition(snapshot, action, reason)
    if _binding(actor) != identity: raise PermissionDenied('工作上下文已变化。')
    proposal = signing.dumps(identity | dict(kind='proposal', slot=slot_id,
        state=snapshot.state, operation=str(uuid4()), action=action, reason=reason), salt=SALT)
    return dict(slot_id=slot_id, clinic=snapshot.slot.clinic.name, dentist=snapshot.slot.dentist.name,
        start=display_time(snapshot.slot.starts_at), end=display_time(snapshot.slot.ends_at),
        before='已暂停新增' if snapshot.slot.booking_paused else '接收新预约',
        after='已暂停新增' if paused else '接收新预约', action=action,
        action_label=ACTIONS[action], reason=REASONS[reason], impact=snapshot.impact,
        proposal_token=proposal, observed_at=display_time(snapshot.observed_at))


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm_intake(*, actor, slot_id, proposal_token, confirmed):
    if confirmed is not True: raise RuleError('请明确核对本次接收控制的影响后再确认。')
    ctx = require_availability_actor(actor)
    lock_clinic_grant(actor, ctx.clinic_id, roles=('FRONT_DESK',))
    data = _load(proposal_token, proposal=True)
    _bound(actor, data, slot_id)
    snapshot,_ = inspect_availability(actor=actor, slot_id=slot_id)
    slot = snapshot.slot  # Row lock held until the outer atomic transaction completes.
    event = AuditEvent.objects.filter(actor_id=actor.pk, subject_type='availabilityslot',
        subject_key=str(slot_id), event_type__in=EVENTS,
        change_summary__operation=data['operation']).first()
    if event:
        summary = event.change_summary
        if (summary.get('contract'), summary.get('action'), summary.get('state_before')) != (
                CONTRACT, data['action'], data['state']):
            raise RuleError('原操作关联需要核对，不能重放。')
        return IntakeResult(slot.pk, slot.booking_paused, event.pk, True)
    if snapshot.state != data['state']:
        raise RuleError('预览后出诊或关联承诺已变化；本次未执行，请重新核对。')
    paused = _transition(snapshot, data['action'], data['reason'])
    if slot.intake_revision >= 2**31-1:
        raise RuleError('接收控制修订号需受控维护，未执行变更。')
    slot.booking_paused = paused
    slot.intake_revision += 1
    slot.save(update_fields=['booking_paused','intake_revision'])
    event = emit(actor, 'SLOT_INTAKE_PAUSED' if paused else 'SLOT_INTAKE_RESUMED', slot,
        reason=REASONS[data['reason']], summary=dict(contract=CONTRACT, action=data['action'],
            operation=data['operation'], clinic_id=slot.clinic_id, state_before=data['state'],
            intake_revision=slot.intake_revision, booking_paused=paused,
            reason_code=data['reason']))
    return IntakeResult(slot.pk, paused, event.pk, False)
