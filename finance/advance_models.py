"""Reviewed applications of retained patient receipts to published invoices."""
import uuid

from django.db import models
from django.db.models import F, Q


class AdvanceAllocation(models.Model):
    receipt = models.ForeignKey('finance.CashEntry', on_delete=models.PROTECT, related_name='allocations')
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    state = models.CharField(max_length=12, default='PENDING', choices=[
        ('PENDING', '待财务复核'), ('POSTED', '已抵扣'), ('REJECTED', '已拒绝')])
    total = models.DecimalField(max_digits=16, decimal_places=2)
    available_at_request = models.DecimalField(max_digits=16, decimal_places=2)
    basis = models.CharField(max_length=500)
    prepared_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT,
                                    related_name='advance_allocations_prepared')
    prepared_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='advance_allocations_reviewed')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=500, blank=True, default='')
    review_operation_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)

    class Meta:
        db_table = 'adc_advance_allocation'
        indexes = [
            models.Index(fields=['receipt', 'state'], name='advance_alloc_receipt_idx'),
            models.Index(fields=['state', '-id'], name='advance_alloc_queue_idx'),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(total__gt=0, total__lte=F('available_at_request')),
                                   name='advance_alloc_request_amount'),
            models.CheckConstraint(condition=(
                Q(state='PENDING', reviewed_by__isnull=True, reviewed_at__isnull=True,
                  review_operation_id__isnull=True, review_reason='') |
                (Q(state__in=['POSTED', 'REJECTED'], reviewed_by__isnull=False,
                   reviewed_at__gte=F('prepared_at'), review_operation_id__isnull=False)
                 & Q(reviewed_at__isnull=False) & ~Q(review_reason=''))),
                name='advance_alloc_review_metadata'),
            models.CheckConstraint(condition=Q(reviewed_by__isnull=True) | ~Q(prepared_by=F('reviewed_by')),
                                   name='advance_alloc_independent'),
        ]


class AdvanceAllocationLine(models.Model):
    allocation = models.ForeignKey(AdvanceAllocation, on_delete=models.PROTECT, related_name='lines')
    invoice = models.ForeignKey('care.Invoice', on_delete=models.PROTECT, related_name='advance_allocations')
    record_version = models.ForeignKey('care.VisitRecordVersion', on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    responsibility = models.DecimalField(max_digits=16, decimal_places=2)
    due_at_request = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        db_table = 'adc_advance_allocation_line'
        constraints = [
            models.UniqueConstraint(fields=['allocation', 'invoice'], name='advance_alloc_once_per_bill'),
            models.CheckConstraint(condition=Q(amount__gt=0, amount__lte=F('due_at_request'),
                                               due_at_request__lte=F('responsibility')),
                                   name='advance_alloc_line_amount'),
        ]


class AdvanceAllocationReversal(models.Model):
    line = models.ForeignKey(AdvanceAllocationLine, on_delete=models.PROTECT, related_name='reversals')
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    state = models.CharField(max_length=12, default='PENDING', choices=[
        ('PENDING', '待财务复核'), ('POSTED', '已撤销抵扣'), ('REJECTED', '已拒绝')])
    basis = models.CharField(max_length=500)
    prepared_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT,
                                    related_name='advance_reversals_prepared')
    prepared_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='advance_reversals_reviewed')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=500, blank=True, default='')
    review_operation_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)

    class Meta:
        db_table = 'adc_advance_allocation_reversal'
        indexes = [models.Index(fields=['state', '-id'], name='advance_reverse_queue_idx')]
        constraints = [
            models.UniqueConstraint(fields=['line'], condition=Q(state__in=['PENDING', 'POSTED']),
                                    name='advance_reverse_one_live_line'),
            models.CheckConstraint(condition=(
                Q(state='PENDING', reviewed_by__isnull=True, reviewed_at__isnull=True,
                  review_operation_id__isnull=True, review_reason='') |
                (Q(state__in=['POSTED', 'REJECTED'], reviewed_by__isnull=False, reviewed_at__isnull=False,
                   reviewed_at__gte=F('prepared_at'), review_operation_id__isnull=False)
                 & Q(reviewed_at__isnull=False) & ~Q(review_reason=''))), name='advance_reverse_review_metadata'),
            models.CheckConstraint(condition=Q(reviewed_by__isnull=True) | ~Q(prepared_by=F('reviewed_by')),
                                   name='advance_reverse_independent'),
        ]
