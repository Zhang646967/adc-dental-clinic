"""Local-only credential exchange; patient permissions remain in portal.policies.

Lock order: code -> external identity -> users by PK -> account phone. Binding
and external login use this same order. No employee grant or PatientAccess write.
Real WeChat is deliberately unavailable until registered application acceptance.
"""
from datetime import timedelta
import hashlib,re,secrets
from uuid import uuid4
from django.conf import settings
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from accounts.models import UserAccount
from accounts.external_models import ExternalIdentity,LocalIdentityCode,AccountPhone,AccountIdentityEvent
from adc_core.commands import business_errors
from adc_core.rules import RuleError
from care.audit import emit

APP='adc-local-patient-v1'


def require_local():
    from accounts.auth_config import local_enabled
    if not local_enabled():
        raise PermissionDenied('当前环境未启用本地授权替身；请使用已分配患者账号。')
    if settings.ADC_READ_ONLY:raise PermissionDenied('只读实例不能办理账号和联络变更。')


@sensitive_variables()
def _digest(code):
    if not isinstance(code,str) or not 32<=len(code)<=160:
        raise RuleError('授权凭证无效或已使用，请重新获取；没有登录或变更资料。')
    return hashlib.sha256(code.encode()).hexdigest()


@transaction.atomic
@sensitive_variables()
def issue_local_code(*,subject=None,user_id=None,phone=None):
    """Private management command only. Raw code is returned once to the operator."""
    require_local();now=timezone.now();token=secrets.token_urlsafe(32)
    if subject is not None:
        if user_id is not None or phone is not None or not re.fullmatch(r'[a-z0-9_-]{1,64}',subject):
            raise RuleError('请使用明确的合成登录身份编号。')
        identity,_=ExternalIdentity.objects.get_or_create(provider='LOCAL',app_id=APP,subject=subject)
        row=LocalIdentityCode.objects.create(purpose='LOGIN',digest=_digest(token),identity=identity,expires_at=now+timedelta(minutes=5))
    else:
        if not isinstance(phone,str) or not re.fullmatch(r'0[0-9]{10}',phone):
            raise RuleError('本地手机替身只接收0开头的十一位合成号码，不验证真实号码。')
        user=UserAccount.objects.get(pk=user_id,is_active=True)
        row=LocalIdentityCode.objects.create(purpose='PHONE',digest=_digest(token),user=user,phone=phone,expires_at=now+timedelta(minutes=5))
    return token,row.expires_at


@sensitive_variables()
def _consume(code,purpose):
    require_local()
    row=LocalIdentityCode.objects.select_for_update().filter(digest=_digest(code),purpose=purpose).first()
    if row is None or row.consumed_at or row.expires_at<=timezone.now():
        raise RuleError('授权凭证无效、已过期或已使用，请重新获取；没有登录或变更资料。')
    row.consumed_at=timezone.now();row.save(update_fields=['consumed_at'])
    return row


def _record(user,action,*,identity=None,snapshot=None,operation=None):
    event=AccountIdentityEvent.objects.create(user=user,identity=identity,operation_id=operation or uuid4(),action=action,snapshot=snapshot or {})
    provider=identity.provider if identity else (snapshot or {}).get('provider','LOCAL')
    emit(user,'PATIENT_ACCOUNT_IDENTITY',event,summary={'action':action,'provider':provider,'synthetic':settings.ADC_CLINICAL_SYNTHETIC})
    return event


def _account_actor(actor):
    if not actor.is_authenticated or not UserAccount.objects.filter(pk=actor.pk,is_active=True).exists():raise PermissionDenied('请重新登录患者账号。')
    ctx=getattr(actor,'_adc_workspace',None)
    if ctx is not None:
        from workspaces.models import WorkspaceContext
        if not WorkspaceContext.objects.filter(pk=ctx.pk,user=actor,revision=ctx.revision,login_channel='PATIENT',role__in=['','PATIENT']).exists():
            raise PermissionDenied('请从患者通道办理账号资料。')
    from portal.policies import has_patient_account
    if not has_patient_account(actor):
        raise PermissionDenied('请先完成患者渠道账号登录。')


@business_errors
@transaction.atomic
@sensitive_variables()
def exchange_login(*,code,existing_user=None,existing_password=None):
    row=_consume(code,'LOGIN')
    identity=ExternalIdentity.objects.select_for_update().get(pk=row.identity_id,provider='LOCAL',app_id=APP)
    user_ids={value for value in (identity.user_id,getattr(existing_user,'pk',None)) if value}
    users={u.pk:u for u in UserAccount.objects.select_for_update().filter(pk__in=user_ids).order_by('pk')}
    from accounts.auth_config import has_live_credentials
    if any(has_live_credentials(u) for u in users.values()):
        raise PermissionDenied('已接入真实认证的账号不能使用本地模拟凭据。')
    if existing_user is not None:
        user=users[existing_user.pk]
        if not user.is_active or not user.check_password(existing_password or ''):raise PermissionDenied('原账号核对未通过。')
        from portal.policies import has_patient_account
        if not has_patient_account(user):raise PermissionDenied('原账号没有患者通道，请先办理本人档案关联。')
        if identity.user_id not in (None,user.pk):raise RuleError('该授权身份已有关联账号，请从原账号核对解绑；不会按手机号合并。')
    elif identity.user_id:
        user=users[identity.user_id]
        if not user.is_active:raise PermissionDenied('该账号已停用，请联系前台。')
    else:
        user=UserAccount(username='patient_'+uuid4().hex)
        user.set_unusable_password();user.save()
    if identity.user_id is None:
        identity.user=user;identity.revision+=1;identity.save(update_fields=['user','revision'])
        _record(user,'BIND',identity=identity,snapshot={'revision':identity.revision,'source':'LOCAL_SIMULATION'})
    _record(user,'LOGIN',identity=identity,snapshot={'revision':identity.revision,'source':'LOCAL_SIMULATION'})
    return user


@business_errors
@transaction.atomic
@sensitive_variables()
def verify_phone(*,actor,code,confirmed):
    if confirmed is not True:raise RuleError('请明确同意绑定此合成联络号码。')
    row=_consume(code,'PHONE')
    user=UserAccount.objects.select_for_update().get(pk=actor.pk)
    _account_actor(actor)
    from accounts.auth_config import has_live_credentials
    if has_live_credentials(user):raise PermissionDenied('真实认证账号不能使用模拟手机凭据。')
    if row.user_id!=user.pk:raise PermissionDenied('此手机号凭证不属于当前账号。')
    phone=AccountPhone.objects.select_for_update().filter(user=user).first()
    if phone:
        phone.phone=row.phone;phone.source='LOCAL_SIMULATION';phone.verified_at=timezone.now();phone.revision+=1
        phone.save(update_fields=['phone','source','verified_at','revision'])
    else:phone=AccountPhone.objects.create(user=user,phone=row.phone,source='LOCAL_SIMULATION',verified_at=timezone.now())
    _record(user,'PHONE_VERIFY',snapshot={'phone':phone.phone,'phone_revision':phone.revision,'source':'LOCAL_SIMULATION'})
    return phone


@business_errors
@transaction.atomic
@sensitive_variables()
def unlink_identity(*,actor,identity_id,expected_revision,password,confirmed):
    if settings.ADC_READ_ONLY:raise PermissionDenied('只读实例不能变更登录绑定。')
    if confirmed is not True:raise RuleError('请明确确认解除本次快捷登录绑定。')
    identity=ExternalIdentity.objects.select_for_update().get(pk=identity_id,user_id=actor.pk)
    user=UserAccount.objects.select_for_update().get(pk=actor.pk)
    _account_actor(actor)
    if not user.has_usable_password() or not user.check_password(password):raise RuleError('请先通过账号恢复设置可用密码，再核对密码解绑。')
    if identity.revision!=expected_revision:raise RuleError('绑定已变化，请刷新；没有覆盖原结果。')
    identity.user=None;identity.revision+=1;identity.save(update_fields=['user','revision'])
    _record(user,'UNBIND',identity=identity,snapshot={'revision':identity.revision,'source':identity.provider})
    return identity


@business_errors
@transaction.atomic
@sensitive_variables()
def set_login_password(*,actor,code,new_password,confirmed):
    if confirmed is not True:raise RuleError('请明确确认设置我的登录密码。')
    row=_consume(code,'LOGIN')
    identity=ExternalIdentity.objects.select_for_update().get(pk=row.identity_id)
    user=UserAccount.objects.select_for_update().get(pk=actor.pk)
    _account_actor(actor)
    from accounts.auth_config import has_live_credentials
    if has_live_credentials(user):raise PermissionDenied('真实认证账号不能使用模拟凭据设置密码。')
    if identity.user_id!=user.pk:raise PermissionDenied('请使用当前绑定身份的新授权凭证。')
    from django.contrib.auth.password_validation import validate_password
    try:validate_password(new_password,user=user)
    except ValidationError as exc:raise RuleError('；'.join(exc.messages)) from None
    user.set_password(new_password);user.save(update_fields=['password'])
    _record(user,'PASSWORD_SET',identity=identity,snapshot={'source':'LOCAL_SIMULATION','identity_revision':identity.revision})
    return user
