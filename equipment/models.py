"""Clinic equipment facts. Management status is not clinical certification."""
import uuid
from django.db import models
from django.db.models import Q

STATES = [('IN_SERVICE','在用'),('MAINTENANCE','维修中'),('RETIRED','已退役')]
CATEGORIES = [('CHAIR','牙椅'),('IMAGING','影像设备'),('STERILIZER','消毒设备'),('OTHER','其他')]

class EquipmentAsset(models.Model):
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    asset_code = models.CharField(max_length=40)
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=16, choices=CATEGORIES)
    location = models.CharField(max_length=120)
    acquired_on = models.DateField()
    acquisition_cost = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    next_service_due = models.DateField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=STATES, default='IN_SERVICE')
    lock_version = models.PositiveIntegerField(default=0)
    registered_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    registered_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'adc_equipment_asset'
        ordering = ['asset_code']
        constraints = [
            models.UniqueConstraint(fields=['asset_code'], name='equipment_code_unique'),
            models.CheckConstraint(condition=Q(state__in=[s for s,l in STATES]), name='equipment_state_valid'),
            models.CheckConstraint(condition=Q(category__in=[s for s,l in CATEGORIES]), name='equipment_category_valid'),
            models.CheckConstraint(condition=Q(acquisition_cost__isnull=True)|Q(acquisition_cost__gte=0), name='equipment_cost_nonnegative'),
        ]

class EquipmentEvent(models.Model):
    asset = models.ForeignKey('equipment.EquipmentAsset', on_delete=models.PROTECT, related_name='events')
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    sequence = models.PositiveIntegerField()
    kind = models.CharField(max_length=16, choices=[('REGISTER','登记'),('MAINTENANCE','送修'),('SERVICE','保养完成／恢复使用'),('RETIRE','退役')])
    previous_state = models.CharField(max_length=16, blank=True)
    next_state = models.CharField(max_length=16, choices=STATES)
    performed_on = models.DateField()
    next_service_due = models.DateField(null=True, blank=True)
    cost = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    note = models.CharField(max_length=500)
    recorded_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'adc_equipment_event'
        ordering = ['-sequence']
        constraints = [
            models.UniqueConstraint(fields=['asset','sequence'], name='equipment_event_sequence_unique'),
            models.CheckConstraint(condition=Q(cost__isnull=True)|Q(cost__gte=0), name='equipment_event_cost_nonnegative'),
            models.CheckConstraint(condition=Q(kind__in=['REGISTER','MAINTENANCE','SERVICE','RETIRE']), name='equipment_event_kind_valid'),
            models.CheckConstraint(condition=Q(next_state__in=[s for s,l in STATES]), name='equipment_event_state_valid'),
        ]
