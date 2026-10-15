"""Quarter and cost aggregates; changes go through finance.services."""
from django.db import models
from django.db.models import Q

class Quarter(models.Model):
    lock_version = models.PositiveIntegerField(default=0)
    year = models.PositiveSmallIntegerField()
    quarter_no = models.PositiveSmallIntegerField()
    roster_status = models.CharField(max_length=12, default="DRAFT", choices=[("DRAFT", "未确认"), ("CONFIRMED", "已确认")])
    roster_confirmed_by = models.ForeignKey("accounts.UserAccount", on_delete=models.PROTECT, null=True, blank=True)
    roster_confirmed_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        db_table = "adc_quarter"
        constraints = [
            models.UniqueConstraint(fields=["year", "quarter_no"], name="quarter_unique"),
            models.CheckConstraint(condition=Q(year__gte=1900, year__lte=9998, quarter_no__gte=1, quarter_no__lte=4), name="quarter_range_valid"),
            models.CheckConstraint(condition=(Q(roster_status="CONFIRMED", roster_confirmed_by__isnull=False, roster_confirmed_at__isnull=False) | Q(roster_status="DRAFT", roster_confirmed_by__isnull=True, roster_confirmed_at__isnull=True)), name="quarter_confirmation_valid"),
        ]

class DentistQuarterCost(models.Model):
    quarter = models.ForeignKey("finance.Quarter", on_delete=models.PROTECT, related_name="dentist_costs")
    dentist = models.ForeignKey("registry.Dentist", on_delete=models.PROTECT)
    cost_status = models.CharField(max_length=12, default="MISSING", choices=[("MISSING", "未录入"), ("DRAFT", "草稿"), ("CONFIRMED", "已确认")])
    supply_cost = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    operating_expense = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    confirmed_by = models.ForeignKey("accounts.UserAccount", on_delete=models.PROTECT, null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    class Meta:
        db_table = "adc_dentist_quarter_cost"
        constraints = [
            models.UniqueConstraint(fields=["quarter", "dentist"], name="dentist_quarter_unique"),
            models.CheckConstraint(condition=Q(cost_status__in=["MISSING", "DRAFT", "CONFIRMED"]), name="cost_status_valid"),
            models.CheckConstraint(condition=(Q(supply_cost__isnull=True) | Q(supply_cost__gte=0)) & (Q(operating_expense__isnull=True) | Q(operating_expense__gte=0)), name="cost_nonnegative"),
            models.CheckConstraint(condition=(Q(cost_status="CONFIRMED", supply_cost__isnull=False, operating_expense__isnull=False, confirmed_by__isnull=False, confirmed_at__isnull=False) | (~Q(cost_status="CONFIRMED") & Q(confirmed_by__isnull=True, confirmed_at__isnull=True))), name="cost_confirmation_valid"),
            models.CheckConstraint(condition=~Q(cost_status="MISSING") | Q(supply_cost__isnull=True, operating_expense__isnull=True), name="missing_cost_is_null"),
        ]

from finance.cash_models import CashEntry

from .daily_models import DailyClose
