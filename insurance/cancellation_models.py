"""One retained reversal per original synthetic settlement."""
import uuid
from django.db import models
from django.db.models import Q

CANCEL_MODES = [('ACCEPT', '正常返回原撤销结果'), ('LOST_SUCCESS', '撤销成功但回复丢失'), ('PROCESSING', '先返回撤销处理中')]
CANCEL_STATES = [('PROCESSING', '撤销处理中'), ('UNKNOWN', '撤销回复未知'), ('AWAITING_REVIEW', '撤销结果已取得，待独立核对'),
    ('REVIEW_REJECTED', '撤销复核未通过，待继续处置'), ('CONFIRMED', '撤销已独立确认')]


class CancellationRequest(models.Model):
    request = models.OneToOneField('insurance.SettlementRequest', on_delete=models.PROTECT, related_name='cancellation')
    cancellation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    operation_id = models.UUIDField(unique=True, editable=False)
    state = models.CharField(max_length=24, choices=CANCEL_STATES, default='PROCESSING')
    revision = models.PositiveIntegerField(default=0)
    simulation_mode = models.CharField(max_length=16, choices=CANCEL_MODES)
    source_snapshot = models.JSONField()
    source_digest = models.CharField(max_length=64)
    prepared_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    prepared_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=500)

    class Meta:
        db_table = 'adc_insurance_cancellation'
        constraints = [
            models.CheckConstraint(condition=Q(state__in=[s for s, _ in CANCEL_STATES]), name='insurance_cancellation_state'),
            models.CheckConstraint(condition=Q(simulation_mode__in=[s for s, _ in CANCEL_MODES]), name='insurance_cancellation_mode'),
        ]


class ReversalOutcome(models.Model):
    cancellation = models.OneToOneField(CancellationRequest, on_delete=models.PROTECT, related_name='outcome')
    reference = models.CharField(max_length=80, unique=True)
    result = models.CharField(max_length=12, default='REVERSED')
    payload = models.JSONField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_insurance_reversal'
        constraints = [models.CheckConstraint(condition=Q(result='REVERSED'), name='insurance_reversal_result')]


class CancellationReview(models.Model):
    cancellation = models.ForeignKey(CancellationRequest, on_delete=models.PROTECT, related_name='reviews')
    operation_id = models.UUIDField(unique=True, editable=False)
    sequence = models.PositiveIntegerField()
    decision = models.CharField(max_length=8, choices=[('APPROVE', '撤销核对通过'), ('REJECT', '未通过，继续处置')])
    reviewed_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    reviewed_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=500)
    clearance_snapshot = models.JSONField()

    class Meta:
        db_table = 'adc_insurance_cancellation_review'
        constraints = [
            models.UniqueConstraint(fields=['cancellation', 'sequence'], name='insurance_cancellation_review_seq'),
            models.CheckConstraint(condition=Q(sequence__gte=1, decision__in=['APPROVE', 'REJECT']), name='insurance_cancellation_decision'),
            models.UniqueConstraint(fields=['cancellation'], condition=Q(decision='APPROVE'), name='insurance_cancellation_once_approved'),
        ]
