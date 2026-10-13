"""Controlled availability maintenance; cannot mutate Visits/WaitOffers.
Lock order on writes: actor -> workspace -> clinic grant -> source availability.
Booking/publish/accept commands use the SAME source-slot row lock. Database
exclusion resolves concurrent overlapping new slots. No new lock namespace.
"""
from dataclasses import dataclass
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
from coordination.models import WaitOffer
from scheduling.models import AvailabilitySlot, Visit
from scheduling.coordination import lock_slots
from scheduling.availability_rules import (CONTRACT, REASONS, MAX_RELATIONS, AvailabilityError,
    assess_relations, block_reasons, digest, display_time, parse_time, positive_id,
    validate_action, validate_replacement, validate_payload)
from workspaces.context import require_active, valid_context
from workspaces.models import WorkspaceContext

SALT = 'adc.availability.09a6'
MAX_AGE = 900
EVENTS = ('SLOT_REPLACED', 'SLOT_DEACTIVATED')
STATE_EVENTS = ('SLOT_CREATED', *EVENTS, 'SLOT_INTAKE_PAUSED', 'SLOT_INTAKE_RESUMED')

@dataclass(frozen=True)
class SlotSnapshot:
    slot: object
    facts: dict
    impact: object
    state: str
    observed_at: object
    blocked: tuple

@dataclass(frozen=True)
class SlotPreview:
    slot_id: int
    clinic_name: str
    dentist_name: str
    before: str
    after: str
    action: str
    reason_label: str
    impact: object
    observed_at: str
    proposal_token: str
    booking_paused: bool = False

@dataclass(frozen=True)
class SlotResult:
    source_id: int
    replacement_id: int | None
    event_id: int
    repeated: bool


def require_availability_actor(actor):
    ctx = getattr(actor, '_adc_workspace', None)
    if ctx is None or ctx.role != 'MANAGER' or ctx.clinic_id is None:
        raise PermissionDenied('请以诊所主管身份选择当前诊所后再操作。')
    require_active(actor, ('MANAGER',), ctx.clinic_id)
    if not valid_context(actor, ctx) or not WorkspaceContext.objects.filter(pk=ctx.pk, user_id=actor.pk,
            role='MANAGER', clinic_id=ctx.clinic_id, revision=ctx.revision).exists():
        raise PermissionDenied('工作身份或诊所已变化，请返回当前工作台。')
    if not bindings(actor).filter(role='MANAGER', scope_kind='CLINIC', clinic_id=ctx.clinic_id).exists():
        raise PermissionDenied('当前诊所主管授权已失效。')
    return ctx


def _binding(actor):
    ctx = require_availability_actor(actor)
    return {'contract': CONTRACT, 'actor': actor.pk, 'context': str(ctx.pk),
            'revision': ctx.revision, 'clinic': ctx.clinic_id}


def _owned_slot(actor, slot_id):
    try:
        positive_id(slot_id)
    except AvailabilityError:
        raise PermissionDenied('出诊安排不存在或不属于当前诊所。') from None
    ctx = require_availability_actor(actor)
    # Scope check before taking the row lock; unknown and other-clinic IDs look identical.
    if not AvailabilitySlot.objects.filter(pk=slot_id, clinic_id=ctx.clinic_id).exists():
        raise PermissionDenied('出诊安排不存在或不属于当前诊所。')
    slot = lock_slots([slot_id])[slot_id]
    if slot.clinic_id != ctx.clinic_id:
        raise PermissionDenied('出诊安排范围已变化。')
    return slot


def _serial_rows(rows):
    return [{key: value.isoformat() if hasattr(value, 'isoformat') else value
             for key, value in row.items()} for row in rows]


def _snapshot(slot):
    # All application mutations of related Visit/Offer state first lock this row.
    now = timezone.now()
    vq = Visit.objects.filter(availability_slot_id=slot.pk).order_by('pk')
    oq = WaitOffer.objects.filter(slot_id=slot.pk).order_by('pk')
    vc, oc = vq.count(), oq.count()
    visits = _serial_rows(vq.values('id', 'clinic_id', 'dentist_id', 'scheduled_start',
        'scheduled_end', 'status', 'lock_version')[:MAX_RELATIONS + 1])
    offers = _serial_rows(oq.values('id', 'request_id', 'request__clinic_id', 'request__state',
        'starts_at', 'ends_at', 'expires_at', 'state', 'visit_id')[:MAX_RELATIONS + 1])
    facts = {'slot_id': slot.pk, 'clinic_id': slot.clinic_id, 'dentist_id': slot.dentist_id,
        'starts_at': slot.starts_at.isoformat(), 'ends_at': slot.ends_at.isoformat(), 'is_active': slot.is_active,
        'clinic_active': slot.clinic.is_active, 'dentist_active': slot.dentist.is_active,
        'booking_paused': slot.booking_paused, 'intake_revision': slot.intake_revision}
    cursor = AuditEvent.objects.filter(subject_type='availabilityslot', subject_key=str(slot.pk),
        event_type__in=STATE_EVENTS).order_by('-pk').values_list('pk', flat=True).first() or 0
    # The current clock is NOT a snapshot field. Expiry is independently checked at confirmation.
    state = digest({'slot': facts, 'visits': visits, 'offers': offers, 'vc': vc, 'oc': oc, 'cursor': cursor})
    impact = assess_relations(slot=facts, visits=visits, offers=offers, now=now, visit_count=vc, offer_count=oc)
    return SlotSnapshot(slot, facts, impact, state, now, block_reasons(facts, impact, now))


@sensitive_variables()
def _load(token, *, proposal):
    if type(token) is not str or not 1 <= len(token) <= 5000:
        raise RuleError('确认资料无效，请重新核对出诊安排。')
    try:
        return validate_payload(signing.loads(token, salt=SALT, max_age=MAX_AGE), proposal=proposal)
    except (signing.BadSignature, TypeError, ValueError, AvailabilityError):
        raise RuleError('页面已过期、被更改或版本不符，请从当前出诊详情重新开始。') from None


def _authorize_payload(actor, payload, slot_id):
    binding = _binding(actor)
    if any(payload[key] != value for key, value in binding.items()) or payload['slot'] != slot_id:
        raise PermissionDenied('确认主体、诊所、对象或工作上下文不符；未执行操作。')
    return binding


@business_errors
@transaction.atomic
def inspect_availability(*, actor, slot_id):
    binding = _binding(actor)
    slot = _owned_slot(actor, slot_id)
    snapshot = _snapshot(slot)
    if _binding(actor) != binding:
        raise PermissionDenied('工作范围已变化，不能返回旧数据。')
    token = signing.dumps({**binding, 'kind': 'state', 'slot': slot.pk, 'state': snapshot.state}, salt=SALT)
    return snapshot, token


@business_errors
@transaction.atomic
@sensitive_variables()
def prepare_availability_change(*, actor, slot_id, state_token, action, reason_code, start=None, end=None):
    payload = _load(state_token, proposal=False)
    binding = _authorize_payload(actor, payload, slot_id)
    slot = _owned_slot(actor, slot_id)
    snapshot = _snapshot(slot)
    if payload['state'] != snapshot.state:
        raise RuleError('出诊或关联业务在填写期间已变化，请重新读取并核对；尚未保存。')
    try:
        validate_action(action, reason_code)
        validate_replacement(snapshot.facts, snapshot.impact, timezone.now(), action=action, start=start, end=end)
    except AvailabilityError as exc:
        raise RuleError(str(exc)) from exc
    if action == 'replace' and AvailabilitySlot.objects.filter(dentist_id=slot.dentist_id,
            is_active=True, starts_at__lt=end, ends_at__gt=start).exclude(pk=slot.pk).exists():
        raise RuleError('新时间与该牙医的另一条有效出诊重叠（可能在其他店），请重新选择。')
    if _binding(actor) != binding:
        raise PermissionDenied('当前身份或诊所已经变化。')
    data = {**binding, 'kind': 'proposal', 'slot': slot.pk, 'state': snapshot.state,
        'operation': str(uuid4()), 'action': action, 'reason': reason_code,
        'start': start.isoformat() if action == 'replace' else None,
        'end': end.isoformat() if action == 'replace' else None}
    return SlotPreview(slot.pk, slot.clinic.name, slot.dentist.name,
        f'{display_time(slot.starts_at)} — {display_time(slot.ends_at)}',
        f'{display_time(start)} — {display_time(end)}（新记录）' if action == 'replace' else '停止提供新预约机会；原记录保留',
        action, REASONS[reason_code], snapshot.impact, display_time(snapshot.observed_at),
        signing.dumps(data, salt=SALT), slot.booking_paused)


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm_availability_change(*, actor, slot_id, proposal_token, confirmed):
    if confirmed is not True:
        raise RuleError('请明确核对时间与影响后再确认。')
    ctx = require_availability_actor(actor)
    # Writes follow the same actor/context/grant/slot order as booking commands.
    lock_clinic_grant(actor, ctx.clinic_id, roles=('MANAGER',))
    payload = _load(proposal_token, proposal=True)
    _authorize_payload(actor, payload, slot_id)
    slot = _owned_slot(actor, slot_id)
    event = AuditEvent.objects.filter(actor_id=actor.pk, subject_type='availabilityslot', subject_key=str(slot.pk),
        event_type__in=EVENTS, change_summary__operation=payload['operation']).first()
    if event:
        summary = event.change_summary
        if summary.get('contract') != CONTRACT or summary.get('action') != payload['action'] or summary.get('state_before') != payload['state']:
            raise RuleError('原操作关联需核对，不能重放。')
        return SlotResult(slot.pk, summary.get('replacement_id'), event.pk, True)
    snapshot = _snapshot(slot)
    if snapshot.state != payload['state']:
        raise RuleError('预览后出诊或关联业务已经变化；本次未执行，请重新核对。')
    start = parse_time(payload['start']) if payload['action'] == 'replace' else None
    end = parse_time(payload['end']) if payload['action'] == 'replace' else None
    try:
        validate_replacement(snapshot.facts, snapshot.impact, timezone.now(), action=payload['action'], start=start, end=end)
    except AvailabilityError as exc:
        raise RuleError(str(exc)) from exc
    # Old interval/dentist/clinic never change. Existing historical FKs remain accurate.
    slot.is_active = False
    slot.save(update_fields=['is_active'])
    replacement = None
    if payload['action'] == 'replace':
        # Existing PG exclusion is the final guard for races with ANY new-slot creator.
        replacement = AvailabilitySlot.objects.create(dentist_id=slot.dentist_id, clinic_id=slot.clinic_id,
            starts_at=start, ends_at=end, is_active=True, booking_paused=slot.booking_paused)
    summary = {'contract': CONTRACT, 'operation': payload['operation'], 'action': payload['action'],
        'reason_code': payload['reason'], 'clinic_id': slot.clinic_id, 'dentist_id': slot.dentist_id,
        'state_before': payload['state'], 'replacement_id': replacement.pk if replacement else None,
        'old_start': slot.starts_at.isoformat(), 'old_end': slot.ends_at.isoformat(),
        'new_start': payload['start'], 'new_end': payload['end'],
        'replacement_booking_paused': slot.booking_paused if replacement else None}
    event = emit(actor, 'SLOT_REPLACED' if replacement else 'SLOT_DEACTIVATED', slot,
        reason=REASONS[payload['reason']], summary=summary)
    if replacement:
        emit(actor, 'SLOT_CREATED', replacement, summary={'clinic_id': slot.clinic_id,
            'dentist_id': slot.dentist_id, 'predecessor_slot_id': slot.pk, 'maintenance_event_id': event.pk})
    return SlotResult(slot.pk, replacement.pk if replacement else None, event.pk, False)
