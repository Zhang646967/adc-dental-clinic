"""Clinic stock, batch traceability and nursing execution evidence."""
from django.db import models
from django.db.models import F, Q


class StockItem(models.Model):
    class Kind(models.TextChoices):
        DRUG = 'DRUG', '药品'
        MATERIAL = 'MATERIAL', '耗材'
        IMPLANT = 'IMPLANT', '植入材料'

    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    prescription_item = models.OneToOneField('clinical.PrescriptionCatalogueItem', on_delete=models.PROTECT,
                                             null=True, blank=True, related_name='stock_item')
    kind = models.CharField(max_length=8, choices=Kind.choices)
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=100)
    unit = models.CharField(max_length=16)

    class Meta:
        db_table = 'adc_stock_item'
        ordering = ['code', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['clinic', 'code'], name='stock_item_clinic_code_unique'),
            models.CheckConstraint(condition=Q(kind='DRUG', prescription_item__isnull=False) |
                Q(kind__in=['MATERIAL', 'IMPLANT'], prescription_item__isnull=True), name='stock_item_source'),
        ]

    def __str__(self):
        return f'{self.code} · {self.name} · {self.unit}'


class StockLot(models.Model):
    item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name='lots')
    code = models.CharField(max_length=60)
    expires_on = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_stock_lot'
        ordering = ['expires_on', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['item', 'code'], name='stock_lot_item_code_unique'),
            models.CheckConstraint(condition=~Q(code=''), name='stock_lot_code_required'),
        ]


class StockRecall(models.Model):
    lot = models.OneToOneField(StockLot, on_delete=models.PROTECT, related_name='recall')
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    reference = models.CharField(max_length=120)
    reason = models.CharField(max_length=500)
    operation_id = models.UUIDField(unique=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_stock_recall'


class NursingDuty(models.Model):
    class Kind(models.TextChoices):
        EXECUTE = 'EXECUTE', '护理执行'
        STERILITY = 'STERILITY', '无菌放行'

    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    user = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    reference = models.CharField(max_length=120)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'adc_nursing_duty'
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=['EXECUTE', 'STERILITY'], valid_until__gt=F('valid_from')),
                                   name='nursing_duty_period'),
            models.UniqueConstraint(fields=['user', 'clinic', 'kind'], condition=Q(revoked_at__isnull=True),
                                    name='nursing_duty_active_unique'),
        ]


class SterilePack(models.Model):
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    code = models.CharField(max_length=60)
    process_reference = models.CharField(max_length=120)
    processed_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    released_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    duty = models.ForeignKey(NursingDuty, on_delete=models.PROTECT)
    operation_id = models.UUIDField(unique=True)
    released_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_sterile_pack'
        constraints = [
            models.UniqueConstraint(fields=['clinic', 'code'], name='sterile_pack_clinic_code_unique'),
            models.CheckConstraint(condition=Q(valid_until__gt=F('released_at'), processed_at__lte=F('released_at')),
                                   name='sterile_pack_release_times'),
        ]


class SterileHold(models.Model):
    pack = models.OneToOneField(SterilePack, on_delete=models.PROTECT, related_name='hold')
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    duty = models.ForeignKey(NursingDuty, on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    operation_id = models.UUIDField(unique=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_sterile_hold'


class NursingExecution(models.Model):
    class Kind(models.TextChoices):
        MATERIAL = 'MATERIAL', '实际耗用'
        STERILE = 'STERILE', '无菌包使用'
        ADMINISTER = 'ADMINISTER', '实际给药'
        ESCALATE = 'ESCALATE', '异常上报'

    visit = models.ForeignKey('scheduling.Visit', on_delete=models.PROTECT, related_name='nursing_executions')
    performed = models.ForeignKey('clinical.PerformedProcedure', on_delete=models.PROTECT, null=True, blank=True)
    sterile_pack = models.OneToOneField(SterilePack, on_delete=models.PROTECT, null=True, blank=True,
                                       related_name='execution')
    issue = models.ForeignKey('clinical.DispenseMovement', on_delete=models.PROTECT, null=True, blank=True,
                              related_name='administrations')
    kind = models.CharField(max_length=10, choices=Kind.choices)
    quantity = models.PositiveIntegerField()
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    duty = models.ForeignKey(NursingDuty, on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    observed_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)
    operation_id = models.UUIDField(unique=True)

    class Meta:
        db_table = 'adc_nursing_execution'
        constraints = [
            models.CheckConstraint(condition=Q(observed_at__lte=F('recorded_at')) & ~Q(reason=''),
                                   name='nursing_execution_time_reason'),
            models.CheckConstraint(condition=(
                Q(kind='MATERIAL', performed__isnull=False, sterile_pack__isnull=True, issue__isnull=True, quantity__gte=1) |
                Q(kind='STERILE', performed__isnull=False, sterile_pack__isnull=False, issue__isnull=True, quantity=1) |
                Q(kind='ADMINISTER', performed__isnull=True, sterile_pack__isnull=True, issue__isnull=False, quantity__gte=1) |
                Q(kind='ESCALATE', performed__isnull=True, sterile_pack__isnull=True, issue__isnull=True, quantity=0)
            ), name='nursing_execution_source'),
        ]


class StockMovement(models.Model):
    class Kind(models.TextChoices):
        RECEIPT = 'RECEIPT', '到货入库'
        ISSUE = 'ISSUE', '发药出库'
        USE = 'USE', '临床耗用'
        QUARANTINE = 'QUARANTINE', '退药隔离'
        WASTE = 'WASTE', '报损'
        REVERSE_IN = 'REVERSE_IN', '入库冲回'
        REVERSE_OUT = 'REVERSE_OUT', '报损冲回'

    lot = models.ForeignKey(StockLot, on_delete=models.PROTECT, related_name='movements')
    kind = models.CharField(max_length=12, choices=Kind.choices)
    quantity = models.PositiveIntegerField()
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    dispense = models.OneToOneField('clinical.DispenseMovement', on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='stock_movement')
    execution = models.OneToOneField(NursingExecution, on_delete=models.PROTECT, null=True, blank=True,
                                      related_name='stock_movement')
    reverses = models.OneToOneField('self', on_delete=models.PROTECT, null=True, blank=True, related_name='reversal')
    reference = models.CharField(max_length=120, blank=True)
    reason = models.CharField(max_length=500)
    operation_id = models.UUIDField(unique=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_stock_movement'
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gte=1, quantity__lte=1000000) & ~Q(reason=''),
                                   name='stock_movement_values'),
            models.CheckConstraint(condition=(
                Q(kind__in=['ISSUE', 'QUARANTINE'], dispense__isnull=False, execution__isnull=True, reverses__isnull=True) |
                Q(kind='USE', dispense__isnull=True, execution__isnull=False, reverses__isnull=True) |
                Q(kind__in=['REVERSE_IN','REVERSE_OUT'], dispense__isnull=True, execution__isnull=True, reverses__isnull=False) |
                Q(kind__in=['RECEIPT','WASTE'], dispense__isnull=True, execution__isnull=True, reverses__isnull=True)
            ), name='stock_movement_source'),
            models.UniqueConstraint(fields=['lot','reference'], condition=Q(kind='RECEIPT'),
                                    name='stock_lot_receipt_reference_unique'),
        ]
