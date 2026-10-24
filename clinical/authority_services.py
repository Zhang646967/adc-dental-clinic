"""Explicit proposal -> independent decision -> retained scope/history."""
from datetime import datetime
import uuid
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from accounts.models import RoleAssignment, UserAccount
from accounts.policies import lock_clinic_grant, require_clinic, require_writable
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal, workspace_binding
from adc_core.rules import RuleError
from care.audit import emit
from clinical.authority import require_reviewer, professional_scope, visit_service_id
from clinical.models import ClinicalAuthorityEvent, ClinicalAuthorityPolicy, ClinicalReviewerAppointment, ProfessionalAuthorization
from registry.models import Clinic
from scheduling.resource_models import BookingService

CONTRACT = 'adc.clinical-authority.c12.v1'
ROLES = ('MANAGER', 'DENTIST')


def lock_people(actor, *other_ids):
    users = {u.pk: u for u in UserAccount.objects.select_for_update().filter(
        pk__in=sorted(set((actor.pk,) + other_ids))).order_by('pk')}
    require_writable(actor)
    return users


def text(value, label, limit=160):
    if not isinstance(value, str) or not 4 <= len(value.strip()) <= limit:
        raise RuleError(f'{label}须填写4至{limit}字。')
    return value.strip()


def date_time(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        if not timezone.is_aware(result):
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise RuleError('请填写带时区的完整生效与失效时间。')


def validate_case(data):
    result = dict(data)
    for key in ('credential_from', 'credential_until', 'valid_from', 'valid_until'):
        result[key] = date_time(data[key])
    if not result['credential_from'] <= result['valid_from'] < result['valid_until'] <= result['credential_until']:
        raise RuleError('操作授权必须完整处于资质证据有效期内。')
    if result['valid_until'] <= timezone.now():
        raise RuleError('不能批准已经过期的授权。')
    if result['source_kind'] not in dict(ProfessionalAuthorization.SOURCES):
        raise RuleError('请选择明确的资质核验来源。')
    if result['source_kind'] == 'SYNTHETIC' and not settings.ADC_CLINICAL_SYNTHETIC:
        raise RuleError('当前环境不接受合成资质。')
    for key, label in [('issuer', '来源机构'), ('source_reference', '证据参考编号')]:
        result[key] = text(data[key], label)
    for key in ('can_read', 'can_record', 'can_refer'):
        if type(data[key]) is not bool:
            raise RuleError('请选择明确的操作范围。')
    if not result['can_read']:
        raise RuleError('专业操作授权必须包含必要的临床查阅范围。')
    subject = UserAccount.objects.filter(pk=data['user_id'], is_active=True, dentist__is_active=True).first()
    if subject is None or not RoleAssignment.objects.filter(user=subject, role='DENTIST', scope_kind='SELF_DENTIST', is_active=True).exists():
        raise RuleError('目标账号必须关联在用医师，并已具有有效医师工作身份。')
    if data['service_id'] is not None and not BookingService.objects.filter(pk=data['service_id'],
        department__clinic_id=data['clinic_id'], is_active=True, dentists=subject.dentist_id).exists():
        raise RuleError('服务不属于此诊所、已经停用或尚未适配该医师。')
    if not Clinic.objects.filter(pk=data['clinic_id'], is_active=True).exists():
        raise RuleError('诊所已停用。')
    return result


def snapshot(row):
    fields = ('user_id', 'clinic_id', 'service_id', 'source_kind', 'source_reference', 'issuer',
        'credential_from', 'credential_until', 'valid_from', 'valid_until', 'can_read', 'can_record', 'can_refer')
    return {key: getattr(row, key).isoformat() if isinstance(getattr(row, key), datetime) else getattr(row, key) for key in fields}


def prepare_authority(*, actor, action, case_id=None, fields=None):
    binding = workspace_binding(actor, ROLES)
    fields = fields or {}
    if action == 'PROPOSE':
        if binding['role'] != 'MANAGER':
            raise PermissionDenied('本店主管负责整理专业授权申请。')
        data = dict(fields, clinic_id=binding['clinic'])
        require_clinic(actor, data['clinic_id'], ('MANAGER',))
        data = validate_case(data)
        data = {k: v.isoformat() if isinstance(v, datetime) else v for k, v in data.items()}
        data = dict(action=action, fields=data)
    elif action == 'ACTIVATE':
        reviewer = require_reviewer(actor, fields['clinic_id'])
        data = dict(action=action, clinic_id=reviewer.clinic_id, reviewer_id=reviewer.pk,
            reviewer_revision=reviewer.revision, note=text(fields.get('note'), '启用依据', 500))
    else:
        row = ProfessionalAuthorization.objects.get(pk=case_id)
        reviewer = require_reviewer(actor, row.clinic_id)
        check_decision(actor, row, action)
        data = dict(action=action, case_id=row.pk, revision=row.revision, reviewer_id=reviewer.pk,
            reviewer_revision=reviewer.revision, note=text(fields.get('note'), '审核依据', 500))
    return {'proposal_token': proposal(actor, CONTRACT, ROLES, data), 'data': data}


def check_decision(actor, row, action):
    if actor.pk in (row.user_id, row.created_by_id):
        raise PermissionDenied('不能审核自己的专业范围或自己整理的申请；切换身份也不能自审。')
    allowed = {'APPROVE': ('PENDING',), 'REJECT': ('PENDING',), 'SUSPEND': ('APPROVED',),
        'REVOKE': ('APPROVED', 'SUSPENDED'), 'RESUME': ('SUSPENDED',)}
    if action not in allowed or row.state not in allowed[action]:
        raise RuleError('申请状态已变化，请重新核对当前结果。')
    if action in ('APPROVE', 'RESUME'):
        validate_case(snapshot(row))


def activation_check(clinic_id):
    from scheduling.models import Visit
    now = timezone.now()
    for visit in Visit.objects.filter(clinic_id=clinic_id).filter(
        status__in=['SCHEDULED', 'CHECKED_IN']).select_related('dentist').order_by('pk'):
        user_id = UserAccount.objects.filter(dentist_id=visit.dentist_id, is_active=True).values_list('pk', flat=True).first()
        moment = max(now, visit.scheduled_start)
        try:
            professional_scope(user_id, clinic_id, visit_service_id(visit), 'RECORD', at=moment)
        except PermissionDenied:
            raise RuleError(f'预约 {visit.visit_no} 的医师、服务或预约日期尚无有效记录授权，请先补齐或明确协调。')


@business_errors
@transaction.atomic
def confirm_authority(*, actor, proposal_token, confirmed):
    if confirmed is not True:
        raise RuleError('请明确确认已核对的专业授权内容。')
    payload = read_proposal(actor, CONTRACT, ROLES, proposal_token)
    data = payload['data']; action = data['action']
    old = ProfessionalAuthorization.objects.get(pk=data['case_id']) if 'case_id' in data else None
    subject_id = old.user_id if old else data['fields']['user_id'] if action == 'PROPOSE' else actor.pk
    lock_people(actor, subject_id)
    read_proposal(actor, CONTRACT, ROLES, proposal_token)
    clinic_id = old.clinic_id if old else data['fields']['clinic_id'] if action == 'PROPOSE' else data['clinic_id']
    reviewer = None
    if action == 'PROPOSE':
        lock_clinic_grant(actor, clinic_id, ('MANAGER',))
    else:
        reviewer = require_reviewer(actor, clinic_id, lock=True)
    previous = ClinicalAuthorityEvent.objects.filter(operation_id=payload['operation'], actor=actor).first()
    if previous:
        return (previous.authorization or ClinicalAuthorityPolicy.objects.get(clinic_id=clinic_id)), True
    if reviewer and (reviewer.pk != data['reviewer_id'] or reviewer.revision != data['reviewer_revision']):
        raise RuleError('审核职责已变化，请重新预览。')
    prior = ''
    if action == 'PROPOSE':
        row = ProfessionalAuthorization.objects.create(created_by=actor, **validate_case(data['fields']))
        note = '本店主管提交专业证据与操作范围，等待独立审核。'
    elif action == 'ACTIVATE':
        Clinic.objects.select_for_update().get(pk=clinic_id, is_active=True)
        if ClinicalAuthorityPolicy.objects.filter(clinic_id=clinic_id).exists():
            raise RuleError('本店已启用专业范围控制，无须再次启用。')
        activation_check(clinic_id)
        row = ClinicalAuthorityPolicy.objects.create(clinic_id=clinic_id, activated_by=actor, reference=data['note'])
        note = data['note']
    else:
        row = ProfessionalAuthorization.objects.select_for_update().get(pk=old.pk)
        if row.revision != data['revision']:
            raise RuleError('申请或决定已变化，请重新预览；本次没有覆盖既有结果。')
        check_decision(actor, row, action)
        prior = row.state
        row.state = {'APPROVE': 'APPROVED', 'REJECT': 'REJECTED', 'SUSPEND': 'SUSPENDED',
            'REVOKE': 'REVOKED', 'RESUME': 'APPROVED'}[action]
        row.revision += 1
        row.save(update_fields=['state', 'revision'])
        note = data['note']
        from accounts.governance import invalidate_contexts
        invalidate_contexts(row.user)
    ClinicalAuthorityEvent.objects.create(actor=actor, clinic_id=clinic_id, reviewer=reviewer,
        authorization=row if isinstance(row, ProfessionalAuthorization) else None,
        operation_id=payload['operation'], action=action, prior_state=prior,
        resulting_state=row.state if isinstance(row, ProfessionalAuthorization) else 'ACTIVE', note=note,
        snapshot=snapshot(row) if isinstance(row, ProfessionalAuthorization) else {'clinic_id': clinic_id})
    emit(actor, 'CLINICAL_AUTHORITY_DECIDED', row, summary={'action': action, 'clinic_id': clinic_id})
    return row, False


def appoint_reviewer(*, actor, target, clinic_id, enabled, reference, valid_from, valid_until):
    """Only called inside password-verified account governance with sorted user locks."""
    from accounts.governance import require_technical
    require_technical(actor)
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError('Reviewer appointment requires account governance transaction')
    clinic = Clinic.objects.get(pk=clinic_id, is_active=True)
    reference = text(reference, '机构委任依据')
    begin, end = date_time(valid_from), date_time(valid_until)
    if not begin < end or (enabled and end <= timezone.now()):
        raise RuleError('请填写有效的审核职责期限。')
    if not target.dentist_id or not RoleAssignment.objects.filter(user=target, role='DENTIST', scope_kind='SELF_DENTIST', is_active=True).exists():
        raise RuleError('审核职责只能授予有效的医师工作账号。')
    row, created = ClinicalReviewerAppointment.objects.select_for_update().get_or_create(user=target, clinic=clinic,
        defaults=dict(reference=reference, valid_from=begin, valid_until=end, is_active=enabled, appointed_by=actor))
    if not created:
        row.reference=reference; row.valid_from=begin; row.valid_until=end; row.is_active=enabled
        row.appointed_by=actor; row.appointed_at=timezone.now(); row.revision+=1
        row.save()
    ClinicalAuthorityEvent.objects.create(actor=actor, clinic=clinic, reviewer=row, operation_id=uuid.uuid4(),
        action='APPOINT_REVIEWER', resulting_state='ACTIVE' if enabled else 'REVOKED', note=reference,
        snapshot=dict(user_id=target.pk, revision=row.revision, valid_from=begin.isoformat(), valid_until=end.isoformat(), is_active=enabled))
    return row
