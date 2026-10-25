"""Retained bank-to-claim allocations and accountable fund discrepancies."""
import uuid
from django.db import models
from django.db.models import F, Q


class FundAllocation(models.Model):
    transfer = models.ForeignKey('finance.FundTransfer', on_delete=models.PROTECT, related_name='allocations')
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    state = models.CharField(max_length=12, default='PENDING', choices=[
        ('PENDING', '待独立复核'), ('CONFIRMED', '分配已核对'), ('REJECTED', '分配未通过')])
    total = models.DecimalField(max_digits=16, decimal_places=2)
    source_snapshot = models.JSONField()
    source_digest = models.CharField(max_length=64)
    basis = models.CharField(max_length=500)
    prepared_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='fund_allocations_prepared')
    prepared_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='fund_allocations_reviewed')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        db_table = 'adc_fund_allocation'
        constraints = [
            models.CheckConstraint(condition=Q(total__gt=0), name='fund_allocation_positive'),
            models.CheckConstraint(condition=Q(state='PENDING', reviewed_by__isnull=True, reviewed_at__isnull=True, review_reason='') |
                (Q(state__in=['CONFIRMED', 'REJECTED'], reviewed_by__isnull=False, reviewed_at__isnull=False) & ~Q(review_reason='')),
                name='fund_allocation_review_metadata'),
            models.CheckConstraint(condition=Q(reviewed_by__isnull=True) | ~Q(prepared_by=F('reviewed_by')),
                name='fund_allocation_independent'),
        ]


class FundAllocationLine(models.Model):
    allocation = models.ForeignKey(FundAllocation, on_delete=models.PROTECT, related_name='lines')
    claim = models.ForeignKey('insurance.SettlementRequest', on_delete=models.PROTECT, related_name='fund_allocations')
    amount = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        db_table = 'adc_fund_allocation_line'
        constraints = [
            models.UniqueConstraint(fields=['allocation', 'claim'], name='fund_allocation_once_per_claim'),
            models.CheckConstraint(condition=Q(amount__gt=0), name='fund_allocation_line_positive'),
        ]


class FundIssue(models.Model):
    claim = models.ForeignKey('insurance.SettlementRequest', on_delete=models.PROTECT, related_name='fund_issues')
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    kind = models.CharField(max_length=16, choices=[
        ('NOT_RECEIVED', '未到账'), ('SHORTFALL', '少到账'), ('DEDUCTION', '扣减待核对'), ('UNKNOWN', '用途或结果待核实')])
    amount = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    opened_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    opened_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_fund_issue'
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=['NOT_RECEIVED', 'SHORTFALL', 'DEDUCTION', 'UNKNOWN']), name='fund_issue_kind'),
            models.CheckConstraint(condition=Q(amount__isnull=True) | Q(amount__gte=0), name='fund_issue_amount'),
        ]


class FundIssueEvent(models.Model):
    issue = models.ForeignKey(FundIssue, on_delete=models.PROTECT, related_name='events')
    sequence = models.PositiveIntegerField()
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    state = models.CharField(max_length=8, choices=[('OPEN', '待跟进'), ('CLOSED', '跟进已结束')])
    owner = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='fund_followups')
    due_at = models.DateTimeField()
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='fund_followup_actions')
    basis = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_fund_issue_event'
        constraints = [
            models.UniqueConstraint(fields=['issue', 'sequence'], name='fund_issue_event_sequence'),
            models.CheckConstraint(condition=Q(sequence__gte=1, state__in=['OPEN', 'CLOSED']), name='fund_issue_event_state'),
        ]
