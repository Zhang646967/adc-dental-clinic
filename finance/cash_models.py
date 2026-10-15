"""Synthetic cash requests: pending is not posted; posting requires another user."""
import uuid
from django.db import models
from django.db.models import F, Q

KINDS = [('RECEIPT','模拟收款'),('REFUND','模拟退款'),('EQUIPMENT_EXPENSE','设备费用'),('EXPENSE_REVERSAL','设备费用冲回')]
class CashEntry(models.Model):
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    invoice = models.ForeignKey('care.Invoice', on_delete=models.PROTECT, null=True, blank=True, related_name='cash_entries')
    based_record_version = models.ForeignKey('care.VisitRecordVersion', on_delete=models.PROTECT, null=True, blank=True)
    equipment_event = models.ForeignKey('equipment.EquipmentEvent', on_delete=models.PROTECT, null=True, blank=True, related_name='cash_entries')
    equipment_cost_amendment = models.ForeignKey('equipment.EquipmentCostAmendment', on_delete=models.PROTECT, null=True, blank=True)
    reversal_of = models.ForeignKey('finance.CashEntry', on_delete=models.PROTECT, null=True, blank=True, related_name='reversal_requests')
    kind = models.CharField(max_length=24, choices=KINDS)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    occurred_on = models.DateField()
    reason = models.CharField(max_length=500)
    state = models.CharField(max_length=12, choices=[('PENDING','待财务审核'),('POSTED','已记账'),('REJECTED','已拒绝')], default='PENDING')
    lock_version = models.PositiveIntegerField(default=0)
    prepared_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='prepared_cash_entries')
    prepared_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='reviewed_cash_entries')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=500, blank=True)
    class Meta:
        db_table = 'adc_cash_entry'
        ordering = ['-pk']
        indexes = [models.Index(fields=['clinic','state','occurred_on'], name='cash_clinic_state_date_idx')]
        constraints = [
            models.CheckConstraint(condition=Q(equipment_cost_amendment__isnull=True)|Q(equipment_event__isnull=False), name='cash_cost_requires_equipment'),
            models.CheckConstraint(condition=Q(amount__gt=0), name='cash_amount_positive'),
            models.CheckConstraint(condition=Q(kind__in=[k for k,l in KINDS]), name='cash_kind_valid'),
            models.CheckConstraint(condition=Q(state__in=['PENDING','POSTED','REJECTED']), name='cash_state_valid'),
            models.CheckConstraint(condition=~Q(prepared_by=F('reviewed_by')), name='cash_no_self_review'),
            models.CheckConstraint(condition=(
                Q(invoice__isnull=False,based_record_version__isnull=False,equipment_event__isnull=True,kind__in=['RECEIPT','REFUND']) |
                Q(invoice__isnull=True,based_record_version__isnull=True,equipment_event__isnull=False,kind__in=['EQUIPMENT_EXPENSE','EXPENSE_REVERSAL'])), name='cash_exact_source'),
            models.CheckConstraint(condition=(
                Q(state='PENDING',reviewed_by__isnull=True,reviewed_at__isnull=True,lock_version=0) |
                Q(state__in=['POSTED','REJECTED'],reviewed_by__isnull=False,reviewed_at__isnull=False,lock_version=1)), name='cash_review_metadata'),
            models.UniqueConstraint(fields=['reversal_of'],condition=Q(reversal_of__isnull=False,state__in=['PENDING','POSTED']), name='cash_one_live_reversal'),
        ]
