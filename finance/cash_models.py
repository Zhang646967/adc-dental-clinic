"""Synthetic cash requests: pending is not posted; posting requires another user."""
import uuid
from django.db import models
from django.db.models import F, Q

KINDS = [('RECEIPT','模拟收款'),('REFUND','模拟退款'),('EQUIPMENT_EXPENSE','设备费用'),('EXPENSE_REVERSAL','设备费用冲回')]
class CashEntry(models.Model):
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    invoice = models.ForeignKey('care.Invoice', on_delete=models.PROTECT, null=True, blank=True, related_name='cash_entries')
    advance_patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, null=True, blank=True,
                                        related_name='advance_receipts')
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

    @property
    def source_type(self):
        if self.advance_patient_id:
            return 'advance_refund' if self.kind == 'REFUND' else 'advance'
        return 'invoice' if self.invoice_id else 'equipment'

    @property
    def source_id(self):
        return self.reversal_of_id if self.is_advance_refund else self.advance_patient_id or self.invoice_id or self.equipment_event_id

    @property
    def is_advance_refund(self):
        return bool(self.advance_patient_id and self.kind == 'REFUND')

    @property
    def display_kind(self):
        if self.advance_patient_id:
            return '患者预收原渠道退款' if self.is_advance_refund else '患者预收款'
        return self.get_kind_display()

    class Meta:
        db_table = 'adc_cash_entry'
        ordering = ['-pk']
        indexes = [models.Index(fields=["clinic","occurred_on"],name="cash_clinic_day_idx"),models.Index(fields=['clinic','state','occurred_on'], name='cash_clinic_state_date_idx'),
                   models.Index(fields=['clinic', 'advance_patient', 'state'], condition=Q(advance_patient__isnull=False),
                                name='cash_advance_clinic_state_idx')]
        constraints = [
            models.CheckConstraint(condition=Q(equipment_cost_amendment__isnull=True)|Q(equipment_event__isnull=False), name='cash_cost_requires_equipment'),
            models.CheckConstraint(condition=Q(amount__gt=0), name='cash_amount_positive'),
            models.CheckConstraint(condition=Q(kind__in=[k for k,l in KINDS]), name='cash_kind_valid'),
            models.CheckConstraint(condition=Q(state__in=['PENDING','POSTED','REJECTED']), name='cash_state_valid'),
            models.CheckConstraint(condition=~Q(prepared_by=F('reviewed_by')), name='cash_no_self_review'),
            models.CheckConstraint(condition=(
                Q(invoice__isnull=False,based_record_version__isnull=False,equipment_event__isnull=True,
                  advance_patient__isnull=True,kind__in=['RECEIPT','REFUND']) |
                Q(invoice__isnull=True,based_record_version__isnull=True,equipment_event__isnull=False,
                  advance_patient__isnull=True,kind__in=['EQUIPMENT_EXPENSE','EXPENSE_REVERSAL']) |
                Q(invoice__isnull=True,based_record_version__isnull=True,equipment_event__isnull=True,
                  advance_patient__isnull=False)
                & (Q(reversal_of__isnull=True,kind='RECEIPT') | Q(reversal_of__isnull=False,kind='REFUND'))),
                name='cash_exact_source'),
            models.CheckConstraint(condition=(
                Q(state='PENDING',reviewed_by__isnull=True,reviewed_at__isnull=True,lock_version=0) |
                Q(state__in=['POSTED','REJECTED'],reviewed_by__isnull=False,reviewed_at__isnull=False,lock_version=1)), name='cash_review_metadata'),
            models.UniqueConstraint(fields=['reversal_of'],condition=Q(reversal_of__isnull=False,
                advance_patient__isnull=True,state__in=['PENDING','POSTED']), name='cash_one_live_reversal'),
        ]
