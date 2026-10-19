"""Clinic-owned scheduling catalogue and retained physical-resource promises.

EquipmentAsset remains the asset ledger. A binding only gives an existing asset
a scheduling location; it never registers an acquisition or an expense.
"""
from django.db import models
from django.db.models import F, Q
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeBoundary, RangeOperators
from adc_core.db import TsTzRange


class ResourcePolicy(models.Model):
    clinic = models.OneToOneField('registry.Clinic', on_delete=models.PROTECT)
    state = models.CharField(max_length=12, default='PREPARING', choices=[('PREPARING', '配置核对中'), ('ENABLED', '统一资源控制')])
    revision = models.PositiveIntegerField(default=0)
    activated_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        db_table = 'adc_resource_policy'


class Department(models.Model):
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = 'adc_department'
        ordering = ['code', 'pk']
        constraints = [models.UniqueConstraint(fields=['clinic', 'code'], name='department_clinic_code')]
    def __str__(self): return self.name


class DepartmentHours(models.Model):
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name='hours')
    weekday = models.PositiveSmallIntegerField(choices=list(enumerate(['周一', '周二', '周三', '周四', '周五', '周六', '周日'])))
    opens_at = models.TimeField()
    closes_at = models.TimeField()
    class Meta:
        db_table = 'adc_department_hours'
        ordering = ['weekday', 'opens_at', 'pk']
        constraints = [models.CheckConstraint(condition=Q(weekday__lte=6, closes_at__gt=F('opens_at')), name='department_hours_valid')]


class TreatmentRoom(models.Model):
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name='rooms')
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = 'adc_treatment_room'
        ordering = ['code', 'pk']
        constraints = [models.UniqueConstraint(fields=['department', 'code'], name='room_department_code')]
    def __str__(self): return f'{self.department.name} / {self.name}'


class BookingService(models.Model):
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name='services')
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=100)
    duration_minutes = models.PositiveSmallIntegerField(default=30)
    is_active = models.BooleanField(default=True)
    dentists = models.ManyToManyField('registry.Dentist', related_name='booking_services', blank=True)
    class Meta:
        db_table = 'adc_booking_service'
        ordering = ['code', 'pk']
        constraints = [models.UniqueConstraint(fields=['department', 'code'], name='service_department_code'),
            models.CheckConstraint(condition=Q(duration_minutes__in=list(range(15, 241, 15))), name='service_duration_valid')]
    def __str__(self): return f'{self.name}（{self.duration_minutes}分钟）'


class ServiceRequirement(models.Model):
    service = models.ForeignKey(BookingService, on_delete=models.PROTECT, related_name='requirements')
    category = models.CharField(max_length=16, choices=[('IMAGING', '影像设备'), ('STERILIZER', '消毒设备'), ('OTHER', '其他设备')])
    quantity = models.PositiveSmallIntegerField(default=1)
    class Meta:
        db_table = 'adc_service_requirement'
        constraints = [models.UniqueConstraint(fields=['service', 'category'], name='service_category_unique'),
            models.CheckConstraint(condition=Q(quantity__gte=1, quantity__lte=8), name='requirement_quantity_valid')]


class ResourceBinding(models.Model):
    asset = models.OneToOneField('equipment.EquipmentAsset', on_delete=models.PROTECT, related_name='scheduling_binding')
    room = models.ForeignKey(TreatmentRoom, on_delete=models.PROTECT, null=True, blank=True, related_name='resources')
    shared = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = 'adc_resource_binding'
        constraints = [models.CheckConstraint(condition=Q(shared=True, room__isnull=True) | Q(shared=False, room__isnull=False), name='binding_location_valid')]


class ResourceBlock(models.Model):
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, null=True, blank=True)
    room = models.ForeignKey(TreatmentRoom, on_delete=models.PROTECT, null=True, blank=True)
    asset = models.ForeignKey('equipment.EquipmentAsset', on_delete=models.PROTECT, null=True, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason = models.CharField(max_length=500)
    is_active = models.BooleanField(default=True)
    recorded_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'adc_resource_block'
        constraints = [models.CheckConstraint(condition=Q(ends_at__gt=F('starts_at')), name='resource_block_time_order'),
            models.CheckConstraint(condition=Q(department__isnull=False, room__isnull=True, asset__isnull=True) |
                Q(department__isnull=True, room__isnull=False, asset__isnull=True) |
                Q(department__isnull=True, room__isnull=True, asset__isnull=False), name='resource_block_one_target')]


class ResourcePlan(models.Model):
    visit = models.ForeignKey('scheduling.Visit', on_delete=models.PROTECT, null=True, blank=True, related_name='resource_plans')
    offer = models.ForeignKey('coordination.WaitOffer', on_delete=models.PROTECT, null=True, blank=True, related_name='resource_plans')
    service = models.ForeignKey(BookingService, on_delete=models.PROTECT)
    room = models.ForeignKey(TreatmentRoom, on_delete=models.PROTECT)
    snapshot = models.JSONField()
    version = models.PositiveIntegerField(default=1)
    is_current = models.BooleanField(default=True)
    reason = models.CharField(max_length=500)
    recorded_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'adc_resource_plan'
        constraints = [models.CheckConstraint(condition=Q(visit__isnull=False) | Q(offer__isnull=False), name='resource_plan_source'),
            models.UniqueConstraint(fields=['visit'], condition=Q(is_current=True, visit__isnull=False), name='visit_current_resource_plan'),
            models.UniqueConstraint(fields=['offer'], condition=Q(is_current=True, offer__isnull=False), name='offer_current_resource_plan')]


class ResourceClaim(models.Model):
    plan = models.ForeignKey(ResourcePlan, on_delete=models.PROTECT, related_name='claims')
    asset = models.ForeignKey('equipment.EquipmentAsset', on_delete=models.PROTECT, related_name='resource_claims')
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    kind = models.CharField(max_length=8, choices=[('HOLD', '邀约暂占'), ('FIRM', '正式占用')])
    expires_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)
    released_at = models.DateTimeField(null=True, blank=True)
    release_reason = models.CharField(max_length=40, blank=True)
    class Meta:
        db_table = 'adc_resource_claim'
        indexes = [models.Index(fields=['asset', 'active', 'starts_at'], name='resource_claim_lookup')]
        constraints = [models.CheckConstraint(condition=Q(ends_at__gt=F('starts_at')), name='resource_claim_time_order'),
            models.UniqueConstraint(fields=['plan', 'asset'], name='resource_plan_asset_unique'),
            ExclusionConstraint(name='physical_resource_no_overlap', expressions=[
                ('asset', RangeOperators.EQUAL), (TsTzRange('starts_at', 'ends_at', RangeBoundary()), RangeOperators.OVERLAPS)], condition=Q(active=True))]


class ResourceCoordination(models.Model):
    plan = models.ForeignKey(ResourcePlan, on_delete=models.PROTECT, related_name='coordination')
    asset = models.ForeignKey('equipment.EquipmentAsset', on_delete=models.PROTECT)
    state = models.CharField(max_length=16, default='OPEN', choices=[('OPEN', '待协调'), ('CONTACT', '待联系'), ('REPLACED', '已替换资源'), ('RESOLVED', '已核实解决')])
    owner = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    due_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=500)
    revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'adc_resource_coordination'
        constraints = [models.UniqueConstraint(fields=['plan', 'asset'], condition=Q(state__in=['OPEN', 'CONTACT']), name='one_open_resource_issue')]


class ResourceAction(models.Model):
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    operation_id = models.UUIDField(unique=True)
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    kind = models.CharField(max_length=40)
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    @property
    def kind_label(self):
        return {'department':'科室维护','hours':'开放时间维护','room':'诊室维护','service':'预约服务维护','binding':'设备排程位置维护','block':'临时停用','release_block':'结束停用','start':'开始核对','activate':'启用资源控制','MAP_EXISTING':'核实原承诺','FRONT_BOOKING':'预约确认','COORD_REPLACE':'资源替换','COORD_CONTACT':'联系交接','COORD_OPEN':'登记资源协调','COORD_RESOLVE':'核实协调解决'}.get(self.kind,self.kind)
    class Meta:
        db_table = 'adc_resource_action'
