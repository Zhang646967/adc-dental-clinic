"""C6.1B staging: retained synthetic requests/results, separate from actual cash."""
import uuid
from django.db import models
from django.db.models import F, Q

SETTLEMENT_STATES = [
    ('PROCESSING', '模拟处理中'), ('UNKNOWN', '回复未知，查询原请求'),
    ('AWAITING_REVIEW', '结果已取得，待独立核对'), ('CONFIRMED', '分担已独立核对'),
    ('REVIEW_REJECTED', '复核未通过，待处置原请求'), ('DECLINED', '模拟结算未受理'),
    ('CANCEL_PENDING', '撤销处置中'), ('CANCELLED', '已完成撤销'),
]
ACTIVE_SETTLEMENT_STATES = tuple(s for s, _ in SETTLEMENT_STATES if s not in ('DECLINED', 'CANCELLED'))
CREDIT_STATES = ('CONFIRMED', 'CANCEL_PENDING')
SIMULATION_MODES = [
    ('ACCEPT', '正常返回合成结果'), ('LOST_SUCCESS', '模拟成功但回复丢失'),
    ('PROCESSING', '模拟先返回处理中'), ('DECLINE', '模拟未受理'),
]


class SettlementRequest(models.Model):
    request_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    operation_id = models.UUIDField(unique=True, editable=False)
    invoice = models.ForeignKey('care.Invoice', on_delete=models.PROTECT, related_name='insurance_requests')
    record_version = models.ForeignKey('care.VisitRecordVersion', on_delete=models.PROTECT)
    arrangement = models.ForeignKey('insurance.ClinicArrangement', on_delete=models.PROTECT)
    eligibility = models.ForeignKey('insurance.EligibilityFact', on_delete=models.PROTECT)
    service_on = models.DateField()
    currency = models.CharField(max_length=3, default='CNY')
    gross_amount = models.DecimalField(max_digits=16, decimal_places=2)
    patient_cash = models.DecimalField(max_digits=16, decimal_places=2)
    personal_account = models.DecimalField(max_digits=16, decimal_places=2)
    fund_amount = models.DecimalField(max_digits=16, decimal_places=2)
    source_snapshot = models.JSONField()
    source_digest = models.CharField(max_length=64)
    simulation_mode = models.CharField(max_length=16, choices=SIMULATION_MODES)
    state = models.CharField(max_length=24, choices=SETTLEMENT_STATES)
    lock_version = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='insurance_requests_created')
    created_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=500)

    class Meta:
        db_table = 'adc_insurance_settlement'
        constraints = [
            models.UniqueConstraint(fields=['invoice'], condition=Q(state__in=ACTIVE_SETTLEMENT_STATES), name='insurance_one_active_settlement'),
            models.CheckConstraint(condition=Q(state__in=[s for s, _ in SETTLEMENT_STATES]), name='insurance_settlement_state'),
            models.CheckConstraint(condition=Q(currency='CNY'), name='insurance_settlement_cny'),
            models.CheckConstraint(condition=Q(gross_amount__gt=0, patient_cash__gte=0, personal_account__gte=0, fund_amount__gte=0)
                & Q(gross_amount=F('patient_cash') + F('personal_account') + F('fund_amount')), name='insurance_settlement_split'),
            models.CheckConstraint(condition=Q(simulation_mode__in=[s for s, _ in SIMULATION_MODES]), name='insurance_simulation_mode'),
        ]


class SettlementLine(models.Model):
    request = models.ForeignKey(SettlementRequest, on_delete=models.PROTECT, related_name='lines')
    treatment_record = models.ForeignKey('care.TreatmentRecord', on_delete=models.PROTECT)
    line_no = models.PositiveIntegerField()
    mapping = models.ForeignKey('insurance.FeeMapping', on_delete=models.PROTECT, null=True, blank=True)
    source_snapshot = models.JSONField()
    policy_quantity = models.DecimalField(max_digits=24, decimal_places=7, null=True, blank=True)
    fund_limit = models.DecimalField(max_digits=16, decimal_places=2)
    gross_amount = models.DecimalField(max_digits=16, decimal_places=2)
    patient_cash = models.DecimalField(max_digits=16, decimal_places=2)
    personal_account = models.DecimalField(max_digits=16, decimal_places=2)
    fund_amount = models.DecimalField(max_digits=16, decimal_places=2)
    exception = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        db_table = 'adc_insurance_settlement_line'
        constraints = [
            models.UniqueConstraint(fields=['request', 'treatment_record'], name='insurance_settlement_source_line'),
            models.UniqueConstraint(fields=['request', 'line_no'], name='insurance_settlement_line_no'),
            models.CheckConstraint(condition=Q(line_no__gte=1, gross_amount__gte=0, patient_cash__gte=0, personal_account__gte=0,
                fund_amount__gte=0, fund_limit__gte=0, fund_amount__lte=F('fund_limit'))
                & Q(gross_amount=F('patient_cash') + F('personal_account') + F('fund_amount')), name='insurance_line_split'),
            models.CheckConstraint(condition=Q(policy_quantity__isnull=True) | Q(policy_quantity__gt=0), name='insurance_line_quantity'),
        ]


class SimulationOutcome(models.Model):
    request = models.OneToOneField(SettlementRequest, on_delete=models.PROTECT, related_name='simulation_outcome')
    reference = models.CharField(max_length=80, unique=True)
    request_digest = models.CharField(max_length=64)
    result = models.CharField(max_length=12, choices=[('ACCEPTED', '模拟已受理'), ('DECLINED', '模拟未受理')])
    payload = models.JSONField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_insurance_simulation'
        constraints = [models.CheckConstraint(condition=Q(result__in=['ACCEPTED', 'DECLINED']), name='insurance_simulation_result')]


class SettlementReview(models.Model):
    request = models.OneToOneField(SettlementRequest, on_delete=models.PROTECT, related_name='review')
    operation_id = models.UUIDField(unique=True, editable=False)
    reviewed_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    decision = models.CharField(max_length=8, choices=[('APPROVE', '分担核对通过'), ('REJECT', '分担核对未通过')])
    reason = models.CharField(max_length=500)
    source_digest = models.CharField(max_length=64)
    reviewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_insurance_settlement_review'
        constraints = [models.CheckConstraint(condition=Q(decision__in=['APPROVE', 'REJECT']), name='insurance_settlement_review')]


class SettlementEvent(models.Model):
    request = models.ForeignKey(SettlementRequest, on_delete=models.PROTECT, related_name='events')
    sequence = models.PositiveIntegerField()
    operation_id = models.UUIDField(unique=True, editable=False)
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    action = models.CharField(max_length=32)
    snapshot = models.JSONField()
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_insurance_settlement_event'
        constraints = [
            models.UniqueConstraint(fields=['request', 'sequence'], name='insurance_settlement_event_seq'),
            models.CheckConstraint(condition=Q(sequence__gte=1), name='insurance_settlement_event_order'),
        ]
