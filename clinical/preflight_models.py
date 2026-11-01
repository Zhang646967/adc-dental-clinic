"""Retained clinical rules, pre-treatment checks and honest historical gaps."""
from django.conf import settings
from django.db import models
from django.db.models import Q


class TreatmentControlPolicy(models.Model):
    clinic = models.OneToOneField('registry.Clinic', on_delete=models.PROTECT)
    activated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reference = models.CharField(max_length=500)
    activated_at = models.DateTimeField(auto_now_add=True)
    class Meta: db_table = 'adc_treatment_control_policy'


class ClinicalConsentRule(models.Model):
    operation_id = models.UUIDField(unique=True)
    MODES = [('CONSENT','须取得具体医疗同意'),('COMMUNICATION','完成沟通记录'),('REVIEW','需进一步专业判断')]
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    treatment_type = models.ForeignKey('registry.TreatmentType', on_delete=models.PROTECT)
    number = models.PositiveIntegerField()
    mode = models.CharField(max_length=16, choices=MODES)
    reference = models.CharField(max_length=500)
    explanation = models.CharField(max_length=1000)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reviewer = models.ForeignKey('clinical.ClinicalReviewerAppointment', on_delete=models.PROTECT)
    published_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'adc_clinical_consent_rule'
        constraints = [models.UniqueConstraint(fields=['clinic','treatment_type','number'], name='clinical_rule_number'), models.CheckConstraint(condition=Q(mode__in=['CONSENT','COMMUNICATION','REVIEW']), name='clinical_rule_mode')]


class TreatmentPreflight(models.Model):
    visit = models.ForeignKey('scheduling.Visit', on_delete=models.PROTECT, related_name='preflight_checks')
    source_record = models.ForeignKey('clinical.ClinicalRecordVersion', on_delete=models.PROTECT)
    step_version = models.ForeignKey('clinical.PlanStepVersion', null=True, blank=True, on_delete=models.PROTECT)
    rule = models.ForeignKey(ClinicalConsentRule, on_delete=models.PROTECT)
    consent_version = models.ForeignKey('clinical.ConsentVersion', null=True, blank=True, on_delete=models.PROTECT)
    consent_decision = models.ForeignKey('clinical.ConsentEvent', null=True, blank=True, on_delete=models.PROTECT)
    proxy_version = models.ForeignKey('portal.MedicalProxyVersion', null=True, blank=True, on_delete=models.PROTECT)
    snapshot = models.JSONField()
    communication = models.CharField(max_length=1000, blank=True)
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    checked_at = models.DateTimeField(auto_now_add=True)
    operation_id = models.UUIDField(unique=True)
    class Meta: db_table = 'adc_treatment_preflight'


class ProcedureGap(models.Model):
    STATES = [('PENDING','待独立医务复核'),('REVIEWED','已复核历史缺口')]
    performed = models.OneToOneField('clinical.PerformedProcedure', on_delete=models.PROTECT, related_name='preflight_gap')
    reason = models.CharField(max_length=1000)
    missing = models.JSONField()
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    recorded_at = models.DateTimeField(auto_now_add=True)
    state = models.CharField(max_length=16, choices=STATES, default='PENDING')
    class Meta:
        db_table = 'adc_procedure_gap'
        constraints = [models.CheckConstraint(condition=Q(state__in=['PENDING','REVIEWED']), name='procedure_gap_state')]


class ProcedureGapReview(models.Model):
    gap = models.OneToOneField(ProcedureGap, on_delete=models.PROTECT, related_name='review')
    reviewer = models.ForeignKey('clinical.ClinicalReviewerAppointment', on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    note = models.CharField(max_length=1000)
    recorded_at = models.DateTimeField(auto_now_add=True)
    operation_id = models.UUIDField(unique=True)
    class Meta: db_table = 'adc_procedure_gap_review'
