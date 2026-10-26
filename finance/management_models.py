"""Monthly management costs; these records do not post payments or payroll."""
from django.db import models
from django.db.models import Q, F

COST_CATEGORIES = [('SUPPLIES','耗材'),('LABOUR','人工'),('RENT','租金'),('UTILITIES','水电物业'),
    ('MAINTENANCE','维修'),('DEPRECIATION','折旧'),('MARKETING','营销'),('OTHER','其他')]


class CostMonth(models.Model):
    clinic = models.ForeignKey('registry.Clinic', null=True, blank=True, on_delete=models.PROTECT)
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    revision = models.PositiveIntegerField(default=0)
    coverage = models.JSONField(default=dict)

    class Meta:
        db_table = 'adc_cost_month'
        constraints = [
            models.UniqueConstraint(fields=['clinic','year','month'], condition=Q(clinic__isnull=False), name='clinic_cost_month_unique'),
            models.UniqueConstraint(fields=['year','month'], condition=Q(clinic__isnull=True), name='hq_cost_month_unique'),
            models.CheckConstraint(condition=Q(year__gte=1900,year__lte=9998,month__gte=1,month__lte=12), name='cost_month_range'),
        ]


class MonthlyCost(models.Model):
    period = models.ForeignKey(CostMonth, on_delete=models.PROTECT, related_name='costs')
    dentist = models.ForeignKey('registry.Dentist', null=True, blank=True, on_delete=models.PROTECT)
    category = models.CharField(max_length=16, choices=COST_CATEGORIES)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    reference = models.CharField(max_length=160)
    basis = models.CharField(max_length=500)
    equipment_event = models.ForeignKey('equipment.EquipmentEvent', null=True, blank=True, on_delete=models.PROTECT)
    replaces = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='corrections')
    state = models.CharField(max_length=12, default='PENDING', choices=[('PENDING','待财务复核'),('APPROVED','已确认'),('REJECTED','已退回')])
    prepared_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='+')
    prepared_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey('accounts.UserAccount', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = 'adc_monthly_cost'
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0), name='monthly_cost_nonnegative'),
            models.CheckConstraint(condition=Q(state__in=['PENDING','APPROVED','REJECTED']), name='monthly_cost_state'),
            models.CheckConstraint(condition=~Q(prepared_by=F('reviewed_by')), name='monthly_cost_independent'),
            models.UniqueConstraint(fields=['replaces'], condition=Q(replaces__isnull=False,state__in=['PENDING','APPROVED']), name='monthly_cost_live_correction'),
            models.UniqueConstraint(fields=['period','reference'],condition=Q(replaces__isnull=True,state__in=['PENDING','APPROVED']),name='monthly_cost_source_unique'),
            models.UniqueConstraint(fields=['equipment_event'],condition=Q(equipment_event__isnull=False,replaces__isnull=True,state__in=['PENDING','APPROVED']),name='monthly_equipment_cost_once'),
            models.CheckConstraint(condition=Q(state='PENDING',reviewed_by__isnull=True,reviewed_at__isnull=True) |
                Q(state__in=['APPROVED','REJECTED'],reviewed_by__isnull=False,reviewed_at__isnull=False),name='monthly_cost_review_metadata'),
        ]


class ManagementReport(models.Model):
    period = models.ForeignKey(CostMonth, on_delete=models.PROTECT, related_name='reports')
    sequence = models.PositiveIntegerField()
    snapshot = models.JSONField()
    digest = models.CharField(max_length=64)
    confirmed_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    confirmed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_management_report'
        constraints = [models.UniqueConstraint(fields=['period','sequence'],name='management_report_sequence')]


class CostAllocation(models.Model):
    report = models.ForeignKey(ManagementReport, on_delete=models.PROTECT, related_name='allocations')
    dentist = models.ForeignKey('registry.Dentist', on_delete=models.PROTECT)
    shift_minutes = models.PositiveIntegerField()
    direct_cost = models.DecimalField(max_digits=16,decimal_places=2)
    shared_cost = models.DecimalField(max_digits=16,decimal_places=2)
    production = models.DecimalField(max_digits=16,decimal_places=2)
    contribution = models.DecimalField(max_digits=16,decimal_places=2)
    basis = models.JSONField()

    class Meta:
        db_table = 'adc_cost_allocation'
        constraints = [models.UniqueConstraint(fields=['report','dentist'],name='report_dentist_allocation_unique')]


class ManagementAction(models.Model):
    period = models.ForeignKey(CostMonth, on_delete=models.PROTECT)
    cost = models.ForeignKey(MonthlyCost, null=True, blank=True, on_delete=models.PROTECT)
    report = models.ForeignKey(ManagementReport, null=True, blank=True, on_delete=models.PROTECT)
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    action = models.CharField(max_length=16)
    operation_id = models.UUIDField(unique=True)
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_management_action'
