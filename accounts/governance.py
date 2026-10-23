"""v0.8 first increment: local-demo identity lifecycle with explicit technical authority.
No superuser bypass. No clinical read surface. No remapping established identities.
The HTTP console deliberately cannot manage itself or technical/superuser targets.
"""
import hashlib
import json
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import F, Q
from django.utils import timezone
from accounts.models import UserAccount, RoleAssignment
from accounts.policies import bindings, require_writable
from adc_core.commands import business_errors
from adc_core.rules import RuleError, validate_role_scope
from care.audit import emit
from care.models import CorrectionRequest
from coordination.models import WaitRequest
from coordination.reservations import lock_resources
from patients.models import Patient
from portal.models import PatientAccess
from registry.models import Clinic, Dentist
from scheduling.models import Visit
from workspaces.context import require_active
from workspaces.models import WorkspaceContext

SALT = 'adc.account-management.v08a1'
MANAGED_ROLES = {'DENTIST':'SELF_DENTIST','FRONT_DESK':'CLINIC','MANAGER':'CLINIC','HQ':'CHAIN','FINANCE':'CHAIN'}
ACTIONS = frozenset(('grant','revoke','reset_password','disable','enable','bind_patient','disable_patient_access','security_suspend','identity_reviewer'))


def require_technical(actor):
    require_active(actor, ('SYSADMIN',))
    if not bindings(actor).filter(role='SYSADMIN', scope_kind='TECHNICAL').exists():
        raise PermissionDenied('需要当前有效的技术管理身份。')


def state_digest(target):
    grant_rows=list(RoleAssignment.objects.filter(user=target).order_by('id').values_list('id','role','scope_kind','clinic_id','is_active','can_verify_patient_relationships'))
    access=list(PatientAccess.objects.filter(user=target).values_list('id','patient_id','is_active'))
    # Only the digest is serialized in the signed token, never the password hash itself.
    raw=json.dumps([target.pk,target.is_active,target.dentist_id,target.password,grant_rows,access],ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def target_token(actor, target):
    require_technical(actor)
    return signing.dumps({'actor':actor.pk,'target':target.pk,'state':state_digest(target)},salt=SALT)


def verify_target(actor, target, token):
    try:
        payload=signing.loads(token,salt=SALT,max_age=15*60)
    except (signing.BadSignature, ValueError, TypeError):
        raise RuleError('账号操作页已过期，请刷新并重新核对。')
    if payload != {'actor':actor.pk,'target':target.pk,'state':state_digest(target)}:
        raise RuleError('目标账号、密码或授权已变化，本次未执行。请刷新后核对。')


def lock_operator(actor, operator_password, target_id=None):
    """All console mutations share the same advisory lock and canonical user order."""
    if not connection.in_atomic_block:
        raise RuntimeError('Account lifecycle must run in a transaction')
    with connection.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(%s,%s)',[8101,1])
    ids=sorted(set([actor.pk]+([target_id] if target_id is not None else [])))
    users={u.pk:u for u in UserAccount.objects.select_for_update().filter(pk__in=ids).order_by('pk')}
    require_writable(actor)
    require_technical(actor)
    fresh=users[actor.pk]
    if not fresh.check_password(operator_password):
        raise ValidationError('技术管理密码不正确，本次未执行。')
    return users.get(target_id)


def check_reason(reason):
    text=(reason or '').strip()
    if not 4 <= len(text) <= 500:
        raise ValidationError('请填写4至500字的操作依据；不要填写密码、密钥或患者医疗信息。')
    return text


def invalidate_contexts(target):
    WorkspaceContext.objects.filter(user=target).update(role='',clinic=None,patient_grant=None,revision=F('revision')+1,updated_at=timezone.now())


def protected_target(actor, target):
    if actor.pk == target.pk:
        raise PermissionDenied('不能在技术管理页修改自己的账号或授权；本人改密请使用“修改我的密码”。')
    if target.is_superuser or RoleAssignment.objects.filter(user=target,role='SYSADMIN',is_active=True).exists():
        raise PermissionDenied('技术管理与超级用户账号由独立管理命令维护；此页面不允许操作。')


def pending_work(target):
    access=PatientAccess.objects.filter(user=target).first()
    pid=access.patient_id if access else None
    lock_resources(patients=[pid] if pid else [],dentists=[target.dentist_id] if target.dentist_id else [])
    affected=Q(pk__in=[])
    if pid: affected |= Q(patient_id=pid)
    if target.dentist_id: affected |= Q(dentist_id=target.dentist_id)
    pending=Visit.objects.filter(affected,status__in=['SCHEDULED','CHECKED_IN']).exists()
    waits=WaitRequest.objects.filter(patient_id=pid,state__in=['WAITING','OFFERED']).exists() if pid else False
    corrections=CorrectionRequest.objects.filter(Q(requester=target)|Q(dentist_confirmed_by=target),status='OPEN').exists()
    return pending or waits or corrections


@business_errors
@transaction.atomic
def create_account(*, actor, username, password, operator_password, reason, dentist_id=None):
    lock_operator(actor,operator_password)
    reason=check_reason(reason)
    if UserAccount.objects.filter(username=username).exists():
        raise RuleError('用户名已存在，请选择其他用户名。')
    dentist=None
    if dentist_id is not None:
        dentist=Dentist.objects.select_for_update().get(pk=dentist_id,is_active=True)
        if UserAccount.objects.filter(dentist=dentist).exists():
            raise RuleError('该牙医已绑定其他账号；不允许覆盖原有身份关联。')
    target=UserAccount(username=username,dentist=dentist,is_active=True,is_staff=False,is_superuser=False)
    validate_password(password,user=target)
    target.set_password(password)
    target.full_clean()
    target.save()
    emit(actor,'ACCOUNT_CREATED',target,reason=reason,summary={'initial_roles':0})
    return target


@business_errors
@transaction.atomic
def change_account(*, actor, target_id, token, action, operator_password, reason, role=None, clinic_id=None,
                   grant_id=None, patient_no=None, new_password=None, reviewer_enabled=False):
    target=lock_operator(actor,operator_password,target_id)
    if target is None: raise UserAccount.DoesNotExist
    protected_target(actor,target)
    verify_target(actor,target,token)
    reason=check_reason(reason)
    if action not in ACTIONS:raise PermissionDenied('未知账号管理操作。')
    if not target.is_active and action not in ('enable','reset_password'):
        raise RuleError('账号已停用，请先核对并启用，再变更授权。')
    summary={'action':action}
    if action == 'grant':
        if role not in MANAGED_ROLES:raise PermissionDenied('此页面不发放技术管理身份。')
        scope=MANAGED_ROLES[role]
        clinic=Clinic.objects.get(pk=clinic_id,is_active=True) if scope=='CLINIC' else None
        if scope!='CLINIC' and clinic_id is not None:raise RuleError('该身份不接受诊所范围，请清空诊所选项。')
        if role=='DENTIST' and not Dentist.objects.filter(pk=target.dentist_id,is_active=True).exists():
            raise RuleError('账号尚未绑定有效牙医，请先通过受控创建流程建立身份关联。')
        validate_role_scope(role,scope,clinic.pk if clinic else None,target.dentist_id)
        obj,_=RoleAssignment.objects.update_or_create(user=target,role=role,scope_kind=scope,clinic=clinic,defaults={'is_active':True})
        summary.update(role=role,clinic_id=clinic.pk if clinic else None,grant_id=obj.pk)
    elif action == 'revoke':
        obj=RoleAssignment.objects.select_for_update().get(pk=grant_id,user=target)
        if obj.role not in MANAGED_ROLES:raise PermissionDenied('不能在此撤回技术管理身份。')
        if obj.role=='DENTIST' and pending_work(target):raise RuleError('仍有未闭合业务，请先安排交接；没有撤回牙医身份。')
        obj.is_active=False;obj.can_verify_patient_relationships=False
        obj.save(update_fields=['is_active','can_verify_patient_relationships']);summary['grant_id']=obj.pk
    elif action == 'identity_reviewer':
        obj=RoleAssignment.objects.select_for_update().get(pk=grant_id,user=target,role='FRONT_DESK',scope_kind='CLINIC',is_active=True,clinic__is_active=True)
        obj.can_verify_patient_relationships=bool(reviewer_enabled)
        obj.save(update_fields=['can_verify_patient_relationships'])
        summary.update(grant_id=obj.pk,identity_reviewer=obj.can_verify_patient_relationships)
    elif action == 'reset_password':
        validate_password(new_password or '',user=target)
        target.set_password(new_password);target.save(update_fields=['password'])
    elif action == 'disable':
        if pending_work(target):raise RuleError('仍有预约、候补、接诊或更正待处理，请先完成或交接；没有停用账号。')
        target.is_active=False;target.save(update_fields=['is_active'])
    elif action == 'security_suspend':
        # Security suspension is NOT business retirement. Do not wait for pending
        # visits, delete grants, cancel appointments, or rewrite clinical records.
        # Changing the session-auth hash prevents an old session from reviving
        # after a later re-enable. Recovery requires a separate password reset.
        target.is_active=False
        target.set_unusable_password()
        target.save(update_fields=['is_active','password'])
        summary.update(credential_reset_required=True,business_records_unchanged=True)
    elif action == 'enable':
        if not target.has_usable_password():
            raise RuleError('该账号凭据已失效。请先完成受控密码重置，再核对并启用；原会话不会恢复。')
        target.is_active=True;target.save(update_fields=['is_active'])
    elif action == 'bind_patient':
        if PatientAccess.objects.filter(user=target).exists():raise RuleError('此账号已有患者绑定；不允许覆盖或更换患者身份。')
        patient=Patient.objects.select_for_update().get(patient_no=patient_no,is_active=True)
        if PatientAccess.objects.filter(patient=patient).exists():raise RuleError('该患者已有绑定账号；不允许重复认领。')
        PatientAccess.objects.create(user=target,patient=patient)
        summary['binding_created']=True
    elif action == 'disable_patient_access':
        if pending_work(target):raise RuleError('仍有未闭合业务，请先处理；没有停用患者入口。')
        access=PatientAccess.objects.select_for_update().get(user=target)
        access.is_active=False;access.save(update_fields=['is_active'])
    invalidate_contexts(target)
    emit(actor,'ACCOUNT_GOVERNED',target,reason=reason,summary=summary)
    return target
