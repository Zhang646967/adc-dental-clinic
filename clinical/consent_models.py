"""Concrete medical decisions; scheme preference remains in PlanDecision."""
from django.conf import settings
from django.db import models
from django.db.models import Q


class MedicalConsent(models.Model):
    step = models.OneToOneField('clinical.TreatmentStep', on_delete=models.PROTECT, related_name='medical_consent')
    revision = models.PositiveIntegerField(default=0)
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    opened_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_medical_consent'


class ConsentVersion(models.Model):
    consent = models.ForeignKey(MedicalConsent, on_delete=models.PROTECT, related_name='versions')
    revision = models.PositiveIntegerField()
    previous = models.OneToOneField('self', null=True, blank=True, on_delete=models.PROTECT, related_name='next_version')
    step_version = models.ForeignKey('clinical.PlanStepVersion', on_delete=models.PROTECT)
    source_record = models.ForeignKey('clinical.ClinicalRecordVersion', on_delete=models.PROTECT)
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    identity_reference = models.CharField(max_length=500)
    patient_snapshot = models.JSONField()
    scope_digest = models.CharField(max_length=64)
    amendment_reason = models.CharField(max_length=500, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_consent_version'
        constraints = [models.UniqueConstraint(fields=['consent', 'revision'], name='consent_version_number'),
                       models.CheckConstraint(condition=Q(revision__gte=1), name='consent_version_positive')]


class ConsentEvent(models.Model):
    ACTIONS = [('PUBLISHED', '医师告知确认'), ('QUESTION', '本人提问'), ('ANSWER', '医师答复'),
               ('AGREED', '本人同意'), ('DECLINED', '本人拒绝'), ('DEFERRED', '本人暂缓'), ('WITHDRAWN', '撤回同意')]
    SOURCES = [('DOCTOR_ACCOUNT', '医师账号记录'), ('SELF_ACCOUNT', '患者本人账号确认'),
               ('PAPER_REFERENCE', '纸质原件决定登记')]
    consent = models.ForeignKey(MedicalConsent, on_delete=models.PROTECT, related_name='events')
    version = models.ForeignKey(ConsentVersion, on_delete=models.PROTECT, related_name='events')
    sequence = models.PositiveIntegerField()
    operation_id = models.UUIDField(unique=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    self_access = models.ForeignKey('portal.PatientAccess', null=True, blank=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=12, choices=ACTIONS)
    source = models.CharField(max_length=20, choices=SOURCES)
    text = models.CharField(max_length=2000, blank=True)
    reference = models.CharField(max_length=500, blank=True)
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)
    reply_to = models.OneToOneField('self', null=True, blank=True, on_delete=models.PROTECT, related_name='answer')

    class Meta:
        db_table = 'adc_consent_event'
        constraints = [models.UniqueConstraint(fields=['consent', 'sequence'], name='consent_event_sequence'),
            models.CheckConstraint(condition=Q(sequence__gte=1), name='consent_event_positive'),
            models.CheckConstraint(condition=Q(action__in=['PUBLISHED', 'QUESTION', 'ANSWER', 'AGREED', 'DECLINED', 'DEFERRED', 'WITHDRAWN']), name='consent_event_action'),
            models.CheckConstraint(condition=Q(source__in=['DOCTOR_ACCOUNT', 'SELF_ACCOUNT', 'PAPER_REFERENCE']), name='consent_event_source'),
            models.CheckConstraint(condition=Q(source='SELF_ACCOUNT', self_access__isnull=False) | (~Q(source='SELF_ACCOUNT') & Q(self_access__isnull=True)), name='consent_self_basis')]
