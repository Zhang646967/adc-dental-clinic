"""Retained prescription submissions and independent review decisions."""
from django.db import models
from django.db.models import F, Q


class PrescriptionDuty(models.Model):
    class Kind(models.TextChoices):
        PRESCRIBE = 'PRESCRIBE', '开方'
        REVIEW = 'REVIEW', '审方'

    user = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    reference = models.CharField(max_length=120)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'adc_prescription_duty'
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=['PRESCRIBE', 'REVIEW']), name='rx_duty_kind'),
            models.CheckConstraint(condition=Q(valid_until__gt=F('valid_from')), name='rx_duty_period'),
            models.UniqueConstraint(fields=['user', 'clinic', 'kind'], condition=Q(revoked_at__isnull=True),
                                    name='rx_duty_one_unrevoked'),
        ]


class PrescriptionCatalogueItem(models.Model):
    class Route(models.TextChoices):
        ORAL = 'ORAL', '口服'
        LOCAL = 'LOCAL', '局部使用'

    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=100)
    strength = models.CharField(max_length=60)
    dose_unit = models.CharField(max_length=16)
    quantity_unit = models.CharField(max_length=16)
    route = models.CharField(max_length=12, choices=Route.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'adc_prescription_catalogue_item'
        ordering = ['code', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['clinic', 'code'], name='rx_catalogue_clinic_code'),
            models.CheckConstraint(condition=Q(route__in=['ORAL', 'LOCAL']), name='rx_catalogue_route'),
        ]

    def __str__(self):
        return f'{self.name} · {self.strength} · {self.get_route_display()} · {self.dose_unit}/{self.quantity_unit}'


class Prescription(models.Model):
    visit = models.OneToOneField('scheduling.Visit', on_delete=models.PROTECT, related_name='prescription')
    prescriber = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_prescription'


class PrescriptionVersion(models.Model):
    prescription = models.ForeignKey(Prescription, on_delete=models.PROTECT, related_name='versions')
    number = models.PositiveIntegerField()
    record = models.ForeignKey('clinical.ClinicalRecordVersion', on_delete=models.PROTECT)
    prescriber_duty = models.ForeignKey(PrescriptionDuty, on_delete=models.PROTECT)
    clinical_scope = models.ForeignKey('clinical.ProfessionalAuthorization', on_delete=models.PROTECT)
    clinical_scope_revision = models.PositiveIntegerField()
    indication = models.CharField(max_length=500)
    items = models.JSONField()
    operation_id = models.UUIDField(unique=True, editable=False)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_prescription_version'
        ordering = ['-number']
        constraints = [
            models.UniqueConstraint(fields=['prescription', 'number'], name='rx_version_number_unique'),
            models.CheckConstraint(condition=Q(number__gte=1) & ~Q(indication=''), name='rx_version_content'),
        ]

    @property
    def state(self):
        return self.decision.action if hasattr(self, 'decision') else 'PENDING'

    @property
    def state_label(self):
        return PrescriptionDecision.Action(self.state).label if self.state != 'PENDING' else '待审核'


class PrescriptionDecision(models.Model):
    class Action(models.TextChoices):
        APPROVED = 'APPROVED', '审核通过'
        RETURNED = 'RETURNED', '已退回修改'
        REJECTED = 'REJECTED', '已拒绝'
        WITHDRAWN = 'WITHDRAWN', '已撤回'

    version = models.OneToOneField(PrescriptionVersion, on_delete=models.PROTECT, related_name='decision')
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    duty = models.ForeignKey(PrescriptionDuty, on_delete=models.PROTECT)
    action = models.CharField(max_length=12, choices=Action.choices)
    reason = models.CharField(max_length=500)
    operation_id = models.UUIDField(unique=True, editable=False)
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_prescription_decision'
        constraints = [
            models.CheckConstraint(condition=Q(action__in=['APPROVED', 'RETURNED', 'REJECTED', 'WITHDRAWN']) &
                                    ~Q(reason=''), name='rx_decision_content'),
        ]
