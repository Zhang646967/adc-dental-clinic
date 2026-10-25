"""Patient-channel credentials are distinct from patient/chart authority."""
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
            models.CheckConstraint(condition=Q(provider='LOCAL'),name='identity_local_provider_only')]


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
        constraints=[models.CheckConstraint(condition=Q(source='LOCAL_SIMULATION'),name='account_phone_local_source_only')]


class AccountIdentityEvent(models.Model):
    user=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT,related_name='identity_events')
    identity=models.ForeignKey(ExternalIdentity,on_delete=models.PROTECT,null=True,blank=True)
    operation_id=models.UUIDField(unique=True)
    action=models.CharField(max_length=24)
    snapshot=models.JSONField(default=dict)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='adc_account_identity_event'
