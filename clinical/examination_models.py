"""Exam requests, actual execution, immutable result versions and decisions."""
from django.db import models
from django.db.models import Q


class ExaminationProject(models.Model):
    service = models.ForeignKey('scheduling.BookingService', on_delete=models.PROTECT)
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'adc_examination_project'
        constraints = [models.UniqueConstraint(fields=['service', 'code'], name='examination_project_code')]

    def __str__(self):
        return self.name


class ExaminationDuty(models.Model):
    class Kind(models.TextChoices):
        EXECUTE = 'EXECUTE', '检查执行与结果登记'
        REVIEW = 'REVIEW', '检查结果独立审核'

    project = models.ForeignKey(ExaminationProject, on_delete=models.PROTECT)
    user = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'adc_examination_duty'
        constraints = [models.UniqueConstraint(fields=['project', 'user', 'kind'], name='examination_duty_unique')]


class ExaminationOrder(models.Model):
    source_record = models.ForeignKey('clinical.ClinicalRecordVersion', on_delete=models.PROTECT)
    project = models.ForeignKey(ExaminationProject, on_delete=models.PROTECT)
    project_name = models.CharField(max_length=100)
    number = models.CharField(max_length=35, unique=True)
    requested_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='+')
    requested_at = models.DateTimeField(auto_now_add=True)
    purpose = models.CharField(max_length=500)
    performed_at = models.DateTimeField(null=True)
    performed_by = models.ForeignKey('accounts.UserAccount', null=True, on_delete=models.PROTECT, related_name='+')
    source_reference = models.CharField(max_length=120, blank=True)
    active_release = models.ForeignKey('ExaminationEvent', null=True, on_delete=models.PROTECT, related_name='+')
    revision = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = 'adc_examination_order'
        constraints = [models.CheckConstraint(
            condition=Q(performed_at__isnull=True, performed_by__isnull=True, source_reference='')
            | (Q(performed_at__isnull=False, performed_by__isnull=False) & ~Q(source_reference='')),
            name='examination_execution_complete',
        )]


class ExaminationReport(models.Model):
    order = models.ForeignKey(ExaminationOrder, on_delete=models.PROTECT, related_name='reports')
    number = models.PositiveIntegerField()
    body = models.CharField(max_length=2000)
    correction_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = 'adc_examination_report'
        constraints = [
            models.UniqueConstraint(fields=['order', 'number'], name='examination_report_version'),
            models.CheckConstraint(condition=Q(number=1, correction_reason='')
                | (Q(number__gt=1) & ~Q(correction_reason='')), name='examination_correction_explained'),
        ]


class ExaminationEvent(models.Model):
    class Action(models.TextChoices):
        ORDER = 'ORDER', '开具检查申请'
        EXECUTE = 'EXECUTE', '登记实际检查'
        SUBMIT = 'SUBMIT', '提交检查结果'
        APPROVE = 'APPROVE', '审核通过'
        RETURN = 'RETURN', '退回结果'
        PUBLISH = 'PUBLISH', '发布给患者'
        WITHDRAW = 'WITHDRAW', '撤回患者报告'

    order = models.ForeignKey(ExaminationOrder, on_delete=models.PROTECT, related_name='events')
    report = models.ForeignKey(ExaminationReport, null=True, on_delete=models.PROTECT, related_name='events')
    action = models.CharField(max_length=12, choices=Action.choices)
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    occurred_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=500, blank=True)
    operation_id = models.UUIDField(unique=True)

    class Meta:
        db_table = 'adc_examination_event'
        constraints = [
            models.CheckConstraint(condition=Q(action__in=['ORDER', 'EXECUTE'], report__isnull=True)
                | Q(action__in=['SUBMIT', 'APPROVE', 'RETURN', 'PUBLISH', 'WITHDRAW'], report__isnull=False),
                name='examination_event_report'),
            models.UniqueConstraint(fields=['report'], condition=Q(action__in=['APPROVE', 'RETURN']),
                name='examination_independent_decision'),
            models.UniqueConstraint(fields=['report', 'action'], condition=Q(report__isnull=False),
                name='examination_report_event_unique'),
        ]
