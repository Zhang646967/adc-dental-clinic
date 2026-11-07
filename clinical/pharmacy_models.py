"""Approved pharmacy prices and attributable physical dispensing facts."""
from django.db import models
from django.db.models import Q


class PharmacyQuote(models.Model):
    approval = models.OneToOneField('clinical.PrescriptionDecision', on_delete=models.PROTECT,
                                    related_name='pharmacy_quote')
    prepared_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    duty = models.ForeignKey('clinical.PrescriptionDuty', on_delete=models.PROTECT)
    operation_id = models.UUIDField(unique=True, editable=False)
    reason = models.CharField(max_length=500)
    prepared_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_pharmacy_quote'


class PharmacyQuoteLine(models.Model):
    quote = models.ForeignKey(PharmacyQuote, on_delete=models.PROTECT, related_name='lines')
    item = models.ForeignKey('clinical.PrescriptionCatalogueItem', on_delete=models.PROTECT)
    name_snapshot = models.CharField(max_length=100)
    unit_snapshot = models.CharField(max_length=16)
    ordered_quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'adc_pharmacy_quote_line'
        ordering = ['pk']
        constraints = [
            models.UniqueConstraint(fields=['quote', 'item'], name='pharmacy_quote_item_unique'),
            models.CheckConstraint(condition=Q(ordered_quantity__gte=1, ordered_quantity__lte=9999,
                                               unit_price__gt=0), name='pharmacy_quote_line_values'),
        ]


class DispenseMovement(models.Model):
    class Kind(models.TextChoices):
        ISSUE = 'ISSUE', '实际发药'
        RETURN = 'RETURN', '实际退药'

    line = models.ForeignKey(PharmacyQuoteLine, on_delete=models.PROTECT, related_name='movements')
    kind = models.CharField(max_length=6, choices=Kind.choices)
    original_issue = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True,
                                       related_name='returns')
    quantity = models.PositiveIntegerField()
    requires_batch = models.BooleanField(default=False)
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    duty = models.ForeignKey('clinical.PrescriptionDuty', on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    operation_id = models.UUIDField(unique=True, editable=False)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_dispense_movement'
        ordering = ['pk']
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gte=1, quantity__lte=9999) & ~Q(reason='') &
                (Q(kind='ISSUE', original_issue__isnull=True) | Q(kind='RETURN', original_issue__isnull=False)),
                name='dispense_movement_values'),
        ]


class PharmacyStop(models.Model):
    approval = models.OneToOneField('clinical.PrescriptionDecision', on_delete=models.PROTECT,
                                    related_name='pharmacy_stop')
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    duty = models.ForeignKey('clinical.PrescriptionDuty', on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    operation_id = models.UUIDField(unique=True, editable=False)
    stopped_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_pharmacy_stop'
        constraints = [models.CheckConstraint(condition=~Q(reason=''), name='pharmacy_stop_reason')]
