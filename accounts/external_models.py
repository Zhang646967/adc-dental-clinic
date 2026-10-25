"""Patient-channel credentials are distinct from patient/chart authority."""
import uuid
from django.db import models
from django.db.models import Q


class ExternalIdentity(models.Model):
    provider=models.CharField(max_length=16,default='LOCAL')
    app_id=models.CharField(max_length=80)
    subject=models.CharField(max_length=160)
    user=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT,null=True,blank=True,related_name='external_identities')
    revision=models.PositiveIntegerField(default=0)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='adc_external_identity'
        constraints=[models.UniqueConstraint(fields=['provider','app_id','subject'],name='external_identity_application_subject'),
            models.CheckConstraint(condition=Q(provider__in=['LOCAL','WECHAT_MINI','WECHAT_WEB','WECHAT_MP','SMS']),name='identity_supported_provider'),
            models.UniqueConstraint(fields=['user'],condition=Q(provider='SMS',user__isnull=False),name='one_sms_login_per_account')]


class LocalIdentityCode(models.Model):
    """Private maintenance-issued surrogate, never a client-asserted OpenID."""
    purpose=models.CharField(max_length=8,choices=[('LOGIN','本地登录替身'),('PHONE','本地手机替身')])
    digest=models.CharField(max_length=64,unique=True)
    identity=models.ForeignKey(ExternalIdentity,on_delete=models.PROTECT,null=True,blank=True)
    user=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT,null=True,blank=True)
    phone=models.CharField(max_length=32,blank=True)
    expires_at=models.DateTimeField()
    consumed_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='adc_local_identity_code'
        constraints=[models.CheckConstraint(condition=(Q(purpose='LOGIN',identity__isnull=False,user__isnull=True,phone='')|
            (Q(purpose='PHONE',identity__isnull=True,user__isnull=False)&~Q(phone=''))),name='local_identity_code_purpose')]


class AccountPhone(models.Model):
    user=models.OneToOneField('accounts.UserAccount',on_delete=models.PROTECT,related_name='verified_phone')
    phone=models.CharField(max_length=32)
    source=models.CharField(max_length=24,default='LOCAL_SIMULATION')
    revision=models.PositiveIntegerField(default=1)
    verified_at=models.DateTimeField()
    class Meta:
        db_table='adc_account_phone'
        constraints=[models.CheckConstraint(condition=Q(source__in=['LOCAL_SIMULATION','WECHAT_PHONE','SMS_VERIFIED','DEMO_SMS']),name='account_phone_known_source')]


class AccountIdentityEvent(models.Model):
    user=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT,related_name='identity_events')
    identity=models.ForeignKey(ExternalIdentity,on_delete=models.PROTECT,null=True,blank=True)
    operation_id=models.UUIDField(unique=True)
    action=models.CharField(max_length=24)
    snapshot=models.JSONField(default=dict)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='adc_account_identity_event'


class SmsChallenge(models.Model):
    """Short-lived, session/purpose-bound OTP; never store a raw verification code."""
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    phone=models.CharField(max_length=16)
    purpose=models.CharField(max_length=8,choices=[('LOGIN','注册或登录'),('BIND','绑定登录号码')])
    user=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT,null=True,blank=True)
    provider=models.CharField(max_length=16)
    session_digest=models.CharField(max_length=64)
    ip_digest=models.CharField(max_length=64)
    code_digest=models.CharField(max_length=64)
    state=models.CharField(max_length=8,default='PENDING',choices=[('PENDING','发送中'),('SENT','已提交发送'),('FAILED','发送失败')])
    attempts=models.PositiveSmallIntegerField(default=0)
    expires_at=models.DateTimeField()
    consumed_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='adc_sms_challenge'
        indexes=[models.Index(fields=['phone','created_at'],name='sms_phone_created'),models.Index(fields=['ip_digest','created_at'],name='sms_ip_created')]
        constraints=[models.CheckConstraint(condition=Q(purpose='LOGIN',user__isnull=True)|Q(purpose='BIND',user__isnull=False),name='sms_purpose_owner'),
            models.CheckConstraint(condition=Q(attempts__lte=5),name='sms_attempt_limit'),
            models.CheckConstraint(condition=Q(provider__in=['tencent','demo']),name='sms_known_provider')]
