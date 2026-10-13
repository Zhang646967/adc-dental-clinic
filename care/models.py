"""Physical structures for I1b/I2. v0.5 adds bounded correction services; published records remain immutable."""
from django.db import models
from django.db.models import F, Q
from adc_core.identifiers import invoice_no

class CorrectionRequest(models.Model):
    visit = models.ForeignKey("scheduling.Visit", on_delete=models.PROTECT)
    kind = models.CharField(max_length=24, choices=[("APPOINTMENT_STATUS", "预约结果"), ("RECORD_CONTENT", "治疗内容")])
    base_record_version = models.ForeignKey("care.VisitRecordVersion", on_delete=models.PROTECT, null=True, blank=True, related_name="based_corrections")
    expected_visit_lock_version = models.PositiveIntegerField()
    requester = models.ForeignKey("accounts.UserAccount", on_delete=models.PROTECT, related_name="requested_corrections")
    reviewer = models.ForeignKey("accounts.UserAccount", on_delete=models.PROTECT, null=True, blank=True, related_name="reviewed_corrections")
    dentist_confirmed_by = models.ForeignKey("accounts.UserAccount", on_delete=models.PROTECT, null=True, blank=True, related_name="confirmed_corrections")
    status = models.CharField(max_length=12, default="OPEN", choices=[("OPEN", "待审核"), ("APPLIED", "已应用"), ("REJECTED", "已拒绝"), ("WITHDRAWN", "已撤回")])
    reason = models.TextField()
    proposed_change = models.JSONField(default=dict)
    requested_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        db_table = "adc_correction_request"
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["APPOINTMENT_STATUS", "RECORD_CONTENT"]), name="correction_kind_valid"),
            models.CheckConstraint(condition=Q(status__in=["OPEN", "APPLIED", "REJECTED", "WITHDRAWN"]), name="correction_status_valid"),
            models.CheckConstraint(condition=~Q(requester=F("reviewer")), name="correction_no_self_approval"),
            models.CheckConstraint(condition=(Q(kind="APPOINTMENT_STATUS", base_record_version__isnull=True) | Q(kind="RECORD_CONTENT", base_record_version__isnull=False)), name="correction_base_required"),
            models.CheckConstraint(condition=(Q(status="APPLIED", reviewer__isnull=False, applied_at__isnull=False) | (~Q(status="APPLIED") & Q(applied_at__isnull=True))), name="correction_applied_metadata"),
            models.UniqueConstraint(fields=["visit"], condition=Q(status="OPEN"), name="one_open_correction_per_visit"),
        ]

class VisitRecordVersion(models.Model):
    visit = models.ForeignKey("scheduling.Visit", on_delete=models.PROTECT, related_name="record_versions")
    revision_no = models.PositiveIntegerField()
    state = models.CharField(max_length=12, default="DRAFT", choices=[("DRAFT", "草稿"), ("PUBLISHED", "已发布"), ("ABANDONED", "已弃用")])
    outcome = models.CharField(max_length=16, choices=[("TREATED", "有治疗"), ("NO_TREATMENT", "无治疗")])
    previous_version = models.ForeignKey("care.VisitRecordVersion", on_delete=models.PROTECT, null=True, blank=True, related_name="next_versions")
    correction_request = models.OneToOneField("care.CorrectionRequest", on_delete=models.PROTECT, null=True, blank=True, related_name="new_version")
    prepared_by = models.ForeignKey("accounts.UserAccount", on_delete=models.PROTECT, related_name="prepared_versions")
    reviewed_by = models.ForeignKey("accounts.UserAccount", on_delete=models.PROTECT, null=True, blank=True, related_name="reviewed_versions")
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    allergy_review_snapshot = models.JSONField(default=dict)
    billing_header_snapshot = models.JSONField(default=dict)
    clinical_note = models.TextField(blank=True, default="")
    no_treatment_reason = models.TextField(blank=True, default="")
    total_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="CNY")
    class Meta:
        db_table = "adc_visit_record_version"
        constraints = [
            models.UniqueConstraint(fields=["visit", "revision_no"], name="visit_revision_unique"),
            models.UniqueConstraint(fields=["id", "visit"], name="version_id_visit_unique"),
            models.UniqueConstraint(fields=["visit"], condition=Q(state="DRAFT"), name="one_draft_per_visit"),
            models.CheckConstraint(condition=Q(revision_no__gte=1), name="revision_positive"),
            models.CheckConstraint(condition=Q(state__in=["DRAFT", "PUBLISHED", "ABANDONED"]), name="version_state_valid"),
            models.CheckConstraint(condition=Q(outcome__in=["TREATED", "NO_TREATMENT"]), name="version_outcome_valid"),
            models.CheckConstraint(condition=Q(total_amount__gte=0, currency="CNY"), name="version_money_valid"),
            models.CheckConstraint(condition=(Q(state="PUBLISHED", published_at__isnull=False) | (~Q(state="PUBLISHED") & Q(published_at__isnull=True))), name="version_publish_metadata"),
            models.CheckConstraint(condition=~Q(previous_version=F("id")), name="version_not_previous_self"),
        ]

class TreatmentRecord(models.Model):
    record_version = models.ForeignKey("care.VisitRecordVersion", on_delete=models.PROTECT, related_name="treatment_lines")
    line_no = models.PositiveIntegerField()
    treatment_type = models.ForeignKey("registry.TreatmentType", on_delete=models.PROTECT)
    name_snapshot = models.CharField(max_length=120)
    unit_snapshot = models.CharField(max_length=120)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_amount = models.DecimalField(max_digits=16, decimal_places=2)
    confirmed_by = models.ForeignKey("accounts.UserAccount", on_delete=models.PROTECT, null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    price_reason = models.CharField(max_length=500, blank=True, default="")
    class Meta:
        db_table = "adc_treatment_record"
        ordering = ["line_no"]
        constraints = [
            models.UniqueConstraint(fields=["record_version", "line_no"], name="record_line_unique"),
            models.CheckConstraint(condition=Q(line_no__gte=1, quantity__gt=0, unit_price__gte=0, line_amount__gte=0), name="record_values_valid"),
            models.CheckConstraint(condition=Q(unit_price__gt=0) | ~Q(price_reason=""), name="zero_price_reason_required"),
            models.CheckConstraint(condition=(Q(confirmed_by__isnull=True, confirmed_at__isnull=True) | Q(confirmed_by__isnull=False, confirmed_at__isnull=False)), name="line_confirmation_consistent"),
        ]

class Invoice(models.Model):
    invoice_no = models.CharField(max_length=40, unique=True, default=invoice_no, editable=False)
    visit = models.OneToOneField("scheduling.Visit", on_delete=models.PROTECT, related_name="invoice")
    current_record_version = models.OneToOneField("care.VisitRecordVersion", on_delete=models.PROTECT, related_name="current_invoice")
    first_issued_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = "adc_invoice"

class AuditEvent(models.Model):
    actor = models.ForeignKey("accounts.UserAccount", on_delete=models.PROTECT, null=True, blank=True)
    visit = models.ForeignKey("scheduling.Visit", on_delete=models.PROTECT, null=True, blank=True, related_name="events")
    correction_request = models.ForeignKey("care.CorrectionRequest", on_delete=models.PROTECT, null=True, blank=True)
    event_type = models.CharField(max_length=48)
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)
    subject_type = models.CharField(max_length=32)
    subject_key = models.CharField(max_length=80)
    reason = models.CharField(max_length=500, blank=True, default="")
    change_summary = models.JSONField(default=dict)
    class Meta:
        db_table = "adc_audit_event"
        indexes = [models.Index(fields=["subject_type", "subject_key", "recorded_at"], name="audit_subject_time_idx")]
