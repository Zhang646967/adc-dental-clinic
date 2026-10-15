"""Retained evidence and reconciliation; never an external funds transfer."""
import uuid
from django.db import models
from django.db.models import Q, F

METHODS = [('CASH','现金'),('CARD','银行卡'),('BANK_TRANSFER','银行转账'),
           ('E_WALLET','电子钱包'),('OTHER','其他')]
DECISIONS = [('PENDING','待独立复核'),('APPROVED','已核实'),('REJECTED','已拒绝')]

class PaymentAccount(models.Model):
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    code = models.CharField(max_length=40)
    method = models.CharField(max_length=16, choices=METHODS)
    is_active = models.BooleanField(default=True)
    lock_version = models.PositiveIntegerField(default=0)
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    last_operation_id = models.UUIDField(default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'adc_payment_account'
        constraints = [models.UniqueConstraint(fields=['clinic','code'], name='payment_account_code_unique'),
            models.CheckConstraint(condition=Q(method__in=[v for v,l in METHODS]), name='payment_account_method_valid')]
    def __str__(self):
        return f'{self.code} · {self.get_method_display()}'

class CashEvidenceVersion(models.Model):
    cash_entry = models.ForeignKey('finance.CashEntry', on_delete=models.PROTECT, related_name='evidence_versions')
    account = models.ForeignKey(PaymentAccount, on_delete=models.PROTECT)
    reference = models.CharField(max_length=80)
    version = models.PositiveIntegerField()
    previous = models.OneToOneField('self', on_delete=models.PROTECT, null=True, blank=True, related_name='next_version')
    initial = models.BooleanField(default=False)
    state = models.CharField(max_length=12, choices=DECISIONS, default='PENDING')
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    prepared_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='cash_evidence_prepared')
    prepared_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=500)
    reviewed_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='cash_evidence_reviewed')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=500, blank=True, default='')
    class Meta:
        db_table = 'adc_cash_evidence'
        constraints = [models.UniqueConstraint(fields=['cash_entry','version'], name='cash_evidence_version_unique'),
            models.UniqueConstraint(fields=['cash_entry'], condition=Q(state='PENDING'), name='cash_evidence_one_pending'),
            models.CheckConstraint(condition=Q(state__in=[v for v,l in DECISIONS]), name='cash_evidence_state_valid'),
            models.CheckConstraint(condition=Q(version__gte=1), name='cash_evidence_positive_version'),
            models.CheckConstraint(condition=Q(reviewed_by__isnull=True)|~Q(prepared_by=F('reviewed_by')), name='cash_evidence_separate_review'),
            models.CheckConstraint(condition=Q(state='PENDING',reviewed_by__isnull=True,reviewed_at__isnull=True,review_reason='')|
                (Q(state__in=['APPROVED','REJECTED'],reviewed_by__isnull=False,reviewed_at__isnull=False)&~Q(review_reason='')), name='cash_evidence_review_metadata')]

class StatementBatch(models.Model):
    account = models.ForeignKey(PaymentAccount, on_delete=models.PROTECT)
    created_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    source_bytes = models.BinaryField()
    digest = models.CharField(max_length=64)
    parser_version = models.CharField(max_length=12, default='csv-v1')
    normalized_rows = models.JSONField()
    state = models.CharField(max_length=12, choices=[('DRAFT','待确认导入'),('IMPORTED','已确认导入')], default='DRAFT')
    operation_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    imported_at = models.DateTimeField(null=True, blank=True)
    new_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    class Meta:
        db_table = 'adc_statement_batch'
        constraints = [models.CheckConstraint(condition=Q(state='DRAFT',operation_id__isnull=True,imported_at__isnull=True,new_count=0,skipped_count=0)|
            Q(state='IMPORTED',operation_id__isnull=False,imported_at__isnull=False), name='statement_batch_state_valid')]

class StatementLine(models.Model):
    batch = models.ForeignKey(StatementBatch, on_delete=models.PROTECT, related_name='lines')
    account = models.ForeignKey(PaymentAccount, on_delete=models.PROTECT)
    transaction_id = models.CharField(max_length=80)
    booked_on = models.DateField()
    direction = models.CharField(max_length=3, choices=[('IN','入账'),('OUT','出账')])
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    currency = models.CharField(max_length=3)
    reference = models.CharField(max_length=80)
    class Meta:
        db_table = 'adc_statement_line'
        indexes = [models.Index(fields=['account','reference'], name='statement_reference_idx')]
        constraints = [models.UniqueConstraint(fields=['account','transaction_id'], name='statement_transaction_unique'),
            models.CheckConstraint(condition=Q(amount__gt=0), name='statement_positive_amount'),
            models.CheckConstraint(condition=Q(direction__in=['IN','OUT']), name='statement_direction_valid')]

class ReconciliationMatch(models.Model):
    cash_entry = models.ForeignKey('finance.CashEntry', on_delete=models.PROTECT, related_name='reconciliation_matches')
    evidence = models.ForeignKey(CashEvidenceVersion, on_delete=models.PROTECT, related_name='matches')
    line = models.ForeignKey(StatementLine, on_delete=models.PROTECT, related_name='matches')
    state = models.CharField(max_length=12, choices=[('PENDING','待独立复核'),('CONFIRMED','匹配已复核'),('REJECTED','已拒绝'),('STALE','凭据已更新，需重核')], default='PENDING')
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    prepared_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='matches_prepared')
    prepared_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='matches_reviewed')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=500, blank=True, default='')
    invalidated_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='matches_invalidated')
    invalidated_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        db_table = 'adc_reconciliation_match'
        constraints = [models.UniqueConstraint(fields=['cash_entry'], condition=Q(state__in=['PENDING','CONFIRMED']), name='reconciliation_cash_active'),
            models.UniqueConstraint(fields=['line'], condition=Q(state__in=['PENDING','CONFIRMED']), name='reconciliation_line_active'),
            models.CheckConstraint(condition=Q(state__in=['PENDING','CONFIRMED','REJECTED','STALE']), name='reconciliation_state_valid'),
            models.CheckConstraint(condition=Q(reviewed_by__isnull=True)|~Q(prepared_by=F('reviewed_by')), name='reconciliation_separate_review'),
            models.CheckConstraint(condition=Q(state='PENDING',reviewed_by__isnull=True,reviewed_at__isnull=True,review_reason='',invalidated_by__isnull=True,invalidated_at__isnull=True)|
                (Q(state__in=['CONFIRMED','REJECTED'],reviewed_by__isnull=False,reviewed_at__isnull=False,invalidated_by__isnull=True,invalidated_at__isnull=True)&~Q(review_reason=''))|
                Q(state='STALE',invalidated_by__isnull=False,invalidated_at__isnull=False), name='reconciliation_review_metadata')]
