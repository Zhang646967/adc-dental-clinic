"""Outpatient documents reference clinical facts; they never own charges."""
from django.db import models
from django.db.models import F, Q

DOCUMENT_KINDS = [('INITIAL', '初诊病历'), ('FOLLOWUP', '复诊病历')]
EVIDENCE_KINDS = [('ACCOUNT_CONFIRMATION', '医师账号确认（课程验证）'),
                  ('PAPER_REFERENCE', '医师确认并登记纸质原件')]


class ClinicalDocument(models.Model):
    encounter = models.OneToOneField('clinical.ClinicalEncounter', on_delete=models.PROTECT, related_name='document')
    responsible = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    due_at = models.DateTimeField()
    next_action_at = models.DateTimeField(null=True, blank=True)
    review_due_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=0)
    opened_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_clinical_document'
        indexes = [models.Index(fields=['responsible', 'due_at'], name='document_owner_due_idx')]


class ClinicalDocumentDraft(models.Model):
    document = models.OneToOneField(ClinicalDocument, on_delete=models.PROTECT, related_name='draft')
    base_version = models.ForeignKey('clinical.ClinicalDocumentVersion', null=True, blank=True, on_delete=models.PROTECT)
    payload = models.JSONField(default=dict)
    saved_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    saved_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'adc_clinical_document_draft'


class ClinicalDocumentVersion(models.Model):
    document = models.ForeignKey(ClinicalDocument, on_delete=models.PROTECT, related_name='versions')
    revision = models.PositiveIntegerField()
    previous = models.OneToOneField('self', null=True, blank=True, on_delete=models.PROTECT, related_name='next_version')
    prior_visit_version = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='followup_versions')
    source_record = models.ForeignKey('clinical.ClinicalRecordVersion', on_delete=models.PROTECT)
    care_record = models.ForeignKey('care.VisitRecordVersion', null=True, blank=True, on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=DOCUMENT_KINDS)
    content = models.JSONField()
    source_snapshot = models.JSONField()
    source_cursor = models.CharField(max_length=64)
    content_digest = models.CharField(max_length=64)
    confirmed_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    confirmed_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)
    evidence_kind = models.CharField(max_length=24, choices=EVIDENCE_KINDS)
    evidence_reference = models.CharField(max_length=500, blank=True)
    amendment_reason = models.CharField(max_length=500, blank=True)
    late_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = 'adc_clinical_document_version'
        constraints = [
            models.UniqueConstraint(fields=['document', 'revision'], name='document_version_unique'),
            models.CheckConstraint(condition=Q(revision=1, previous__isnull=True) | Q(revision__gt=1, previous__isnull=False), name='document_previous_required'),
            models.CheckConstraint(condition=~Q(previous=F('id')), name='document_not_previous_self'),
            models.CheckConstraint(condition=~Q(prior_visit_version=F('id')), name='document_not_prior_self'),
            models.CheckConstraint(condition=Q(kind__in=['INITIAL', 'FOLLOWUP']), name='document_kind_valid'),
            models.CheckConstraint(condition=Q(previous__isnull=True) | ~Q(amendment_reason=''), name='document_amendment_reason'),
            models.CheckConstraint(condition=Q(evidence_kind='ACCOUNT_CONFIRMATION', evidence_reference='') | (Q(evidence_kind='PAPER_REFERENCE') & ~Q(evidence_reference='')), name='document_evidence_valid'),
            models.CheckConstraint(condition=Q(confirmed_at__lte=F('recorded_at')), name='document_confirmation_time_valid'),
        ]


class ClinicalDocumentEvent(models.Model):
    document = models.ForeignKey(ClinicalDocument, on_delete=models.PROTECT, related_name='events')
    version = models.ForeignKey(ClinicalDocumentVersion, null=True, blank=True, on_delete=models.PROTECT)
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    operation_id = models.UUIDField(unique=True)
    action = models.CharField(max_length=24)
    note = models.CharField(max_length=1000, blank=True)
    snapshot = models.JSONField(default=dict)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_clinical_document_event'
