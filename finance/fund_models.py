"""Bank evidence belongs to finance; recognition is not patient cash or revenue."""
import uuid
from django.db import models
from django.db.models import Q, F


class FundTransfer(models.Model):
    line = models.ForeignKey('finance.StatementLine', on_delete=models.PROTECT, related_name='fund_transfers')
    kind = models.CharField(max_length=8, choices=[('RECEIPT', '基金银行到账'), ('RETURN', '基金银行退回')])
    state = models.CharField(max_length=12, default='PENDING', choices=[('PENDING','待独立核对'),('CONFIRMED','银行证据已核对'),('REJECTED','未通过')])
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    prepared_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='fund_transfers_prepared')
    prepared_at = models.DateTimeField(auto_now_add=True)
    basis = models.CharField(max_length=500)
    reviewed_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='fund_transfers_reviewed')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        db_table = 'adc_fund_transfer'
        constraints = [
            models.UniqueConstraint(fields=['line'], condition=Q(state__in=['PENDING','CONFIRMED']), name='fund_transfer_active_line'),
            models.CheckConstraint(condition=Q(kind__in=['RECEIPT','RETURN']), name='fund_transfer_kind'),
            models.CheckConstraint(condition=Q(state='PENDING',reviewed_by__isnull=True,reviewed_at__isnull=True,review_reason='') |
                (Q(state__in=['CONFIRMED','REJECTED'],reviewed_by__isnull=False,reviewed_at__isnull=False)&~Q(review_reason='')), name='fund_transfer_review_metadata'),
            models.CheckConstraint(condition=Q(reviewed_by__isnull=True)|~Q(prepared_by=F('reviewed_by')), name='fund_transfer_independent_review'),
        ]


class StatementUse(models.Model):
    line = models.ForeignKey('finance.StatementLine', on_delete=models.PROTECT, related_name='uses')
    cash_match = models.OneToOneField('finance.ReconciliationMatch', on_delete=models.PROTECT, null=True, blank=True, related_name='statement_use')
    fund_transfer = models.OneToOneField(FundTransfer, on_delete=models.PROTECT, null=True, blank=True, related_name='statement_use')
    state = models.CharField(max_length=8, choices=[('ACTIVE','已占用'),('RELEASED','已释放，历史保留')])
    created_at = models.DateTimeField()
    released_at = models.DateTimeField(null=True, blank=True)
    derived_from_existing = models.BooleanField(default=False)

    class Meta:
        db_table = 'adc_statement_use'
        constraints = [
            models.UniqueConstraint(fields=['line'],condition=Q(state='ACTIVE'),name='statement_one_active_use'),
            models.CheckConstraint(condition=Q(cash_match__isnull=False,fund_transfer__isnull=True)|Q(cash_match__isnull=True,fund_transfer__isnull=False),name='statement_use_exact_owner'),
            models.CheckConstraint(condition=Q(state='ACTIVE',released_at__isnull=True)|Q(state='RELEASED',released_at__isnull=False),name='statement_use_state'),
        ]
