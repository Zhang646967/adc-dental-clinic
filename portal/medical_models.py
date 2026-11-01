"""Medical representation is independent of appointment delegation."""
from django.conf import settings
from django.db import models
from django.db.models import Q, F


class MedicalProxy(models.Model):
    STATES = [('MATERIALS','待资料核对'),('DOCTOR','待医师确认'),('REVIEW','待独立医务确认'),('ACTIVE','生效'),('RETURNED','退回补充'),('REJECTED','不通过'),('SUSPENDED','已暂停'),('REVOKED','已撤销')]
    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT)
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    delegate = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='medical_proxies')
    kind = models.CharField(max_length=16, choices=[('GUARDIAN','未成年监护'),('WRITTEN','成年患者书面委托')])
    state = models.CharField(max_length=16, choices=STATES, default='MATERIALS')
    revision = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'adc_medical_proxy'
        indexes = [models.Index(fields=['clinic','state'], name='medical_proxy_queue')]
        constraints = [models.CheckConstraint(condition=Q(state__in=['MATERIALS','DOCTOR','REVIEW','ACTIVE','RETURNED','REJECTED','SUSPENDED','REVOKED']), name='medical_proxy_state'), models.CheckConstraint(condition=Q(kind__in=['GUARDIAN','WRITTEN']), name='medical_proxy_kind')]


class MedicalProxyVersion(models.Model):
    patient_snapshot = models.JSONField(default=dict, db_default={})
    delegate_name = models.CharField(max_length=100,default='',db_default='')
    proxy = models.ForeignKey(MedicalProxy, on_delete=models.PROTECT, related_name='versions')
    number = models.PositiveIntegerField()
    plan = models.ForeignKey('clinical.TreatmentPlan', on_delete=models.PROTECT)
    identity_reference = models.CharField(max_length=500)
    authority_reference = models.CharField(max_length=500)
    applicability = models.CharField(max_length=1000)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'adc_medical_proxy_version'
        constraints = [models.UniqueConstraint(fields=['proxy','number'], name='medical_proxy_version_number'), models.CheckConstraint(condition=Q(valid_until__gt=F('valid_from')), name='medical_proxy_interval')]


class MedicalProxyScope(models.Model):
    version = models.ForeignKey(MedicalProxyVersion, on_delete=models.PROTECT, related_name='scopes')
    step = models.ForeignKey('clinical.TreatmentStep', on_delete=models.PROTECT)
    class Meta:
        db_table = 'adc_medical_proxy_scope'
        constraints = [models.UniqueConstraint(fields=['version','step'], name='medical_proxy_step_scope')]


class MedicalProxyEvent(models.Model):
    proxy = models.ForeignKey(MedicalProxy, on_delete=models.PROTECT, related_name='events')
    version = models.ForeignKey(MedicalProxyVersion, on_delete=models.PROTECT)
    sequence = models.PositiveIntegerField()
    action = models.CharField(max_length=20)
    resulting_state = models.CharField(max_length=16)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reviewer = models.ForeignKey('clinical.ClinicalReviewerAppointment', null=True, blank=True, on_delete=models.PROTECT)
    note = models.CharField(max_length=1000)
    operation_id = models.UUIDField(unique=True)
    recorded_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'adc_medical_proxy_event'
        constraints = [models.UniqueConstraint(fields=['proxy','sequence'], name='medical_proxy_event_order')]
