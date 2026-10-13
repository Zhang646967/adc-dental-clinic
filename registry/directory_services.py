"""Audited directory registration and qualification associations. No bulk CRUD.
Lock order: governance advisory -> actor -> context -> technical grant -> directory
advisory -> dentist -> qualification -> association. No Visit/Invoice mutations.
"""
from dataclasses import dataclass
from functools import wraps
from uuid import uuid4
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import connection, IntegrityError, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from accounts.governance import lock_operator
from accounts.models import RoleAssignment
from accounts.policies import bindings
from adc_core.commands import business_errors
from adc_core.rules import RuleError
from care.audit import emit
from care.models import AuditEvent
from registry.models import Clinic, Dentist, Qualification, DentistQualification
from registry.directory_rules import (CONTRACT, FIELDS, KINDS, REASONS, DirectoryInputError, DisplayRow,
    normalize_registration, display_rows, validate_reason, validate_payload, positive_id,
    association_transition, state_digest)
from workspaces.context import require_active, valid_context
from workspaces.models import WorkspaceContext

MODEL_MAP = {'clinic': Clinic, 'dentist': Dentist, 'qualification': Qualification}
CODE_FIELDS = {'clinic': 'clinic_code', 'dentist': 'employee_no', 'qualification': 'code'}
SALT = 'adc.directory.confirm.09a5'
MAX_AGE = 900
REGISTER_EVENTS = {'clinic': 'REGISTRY_CLINIC_REGISTERED', 'dentist': 'REGISTRY_DENTIST_REGISTERED',
                   'qualification': 'REGISTRY_QUALIFICATION_REGISTERED'}
ASSOCIATION_EVENTS = ('DENTIST_QUALIFICATION_ATTACHED', 'DENTIST_QUALIFICATION_WITHDRAWN')
ALL_EVENTS = tuple(REGISTER_EVENTS.values()) + ASSOCIATION_EVENTS

@dataclass(frozen=True)
class DirectoryPreview:
    title: str
    rows: tuple
    proposal_token: str
    reason_label: str
    kind: str

@dataclass(frozen=True)
class DirectoryResult:
    kind: str
    object_id: int
    event_id: int
    repeated: bool


def require_directory_actor(actor):
    ctx = getattr(actor, '_adc_workspace', None)
    if ctx is None or ctx.role != 'SYSADMIN' or ctx.clinic_id is not None:
        raise PermissionDenied('请先进入有效的技术管理工作台。其他身份不具有目录维护权。')
    require_active(actor, ('SYSADMIN',))
    if not valid_context(actor, ctx) or not WorkspaceContext.objects.filter(
            pk=ctx.pk, user_id=actor.pk, role='SYSADMIN', clinic_id=None, revision=ctx.revision).exists():
        raise PermissionDenied('工作身份已变化，请返回当前工作台重新核对。')
    if not bindings(actor).filter(role='SYSADMIN', scope_kind='TECHNICAL').exists():
        raise PermissionDenied('技术管理授权已失效。')
    return ctx


def directory_conflicts(fn):
    """Translate only known duplicate-key failures, outside the atomic block."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except IntegrityError as exc:
            name = getattr(getattr(exc.__cause__, 'diag', None), 'constraint_name', None)
            if name in {'adc_clinic_clinic_code_key', 'adc_dentist_employee_no_key',
                        'adc_qualification_code_key', 'dentist_qualification_unique'}:
                raise RuleError('编号或资格关联已存在，本次未覆盖任何资料；请重新核对。') from exc
            raise
    return wrapped


def _binding(actor):
    ctx = require_directory_actor(actor)
    return {'contract': CONTRACT, 'actor': actor.pk, 'context': str(ctx.pk), 'revision': ctx.revision}


@sensitive_variables()
def _load(token):
    if type(token) is not str or not 1 <= len(token) <= 16000:
        raise RuleError('确认资料无效，请返回目录核对。')
    try:
        payload = signing.loads(token, salt=SALT, max_age=MAX_AGE)
        return validate_payload(payload)
    except (signing.BadSignature, TypeError, ValueError, DirectoryInputError):
        raise RuleError('确认资料已过期、被更改或版本不符。请核对当前目录，勿反复提交。') from None


@sensitive_variables()
def _clean(kind, details):
    try:
        values = normalize_registration(kind, details, today=timezone.localdate())
    except DirectoryInputError as exc:
        raise RuleError(str(exc)) from exc
    obj = MODEL_MAP[kind](**values, is_active=True)
    obj.full_clean()  # Actual EmailField/date/decimal/constraint validators, at preview AND confirmation.
    return obj, values


def _duplicate(kind, values):
    field = CODE_FIELDS[kind]
    if MODEL_MAP[kind].objects.filter(**{field + '__iexact': values[field]}).exists():
        raise RuleError('该编码或员工编号已存在；请核对原目录，不会覆盖或复活旧资料。')


@business_errors
@sensitive_variables()
def prepare_registration(*, actor, kind, details, reason_code):
    binding = _binding(actor)
    if type(kind) is not str or kind not in MODEL_MAP:
        raise RuleError('未知的基础目录类型。')
    try:
        validate_reason(reason_code)
    except DirectoryInputError as exc:
        raise RuleError(str(exc)) from exc
    # Normalize before checking duplicates; arbitrary form fields never become model kwargs.
    try:
        normalized = normalize_registration(kind, details, today=timezone.localdate())
    except DirectoryInputError as exc:
        raise RuleError(str(exc)) from exc
    _duplicate(kind, normalized)
    _, values = _clean(kind, normalized)
    if _binding(actor) != binding:
        raise PermissionDenied('工作身份已变化，不能继续使用旧预览。')
    token = signing.dumps({**binding, 'kind': kind, 'action': 'register', 'values': values,
                           'reason_code': reason_code, 'operation': str(uuid4())}, salt=SALT)
    return DirectoryPreview('核对并登记' + KINDS[kind], display_rows(kind, values), token, REASONS[reason_code], kind)


def _association(actor, dentist_id, qualification_id, *, locked):
    require_directory_actor(actor)
    try:
        positive_id(dentist_id); positive_id(qualification_id)
    except DirectoryInputError as exc:
        raise RuleError(str(exc)) from exc
    dentists = Dentist.objects.select_for_update() if locked else Dentist.objects
    quals = Qualification.objects.select_for_update() if locked else Qualification.objects
    dentist = dentists.get(pk=dentist_id)
    qual = quals.get(pk=qualification_id)
    links = DentistQualification.objects.select_for_update() if locked else DentistQualification.objects
    link = links.filter(dentist=dentist, qualification=qual).first()
    cursor = 0
    if link:
        cursor = AuditEvent.objects.filter(subject_type='dentistqualification', subject_key=str(link.pk),
            event_type__in=ASSOCIATION_EVENTS).order_by('-id').values_list('id', flat=True).first() or 0
    digest = state_digest({'dentist': [dentist.pk, dentist.employee_no, dentist.name, dentist.is_active],
                           'qualification': [qual.pk, qual.code, qual.name, qual.is_active],
                           'link': [link.pk, link.is_active, link.notes] if link else None,
                           'audit_cursor': cursor})
    return dentist, qual, link, digest


@business_errors
@transaction.atomic
@sensitive_variables()
def prepare_association(*, actor, dentist_id, qualification_id, action, reason_code):
    binding = _binding(actor)
    dentist, qual, link, digest = _association(actor, dentist_id, qualification_id, locked=True)
    try:
        transition, _ = association_transition(action, dentist_active=dentist.is_active,
            qualification_active=qual.is_active, link_active=link.is_active if link else None)
        validate_reason(reason_code, action=action)
        if (transition == 'RESTORE') != (reason_code == 'RESTORE_LINK') and action == 'attach':
            raise DirectoryInputError('恢复旧关联请选择“重新核对后恢复资格关联”；新关联请选择资料登记依据。')
    except DirectoryInputError as exc:
        raise RuleError(str(exc)) from exc
    rows = (DisplayRow('牙医', f'{dentist.employee_no} · {dentist.name}'),
            DisplayRow('资格类别', f'{qual.code} · {qual.name}'),
            DisplayRow('当前关联', '有效登记' if link and link.is_active else '已撤回' if link else '未关联'),
            DisplayRow('拟进行的操作', {'ATTACH': '新增资格关联', 'RESTORE': '恢复原关联（保留原编号）', 'WITHDRAW': '撤回误关联（保留历史）'}[transition]))
    if _binding(actor) != binding:
        raise PermissionDenied('工作身份已变化，请重新核对。')
    payload = {**binding, 'operation': str(uuid4()), 'kind': 'association', 'action': action,
               'values': {'dentist_id': dentist.pk, 'qualification_id': qual.pk}, 'state': digest,
               'reason_code': reason_code}
    return DirectoryPreview({'ATTACH':'核对并登记牙医资格关联','RESTORE':'核对并恢复原资格关联','WITHDRAW':'核对并撤回误关联'}[transition], rows, signing.dumps(payload, salt=SALT), REASONS[reason_code], 'association')


def _lock_write(actor, operator_password):
    require_directory_actor(actor)
    lock_operator(actor, operator_password)  # Includes ADC_READ_ONLY, current user/context and password.
    grant = RoleAssignment.objects.select_for_update().filter(user_id=actor.pk, role='SYSADMIN',
        scope_kind='TECHNICAL', is_active=True).first()
    if grant is None:
        raise PermissionDenied('技术授权已撤回。')
    require_directory_actor(actor)
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s,%s)', [8127, 1])


@business_errors
@directory_conflicts
@transaction.atomic
@sensitive_variables()
def confirm_directory_change(*, actor, proposal_token, operator_password, confirmed):
    if confirmed is not True:
        raise RuleError('请明确确认所核对的资料和影响；尚未保存。')
    _lock_write(actor, operator_password)
    payload = _load(proposal_token)
    current = _binding(actor)
    if any(payload[k] != current[k] for k in current):
        raise PermissionDenied('确认主体或工作上下文不符，请重新核对。')
    event = AuditEvent.objects.filter(actor_id=actor.pk, event_type__in=ALL_EVENTS,
                                      change_summary__operation=payload['operation']).first()
    if event:
        # Authorize first. Never apply a successful operation twice or undo later edits.
        if event.change_summary.get('contract') != CONTRACT or event.change_summary.get('kind') != payload['kind']:
            raise RuleError('原操作记录不一致，请停止并核对。')
        object_id = event.change_summary['dentist_id'] if payload['kind'] == 'association' else int(event.subject_key)
        return DirectoryResult(payload['kind'], object_id, event.pk, True)
    kind = payload['kind']
    if kind in MODEL_MAP:
        try:
            normalized = normalize_registration(kind, payload['values'], today=timezone.localdate())
        except DirectoryInputError as exc:
            raise RuleError(str(exc)) from exc
        _duplicate(kind, normalized)
        obj, _ = _clean(kind, normalized)
        obj.save(force_insert=True)
        event = emit(actor, REGISTER_EVENTS[kind], obj, reason=REASONS[payload['reason_code']],
            summary={'contract': CONTRACT, 'operation': payload['operation'], 'kind': kind,
                     'fields': list(FIELDS[kind]), 'reason_code': payload['reason_code']})
        return DirectoryResult(kind, obj.pk, event.pk, False)
    dentist, qual, link, digest = _association(actor, **payload['values'], locked=True)
    if payload['state'] != digest:
        raise RuleError('牙医、资格或关联在预览后已变化，本次未保存；请重新读取。')
    try:
        transition, active = association_transition(payload['action'], dentist_active=dentist.is_active,
            qualification_active=qual.is_active, link_active=link.is_active if link else None)
        if payload['action'] == 'attach' and ((transition == 'RESTORE') != (payload['reason_code'] == 'RESTORE_LINK')):
            raise DirectoryInputError('关联依据与当前状态不一致。')
    except DirectoryInputError as exc:
        raise RuleError(str(exc)) from exc
    if link is None:
        link = DentistQualification(dentist=dentist, qualification=qual, notes='', is_active=True)
        link.full_clean(); link.save(force_insert=True)
    else:
        link.is_active = active
        link.save(update_fields=['is_active'])  # Never delete/recreate or rewrite old notes.
    event = emit(actor, ASSOCIATION_EVENTS[0 if active else 1], link, reason=REASONS[payload['reason_code']],
        summary={'contract': CONTRACT, 'operation': payload['operation'], 'kind': kind,
                 'dentist_id': dentist.pk, 'qualification_id': qual.pk, 'transition': transition,
                 'reason_code': payload['reason_code'], 'clinical_eligibility_not_assessed': True})
    return DirectoryResult(kind, dentist.pk, event.pk, False)
