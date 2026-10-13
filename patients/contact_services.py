"""Bounded, audited contact maintenance: preview is not a write.
Public commands bind target + current workspace + data state + one operation ID.
No Patient model schema change, clinical writes, account rebinding or invoice rewrite.
"""
from dataclasses import dataclass
from uuid import uuid4
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.views.decorators.debug import sensitive_variables
from accounts.policies import lock_clinic_grant, require_clinic
from adc_core.commands import business_errors
from adc_core.rules import RuleError
from care.audit import emit
from care.models import AuditEvent
from patients.models import Patient
from patients.selectors import visible_patients
from patients.contact_rules import (CONTACT_FIELDS, CONTRACT, REASONS, ContactInputError,
                                    differences, normalize_details, state_digest, validate_proposal, validate_reason)
from workspaces.context import require_active, valid_context
from workspaces.models import WorkspaceContext

STATE_SALT = 'adc.patient.contact.snapshot.09a3'
PROPOSAL_SALT = 'adc.patient.contact.proposal.09a3'
TOKEN_MAX_AGE = 15 * 60
EVENT_TYPE = 'PATIENT_CONTACT_CHANGED'

@dataclass(frozen=True)
class ContactEditor:
    patient: object
    values: dict
    state_token: str

@dataclass(frozen=True)
class ContactPreview:
    patient: object
    rows: tuple
    proposal_token: str
    reason_label: str

@dataclass(frozen=True)
class ContactResult:
    patient_id: int
    event_id: int
    repeated: bool


def require_contact_actor(actor):
    ctx = getattr(actor, '_adc_workspace', None)
    if ctx is None or ctx.role != 'FRONT_DESK' or ctx.clinic_id is None:
        raise PermissionDenied('请先进入前台工作台并选择授权诊所。')
    require_active(actor, ('FRONT_DESK',), ctx.clinic_id)
    require_clinic(actor, ctx.clinic_id)
    if not WorkspaceContext.objects.filter(pk=ctx.pk, user_id=actor.pk, role=ctx.role,
                                            clinic_id=ctx.clinic_id, revision=ctx.revision).exists():
        raise PermissionDenied('工作身份或诊所已变化，请刷新后重新核对。')
    if not valid_context(actor, ctx):
        raise PermissionDenied('当前授权已失效。')
    return ctx


def _subject(actor, patient_id, *, locked=False):
    ctx = require_contact_actor(actor)
    if not visible_patients(actor).filter(pk=patient_id, is_active=True).exists():
        raise PermissionDenied('该档案不可用或不在当前诊所的授权范围。')
    qs = Patient.objects.select_for_update() if locked else Patient.objects
    try:
        patient = qs.get(pk=patient_id, is_active=True)
    except Patient.DoesNotExist:
        raise PermissionDenied('该档案不可用或不在当前诊所的授权范围。') from None
    # A global exact-number lookup alone is NOT a contact-edit grant.
    if patient.created_in_clinic_id != ctx.clinic_id and not patient.visits.filter(clinic_id=ctx.clinic_id).exists():
        raise PermissionDenied('该档案不可用或不在当前诊所的授权范围。')
    return patient


def _events(patient):
    return AuditEvent.objects.filter(subject_type='patient', subject_key=str(patient.pk), event_type=EVENT_TYPE)


@sensitive_variables()
def _values(patient):
    return {field: getattr(patient, field) for field in CONTACT_FIELDS}


def _binding(actor, patient):
    ctx = require_contact_actor(actor)
    cursor = _events(patient).order_by('-id').values_list('id', flat=True).first() or 0
    return {'contract': CONTRACT, 'actor': actor.pk, 'patient': patient.pk,
            'clinic': ctx.clinic_id, 'context': str(ctx.pk), 'revision': ctx.revision,
            'state': state_digest(patient_id=patient.pk, values=_values(patient), audit_cursor=cursor)}


@sensitive_variables()
def _load(token, salt):
    if not isinstance(token, str) or not 1 <= len(token) <= 16000:
        raise RuleError('确认资料不可用。请先核对当前资料，再重新填写。')
    try:
        return signing.loads(token, salt=salt, max_age=TOKEN_MAX_AGE)
    except (signing.BadSignature, ValueError, TypeError):
        raise RuleError('确认页已过期或被更改。请先核对当前资料；此前已保存的操作不会因此撤销。') from None


@sensitive_variables()
def _clean(patient, details):
    try:
        result = normalize_details(details)
    except ContactInputError as exc:
        raise RuleError(str(exc)) from exc
    # Reuse actual model-field validators, notably EmailField, inside the command.
    for name in CONTACT_FIELDS:
        result[name] = Patient._meta.get_field(name).clean(result[name], patient)
    return result


@transaction.atomic
@sensitive_variables()
def contact_editor(*, actor, patient_id):
    # Consistent small snapshot. No business write; there is no new read-grant here.
    patient = _subject(actor, patient_id, locked=True)
    token = signing.dumps(_binding(actor, patient), salt=STATE_SALT)
    require_contact_actor(actor)
    return ContactEditor(patient, _values(patient), token)


@business_errors
@transaction.atomic
@sensitive_variables()
def prepare_contact_change(*, actor, patient_id, state_token, details, reason_code):
    ctx = require_contact_actor(actor)
    lock_clinic_grant(actor, ctx.clinic_id)
    patient = _subject(actor, patient_id, locked=True)
    before = _binding(actor, patient)
    if _load(state_token, STATE_SALT) != before:
        raise RuleError('联络资料已被更新，请重新读取后核对；不能覆盖他人的修改。')
    values = _clean(patient, details)
    try:
        validate_reason(reason_code)
    except ContactInputError as exc:
        raise RuleError(str(exc)) from exc
    rows = differences(_values(patient), values)
    if not rows:
        raise RuleError('没有实际变更，无需保存。')
    payload = {**before, 'operation': str(uuid4()), 'values': values, 'reason_code': reason_code}
    token = signing.dumps(payload, salt=PROPOSAL_SALT)
    # Return to the same authorized workspace. Preview does not update Patient or emit an event.
    require_contact_actor(actor)
    return ContactPreview(patient, rows, token, REASONS[reason_code])


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm_contact_change(*, actor, patient_id, proposal_token, confirmed):
    ctx = require_contact_actor(actor)
    lock_clinic_grant(actor, ctx.clinic_id)
    if confirmed is not True:
        raise RuleError('请明确确认本次联络资料变更。')
    patient = _subject(actor, patient_id, locked=True)
    payload = _load(proposal_token, PROPOSAL_SALT)
    try:
        validate_proposal(payload)
    except ContactInputError as exc:
        raise RuleError(str(exc)) from exc
    current = _binding(actor, patient)
    if any(payload[k] != current[k] for k in ('contract', 'actor', 'patient', 'clinic', 'context', 'revision')):
        raise PermissionDenied('确认对象或工作上下文不符，请重新核对。')
    previous = _events(patient).filter(actor_id=actor.pk, change_summary__operation=payload['operation']).first()
    if previous is not None:
        # Authorize first. A successful operation is not applied again even if later edits exist.
        return ContactResult(patient.pk, previous.pk, True)
    if payload['state'] != current['state']:
        raise RuleError('预览后联络资料又发生了变化，本次未保存；请重新读取并核对差异。')
    values = _clean(patient, payload['values'])
    rows = differences(_values(patient), values)
    if not rows:
        raise RuleError('当前资料与提交值相同，无需重复保存。')
    for field in CONTACT_FIELDS:
        setattr(patient, field, values[field])
    patient.save(update_fields=list(CONTACT_FIELDS))
    event = emit(actor, EVENT_TYPE, patient, reason=REASONS[payload['reason_code']], summary={
        'operation': payload['operation'], 'fields': [row.field for row in rows],
        'clinic_id': ctx.clinic_id, 'reason_code': payload['reason_code'], 'contract': CONTRACT,
    })
    return ContactResult(patient.pk, event.pk, False)
