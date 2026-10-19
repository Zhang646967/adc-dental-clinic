"""Clinic equipment facts. Management status is not clinical certification."""
import uuid
from django.db import models
from django.db.models import Q,F

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
    def __str__(self):
        return f'{self.asset_code} · {self.name}'

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

class EquipmentCostAmendment(models.Model):
    """Retained source-cost request; approval changes a projection, never the event."""
    event = models.ForeignKey(EquipmentEvent, on_delete=models.PROTECT, related_name='cost_amendments')
    operation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    based_amendment = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True)
    previous_cost = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    proposed_cost = models.DecimalField(max_digits=16, decimal_places=2)
    reason = models.CharField(max_length=500)
    state = models.CharField(max_length=12, choices=[('PENDING','待独立审核'),('APPROVED','已核实费用'),('REJECTED','已拒绝')], default='PENDING')
    lock_version = models.PositiveIntegerField(default=0)
    prepared_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='prepared_equipment_costs')
    prepared_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='reviewed_equipment_costs')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=500, blank=True)
    class Meta:
        db_table = 'adc_equipment_cost_amendment'
        ordering = ['-pk']
        indexes = [models.Index(fields=['event','state','id'], name='equip_cost_event_state_idx')]
        constraints = [
            models.CheckConstraint(condition=Q(proposed_cost__gte=0), name='equip_cost_nonnegative'),
            models.CheckConstraint(condition=Q(state__in=['PENDING','APPROVED','REJECTED']), name='equip_cost_state_valid'),
            models.CheckConstraint(condition=~Q(prepared_by=F('reviewed_by')), name='equip_cost_no_self_review'),
            models.CheckConstraint(condition=(Q(state='PENDING',reviewed_by__isnull=True,reviewed_at__isnull=True,lock_version=0) |
                Q(state__in=['APPROVED','REJECTED'],reviewed_by__isnull=False,reviewed_at__isnull=False,lock_version=1)), name='equip_cost_review_metadata'),
            models.UniqueConstraint(fields=['event'],condition=Q(state='PENDING'), name='equip_cost_one_pending'),
        ]

from .maintenance_models import MaintenanceOrder,MaintenanceAction
