"""Immutable versions of daily synthetic-ledger reconciliation."""
from django.conf import settings
from django.db import models
from django.db.models import Q, F

class DailyClose(models.Model):
    operation_id = models.UUIDField(unique=True, editable=False)
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    business_date = models.DateField()
    version = models.PositiveIntegerField()
    previous = models.OneToOneField('self', null=True, blank=True, on_delete=models.PROTECT, related_name='next_version')
    snapshot = models.JSONField()
    declared = models.JSONField()
    evidence = models.CharField(max_length=500)
    reason = models.CharField(max_length=500)
    state = models.CharField(max_length=10, default='PENDING', choices=[('PENDING','待独立复核'),('APPROVED','已复核快照'),('REJECTED','退回重核')])
    lock_version = models.PositiveIntegerField(default=0)
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='daily_closes_prepared')
    prepared_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.PROTECT,related_name='daily_closes_reviewed')
    reviewed_at = models.DateTimeField(null=True,blank=True)
    review_reason = models.CharField(max_length=500,blank=True,default='')
    class Meta:
        db_table = 'adc_daily_close'
        indexes = [models.Index(fields=['state','business_date'],name='daily_queue_idx')]
        constraints = [
            models.UniqueConstraint(fields=['clinic','business_date','version'],name='daily_version_unique'),
            models.UniqueConstraint(fields=['clinic','business_date'],condition=Q(state='PENDING'),name='daily_one_pending'),
            models.CheckConstraint(condition=Q(version__gte=1),name='daily_positive_version'),
            models.CheckConstraint(condition=Q(reviewed_by__isnull=True)|~Q(prepared_by=F('reviewed_by')),name='daily_independent_review'),
            models.CheckConstraint(condition=(Q(state='PENDING',lock_version=0,reviewed_by__isnull=True,reviewed_at__isnull=True,review_reason='')|Q(state__in=['APPROVED','REJECTED'],lock_version=1,reviewed_by__isnull=False,reviewed_at__isnull=False)&~Q(review_reason='')),name='daily_review_metadata'),
        ]
