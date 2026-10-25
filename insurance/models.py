"""Versioned policy facts and explicitly synthetic eligibility, separate from cash."""
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, RangeOperators
from django.db import models
from django.db.models import F, Q, Value

STATES = [('DRAFT', '待独立核对'), ('CONFIRMED', '已核对启用'),
          ('REJECTED', '未通过'), ('DISABLED', '已停用，历史保留')]
CLASSES = [('A', '甲类'), ('B', '乙类'), ('NOT_PAYABLE', '不支付'), ('UNKNOWN', '原表未知')]
SCHEMES = [('EMPLOYEE', '职工医保（模拟）'), ('RESIDENT', '居民医保（模拟）'), ('UNKNOWN', '类型待核实')]
ELIGIBILITY_STATES = [('VERIFIED', '模拟待遇已核对'), ('NOT_ELIGIBLE', '本次无适用待遇'), ('UNKNOWN', '待核实')]


class InclusiveDates(models.Func):
    function = 'DATERANGE'
    output_field = DateRangeField()


class ReviewedPreparation(models.Model):
    state = models.CharField(max_length=12, choices=STATES, default='DRAFT')
    revision = models.PositiveIntegerField(default=0)
    prepared_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='+')
    prepared_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='+', null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(condition=Q(state__in=[s for s, _ in STATES]), name='%(class)s_state'),
            models.CheckConstraint(condition=Q(reviewed_by__isnull=True) | ~Q(prepared_by=F('reviewed_by')), name='%(class)s_independent'),
            models.CheckConstraint(condition=Q(state='DRAFT', reviewed_by__isnull=True, reviewed_at__isnull=True, review_reason='', revision=0) |
                (Q(state__in=['CONFIRMED', 'REJECTED', 'DISABLED'], reviewed_by__isnull=False, reviewed_at__isnull=False, revision__gte=1) & ~Q(review_reason='')),
                name='%(class)s_review_metadata'),
        ]


class PolicyCatalogue(ReviewedPreparation):
    region = models.CharField(max_length=8)
    version_code = models.CharField(max_length=40)
    notice = models.CharField(max_length=120)
    effective_on = models.DateField()
    source_url = models.URLField(max_length=500)
    attachment_url = models.URLField(max_length=500)
    source_format = models.CharField(max_length=24)
    parser_version = models.CharField(max_length=32)
    source_digest = models.CharField(max_length=64, db_index=True)
    review_attempt = models.PositiveIntegerField(default=1)
    previous = models.OneToOneField('self', on_delete=models.PROTECT, null=True, blank=True, related_name='next_review')
    normalized_digest = models.CharField(max_length=64)
    original_bytes = models.BinaryField()
    normalized_rows = models.JSONField()
    source_summary = models.JSONField()

    class Meta(ReviewedPreparation.Meta):
        abstract = False
        db_table = 'adc_insurance_catalogue'
        constraints = ReviewedPreparation.Meta.constraints + [
            models.UniqueConstraint(fields=['region', 'version_code', 'review_attempt'], name='insurance_policy_version_review'),
            models.UniqueConstraint(fields=['source_digest', 'review_attempt'], name='insurance_policy_source_review'),
            models.UniqueConstraint(fields=['source_digest'], condition=Q(previous__isnull=True), name='insurance_policy_one_origin'),
            models.UniqueConstraint(fields=['source_digest'], condition=Q(state__in=['DRAFT', 'CONFIRMED']), name='insurance_policy_one_live'),
            models.CheckConstraint(condition=Q(review_attempt=1, previous__isnull=True) | Q(review_attempt__gte=2, previous__isnull=False), name='insurance_policy_review_chain'),
        ]

    def __str__(self):
        return f'{self.notice} · 第{self.review_attempt}次核对'


class PolicyItem(models.Model):
    catalogue = models.ForeignKey(PolicyCatalogue, on_delete=models.PROTECT, related_name='items')
    code = models.CharField(max_length=15)
    name = models.CharField(max_length=160)
    unit = models.CharField(max_length=120, null=True, blank=True)
    payment_class = models.CharField(max_length=16, choices=CLASSES)
    pre_self_pay_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    review_state = models.CharField(max_length=24)
    source_rows = models.JSONField()
    raw_cells = models.JSONField()

    class Meta:
        db_table = 'adc_insurance_policy_item'
        constraints = [
            models.UniqueConstraint(fields=['catalogue', 'code'], name='insurance_policy_code'),
            models.CheckConstraint(condition=Q(payment_class__in=[s for s, _ in CLASSES]), name='insurance_policy_class'),
            models.CheckConstraint(condition=Q(pre_self_pay_percent__isnull=True) | Q(pre_self_pay_percent__gte=0, pre_self_pay_percent__lte=100), name='insurance_policy_share'),
        ]

    def __str__(self):
        return f'{self.code} · {self.name}'


class ClinicArrangement(ReviewedPreparation):
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    catalogue = models.ForeignKey(PolicyCatalogue, on_delete=models.PROTECT)
    starts_on = models.DateField()
    ends_on = models.DateField()
    reference = models.CharField(max_length=80)

    class Meta(ReviewedPreparation.Meta):
        abstract = False
        db_table = 'adc_insurance_arrangement'
        constraints = ReviewedPreparation.Meta.constraints + [
            models.CheckConstraint(condition=Q(ends_on__gte=F('starts_on')), name='insurance_arrangement_dates'),
            ExclusionConstraint(name='insurance_arrangement_no_overlap', expressions=[('clinic', RangeOperators.EQUAL),
                (InclusiveDates('starts_on', 'ends_on', Value('[]')), RangeOperators.OVERLAPS)], condition=Q(state='CONFIRMED')),
        ]


class FeeMapping(ReviewedPreparation):
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    treatment_type = models.ForeignKey('registry.TreatmentType', on_delete=models.PROTECT)
    policy_item = models.ForeignKey(PolicyItem, on_delete=models.PROTECT)
    fee_snapshot = models.JSONField()
    policy_units_per_fee = models.DecimalField(max_digits=12, decimal_places=4)
    compatibility_basis = models.CharField(max_length=500)

    class Meta(ReviewedPreparation.Meta):
        abstract = False
        db_table = 'adc_insurance_fee_mapping'
        constraints = ReviewedPreparation.Meta.constraints + [
            models.UniqueConstraint(fields=['clinic', 'treatment_type'], condition=Q(state='CONFIRMED'), name='insurance_one_fee_mapping'),
            models.CheckConstraint(condition=Q(policy_units_per_fee__gt=0), name='insurance_mapping_quantity'),
        ]


class EligibilityFact(models.Model):
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT)
    version = models.PositiveIntegerField()
    previous = models.OneToOneField('self', on_delete=models.PROTECT, null=True, blank=True, related_name='next_version')
    insured_region = models.CharField(max_length=8)
    scheme = models.CharField(max_length=12, choices=SCHEMES)
    state = models.CharField(max_length=16, choices=ELIGIBILITY_STATES)
    starts_on = models.DateField()
    ends_on = models.DateField()
    reference = models.CharField(max_length=80)
    basis = models.CharField(max_length=500)
    source = models.CharField(max_length=24, default='LOCAL_SIMULATION', editable=False)
    recorded_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_insurance_eligibility'
        indexes = [models.Index(fields=['clinic', 'patient', '-version'], name='insurance_eligibility_latest')]
        constraints = [
            models.UniqueConstraint(fields=['clinic', 'patient', 'version'], name='insurance_eligibility_version'),
            models.CheckConstraint(condition=Q(version__gte=1, ends_on__gte=F('starts_on'), source='LOCAL_SIMULATION'), name='insurance_eligibility_facts'),
            models.CheckConstraint(condition=Q(scheme__in=[s for s, _ in SCHEMES], state__in=[s for s, _ in ELIGIBILITY_STATES]), name='insurance_eligibility_values'),
            models.CheckConstraint(condition=Q(version=1, previous__isnull=True) | Q(version__gte=2, previous__isnull=False), name='insurance_eligibility_chain'),
        ]


class InsuranceEvent(models.Model):
    catalogue = models.ForeignKey(PolicyCatalogue, on_delete=models.PROTECT, null=True, blank=True, related_name='events')
    arrangement = models.ForeignKey(ClinicArrangement, on_delete=models.PROTECT, null=True, blank=True, related_name='events')
    mapping = models.ForeignKey(FeeMapping, on_delete=models.PROTECT, null=True, blank=True, related_name='events')
    eligibility = models.ForeignKey(EligibilityFact, on_delete=models.PROTECT, null=True, blank=True, related_name='events')
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    operation_id = models.UUIDField(unique=True)
    action = models.CharField(max_length=24)
    reason = models.CharField(max_length=500)
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_insurance_event'
        constraints = [models.CheckConstraint(condition=
            Q(catalogue__isnull=False, arrangement__isnull=True, mapping__isnull=True, eligibility__isnull=True) |
            Q(catalogue__isnull=True, arrangement__isnull=False, mapping__isnull=True, eligibility__isnull=True) |
            Q(catalogue__isnull=True, arrangement__isnull=True, mapping__isnull=False, eligibility__isnull=True) |
            Q(catalogue__isnull=True, arrangement__isnull=True, mapping__isnull=True, eligibility__isnull=False), name='insurance_event_one_subject')]


# C6.1B private staging; not yet accepted or installed.
from insurance.settlement_models import (SettlementRequest, SettlementLine, SimulationOutcome, SettlementReview, SettlementEvent)
from insurance.cancellation_models import CancellationRequest, ReversalOutcome, CancellationReview
