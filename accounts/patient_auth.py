"""Patient-only credential commands; no chart, employee or appointment grants."""
from datetime import timedelta
import hashlib,hmac,ipaddress,re,secrets
from uuid import uuid4
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import connection,transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from accounts.models import UserAccount
from accounts.external_models import AccountPhone,ExternalIdentity,SmsChallenge
from accounts.external_identity import _account_actor,_record
from accounts import auth_providers
from adc_core.commands import business_errors
from adc_core.rules import RuleError

SMS_APP='adc-patient-phone-v1'


def writable():
    if settings.ADC_READ_ONLY:raise PermissionDenied('只读实例不能注册、登录授权或变更账号资料。')


@sensitive_variables()
def digest(value):return hmac.new(settings.SECRET_KEY.encode(),value.encode(),hashlib.sha256).hexdigest()


def session_key(request,*,create=False):
    key=request.session.get('adc_auth_session')
    if not key and create:key=secrets.token_urlsafe(32);request.session['adc_auth_session']=key
    if not key:raise RuleError('验证页面已失效，请重新获取验证码。')
    return digest('session:'+key)


def phone_number(phone):
    demo=auth_providers.capabilities()['sms_demo']
    pattern=r'0[0-9]{10}' if demo else r'1[3-9][0-9]{9}'
    if not isinstance(phone,str) or not re.fullmatch(pattern,phone):
        raise RuleError('测试环境请使用0开头的十一位合成号码。' if demo else '请填写有效的中国大陆手机号。')
    return phone


@business_errors
@transaction.atomic
@sensitive_variables()
def exchange_identity(*,provider,app_id,subject,existing_user=None,existing_password=None,binding_actor=None):
    """Inputs originate only from the server provider adapter or verified OTP."""
    writable()
    if provider not in ('WECHAT_MINI','WECHAT_WEB','WECHAT_MP','SMS'):raise RuleError('登录方式无效。')
    if provider=='SMS':
        with connection.cursor() as cursor:cursor.execute('SELECT pg_advisory_xact_lock(%s)',[87040582])
    identity,_=ExternalIdentity.objects.get_or_create(provider=provider,app_id=app_id,subject=subject)
    identity=ExternalIdentity.objects.select_for_update().get(pk=identity.pk)
    if binding_actor is not None:
        _account_actor(binding_actor);existing_user=binding_actor
    ids={pk for pk in (identity.user_id,getattr(existing_user,'pk',None)) if pk}
    users={user.pk:user for user in UserAccount.objects.select_for_update().filter(pk__in=ids).order_by('pk')}
    if provider=='SMS' and auth_providers.capabilities()['sms_demo']:
        from accounts.auth_config import has_live_credentials
        if any(has_live_credentials(u) for u in users.values()):raise PermissionDenied('真实认证账号不能使用演示验证码。')
    if existing_user is not None:
        user=users[existing_user.pk]
        from portal.policies import has_patient_account
        if not user.is_active or not has_patient_account(user) or (binding_actor is None and not user.check_password(existing_password or '')):
            raise PermissionDenied('原患者账号核对未通过，请重新登录。')
        if identity.user_id not in (None,user.pk):raise RuleError('此登录方式已绑定其他账号，请使用原账号登录；不会合并患者档案。')
    elif identity.user_id:
        user=users[identity.user_id]
        if not user.is_active:raise PermissionDenied('该账号已停用，请联系门店。')
    else:
        user=UserAccount(username='patient_'+uuid4().hex);user.set_unusable_password();user.save()
    if provider=='SMS' and existing_user is not None:
        for previous in ExternalIdentity.objects.select_for_update().filter(provider='SMS',user=user).exclude(pk=identity.pk).order_by('pk'):
            previous.user=None;previous.revision+=1;previous.save(update_fields=['user','revision'])
            _record(user,'PHONE_REPLACED',identity=previous,snapshot={'source':'SMS','revision':previous.revision})
    if identity.user_id is None:
        identity.user=user;identity.revision+=1;identity.save(update_fields=['user','revision'])
        _record(user,'BIND',identity=identity,snapshot={'source':provider,'revision':identity.revision})
    _record(user,'LOGIN' if binding_actor is None else 'CREDENTIAL_BIND',identity=identity,snapshot={'source':provider,'revision':identity.revision})
    return user


def _phone_record(user,phone,source):
    item=AccountPhone.objects.select_for_update().filter(user=user).first()
    if item:
        item.phone=phone;item.source=source;item.verified_at=timezone.now();item.revision+=1
        item.save(update_fields=['phone','source','verified_at','revision'])
    else:item=AccountPhone.objects.create(user=user,phone=phone,source=source,verified_at=timezone.now())
    _record(user,'PHONE_VERIFY',snapshot={'source':source,'provider':'SMS' if source in ('SMS_VERIFIED','DEMO_SMS') else 'WECHAT_MINI','phone_revision':item.revision})
    return item


@sensitive_variables()
def request_sms(*,request,phone,purpose,confirmed,captcha_key=''):
    writable();caps=auth_providers.capabilities()
    if confirmed is not True:raise RuleError('请同意使用此号码接收验证码并办理本人账号。')
    if not caps['sms_enabled']:raise RuleError('短信注册尚未开通，请使用账号密码登录。')
    phone=phone_number(phone);user=None
    if purpose=='BIND':_account_actor(request.user);user=request.user
    elif purpose!='LOGIN':raise RuleError('验证码用途无效。')
    session=session_key(request,create=True)
    address=request.META.get('HTTP_X_ADC_CLIENT_IP') if getattr(settings,'SECURE_PROXY_SSL_HEADER',None) else None
    try:address=str(ipaddress.ip_address(address or request.META.get('REMOTE_ADDR','127.0.0.1')))
    except ValueError:raise RuleError('无法确认访问来源，请稍后重试。') from None
    ip=digest('ip:'+address);now=timezone.now();code=f'{secrets.randbelow(1000000):06d}';pk=uuid4()
    if settings.ADC_SMS_PROVIDER=='cloudbase' and phone not in settings.ADC_SMS_ALLOWED_TEST_PHONES:
        raise RuleError('当前仅向已约定的免费联调号码发送验证码。')
    with transaction.atomic():
        # One short database lock serializes cost limits across all web workers.
        with connection.cursor() as cursor:cursor.execute('SELECT pg_advisory_xact_lock(%s)',[87040581])
        rows=SmsChallenge.objects.all()
        if settings.ADC_SMS_PROVIDER=='cloudbase' and rows.filter(provider='cloudbase').count()>=min(10,settings.ADC_SMS_LIVE_TEST_LIMIT):
            raise RuleError('本轮免费短信联调次数已用完，未继续调用平台。')
        if rows.filter(phone=phone,created_at__gt=now-timedelta(seconds=60)).exists():raise RuleError('验证码刚刚发送，请60秒后再试。')
        if (rows.filter(phone=phone,created_at__gt=now-timedelta(days=1)).count()>=5 or
                rows.filter(ip_digest=ip,created_at__gt=now-timedelta(hours=1)).count()>=10 or
                rows.filter(created_at__gt=now-timedelta(days=1)).count()>=settings.ADC_SMS_GLOBAL_DAILY_LIMIT):
            raise RuleError('验证码请求次数已达上限，请稍后再试或使用账号密码。')
        SmsChallenge.objects.filter(phone=phone,session_digest=session,purpose=purpose,consumed_at__isnull=True).update(expires_at=now)
        row=SmsChallenge.objects.create(id=pk,phone=phone,purpose=purpose,user=user,provider=settings.ADC_SMS_PROVIDER,session_digest=session,ip_digest=ip,
            code_digest='' if settings.ADC_SMS_PROVIDER=='cloudbase' else digest(str(pk)+':'+code),expires_at=now+timedelta(minutes=5))
    # Sending happens after reservation commits. A timeout never frees a rate
    # allowance and never silently switches to the synthetic delivery provider.
    expires=300;reference=''
    try:
        if settings.ADC_SMS_PROVIDER=='cloudbase':
            captcha_token=None;captcha=request.session.pop('adc_sms_captcha',None)
            if captcha:
                if captcha['expires']<=timezone.now().timestamp() or captcha['session']!=session:raise RuleError('图片验证码已过期，请刷新。')
                captcha_token=auth_providers.cloudbase_verify_captcha(captcha['token'],captcha_key.strip())
            reference,expires=auth_providers.cloudbase_send(phone,captcha_token=captcha_token)
        else:auth_providers.send_sms(phone,code)
    except RuleError:
        SmsChallenge.objects.filter(pk=pk).update(state='FAILED')
        raise
    SmsChallenge.objects.filter(pk=pk).update(state='SENT',provider_reference=reference,expires_at=now+timedelta(seconds=expires))
    result=dict(challenge=str(pk),expires_seconds=expires,retry_after_seconds=60,demo=caps['sms_demo'])
    if caps['sms_demo']:result['test_code']=code
    return result


@sensitive_variables()
def confirm_sms(*,request,challenge,phone,code,purpose,confirmed):
    writable()
    if confirmed is not True:raise RuleError('请明确确认使用此号码办理账号。')
    if not auth_providers.capabilities()['sms_enabled']:raise RuleError('短信注册尚未开通。')
    phone=phone_number(phone);session=session_key(request);error=None;user=None
    with transaction.atomic():
        row=SmsChallenge.objects.select_for_update().filter(pk=challenge).first()
        if (row is None or row.state!='SENT' or row.provider!=settings.ADC_SMS_PROVIDER or row.phone!=phone or row.session_digest!=session or row.purpose!=purpose or
                row.consumed_at or row.expires_at<=timezone.now() or row.attempts>=5 or row.user_id!=(request.user.pk if purpose=='BIND' else None)):
            error='验证码无效、已使用或已过期，请重新获取。'
        else:
            try:
                if not isinstance(code,str) or not re.fullmatch(r'[0-9]{6}',code):raise RuleError('请填写六位验证码。')
                if row.provider=='cloudbase':auth_providers.cloudbase_verify(row.provider_reference,code)
                elif not secrets.compare_digest(row.code_digest,digest(str(row.pk)+':'+code)):raise RuleError('验证码不正确，请重新核对。')
            except RuleError as exc:
                row.attempts+=1;row.save(update_fields=['attempts']);error=str(exc)
            if not error:
                actor=request.user if purpose=='BIND' else None
                user=exchange_identity(provider='SMS',app_id=SMS_APP,subject=phone,binding_actor=actor)
                _phone_record(user,phone,'DEMO_SMS' if row.provider=='demo' else 'SMS_VERIFIED')
                row.consumed_at=timezone.now();row.save(update_fields=['consumed_at'])
    # Raise after the transaction so incorrect attempts remain counted.
    if error:raise RuleError(error)
    return user


@business_errors
@transaction.atomic
@sensitive_variables()
def bind_wechat_phone(*,actor,code,confirmed):
    writable();_account_actor(actor)
    if confirmed is not True:raise RuleError('请确认授权微信手机号用于本人账号联络和登录。')
    if not ExternalIdentity.objects.filter(user=actor,provider='WECHAT_MINI',app_id=settings.ADC_WECHAT_MINI_APP_ID).exists():
        raise RuleError('请先登录并绑定当前小程序微信身份，再授权手机号。')
    phone=auth_providers.wechat_phone(code)
    user=exchange_identity(provider='SMS',app_id=SMS_APP,subject=phone,binding_actor=actor)
    return _phone_record(user,phone,'WECHAT_PHONE')
