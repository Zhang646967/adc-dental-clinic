"""Retained medical archive requests, exact packages and reviewed amendments."""
from django.db import models
from django.db.models import F, Q


class ClinicalArchive(models.Model):
    encounter = models.OneToOneField('clinical.ClinicalEncounter', on_delete=models.PROTECT, related_name='archive')
    responsible = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    due_at = models.DateTimeField()
    supplement_due_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_clinical_archive'


class ArchiveSubmission(models.Model):
    KINDS = [('ARCHIVE', '完整病历归档'), ('MATERIALS', '缺项资料保全（未完成归档）')]
    STATES = [('PENDING', '待独立医务审核'), ('RETURNED', '退回完善'), ('REJECTED', '未通过'),
              ('APPROVED', '已审核，待生成'), ('FAILED', '生成失败，待重试'),
              ('STALE', '来源或职责变化，待重新提交'), ('PUBLISHED', '固定文件已生成')]
    archive = models.ForeignKey(ClinicalArchive, on_delete=models.PROTECT, related_name='submissions')
    number = models.PositiveIntegerField()
    kind = models.CharField(max_length=12, choices=KINDS)
    document_version = models.ForeignKey('clinical.ClinicalDocumentVersion', null=True, blank=True, on_delete=models.PROTECT)
    previous_package = models.ForeignKey('clinical.ArchivePackage', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    snapshot = models.JSONField()
    source_digest = models.CharField(max_length=64)
    reason = models.CharField(max_length=1000)
    submitted_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='+')
    assigned_reviewer = models.ForeignKey('clinical.ClinicalReviewerAppointment', on_delete=models.PROTECT, related_name='+')
    due_at = models.DateTimeField()
    submitted_at = models.DateTimeField(auto_now_add=True)
    operation_id = models.UUIDField(unique=True)
    state = models.CharField(max_length=12, choices=STATES, default='PENDING')
    revision = models.PositiveIntegerField(default=0)
    reviewer = models.ForeignKey('clinical.ClinicalReviewerAppointment', null=True, blank=True, on_delete=models.PROTECT)
    reviewed_by = models.ForeignKey('accounts.UserAccount', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=1000, blank=True)
    approval_scope = models.JSONField(default=dict)
    attempts = models.PositiveIntegerField(default=0)
    generation_error = models.CharField(max_length=40, blank=True)

    class Meta:
        db_table = 'adc_archive_submission'
        constraints = [models.UniqueConstraint(fields=['archive', 'number'], name='archive_submission_number'),
            models.CheckConstraint(condition=Q(kind__in=['ARCHIVE', 'MATERIALS']), name='archive_submission_kind'),
            models.CheckConstraint(condition=Q(state__in=['PENDING','RETURNED','REJECTED','APPROVED','FAILED','STALE','PUBLISHED']), name='archive_submission_state'),
            models.CheckConstraint(condition=Q(kind='MATERIALS') | Q(document_version__isnull=False), name='archive_requires_document'),
            models.UniqueConstraint(fields=['archive'],condition=Q(state__in=['PENDING','APPROVED','FAILED']),name='archive_one_open_submission')]
        indexes = [models.Index(fields=['state', 'submitted_at'], name='archive_generation_queue')]


class ArchivePackage(models.Model):
    archive = models.ForeignKey(ClinicalArchive, on_delete=models.PROTECT, related_name='packages')
    submission = models.OneToOneField(ArchiveSubmission, on_delete=models.PROTECT, related_name='package')
    number = models.PositiveIntegerField()
    previous = models.OneToOneField('self', null=True, blank=True, on_delete=models.PROTECT, related_name='next_package')
    pdf = models.BinaryField()
    pdf_sha256 = models.CharField(max_length=64)
    manifest = models.JSONField()
    renderer = models.CharField(max_length=64)
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_archive_package'
        constraints = [models.UniqueConstraint(fields=['archive', 'number'], name='archive_package_number'),
            models.CheckConstraint(condition=Q(number=1, previous__isnull=True) | Q(number__gt=1, previous__isnull=False), name='archive_package_previous'),
            models.CheckConstraint(condition=~Q(previous=F('id')), name='archive_package_not_self')]


class ArchiveAmendment(models.Model):
    TARGETS = [('DOCUMENT', '完整病历文书'), ('RECORD', '检查及牙位记录')]
    STATES = [('PENDING', '待独立医务审核'), ('RETURNED', '退回完善'), ('REJECTED', '未通过'),
              ('APPROVED', '已批准准确内容，待医师确认'), ('APPLIED', '已追加临床版本'), ('CANCELLED', '已撤回')]
    archive = models.ForeignKey(ClinicalArchive, on_delete=models.PROTECT, related_name='amendments')
    base_package = models.ForeignKey(ArchivePackage, on_delete=models.PROTECT)
    target = models.CharField(max_length=12, choices=TARGETS)
    candidate = models.JSONField()
    candidate_digest = models.CharField(max_length=64)
    reason = models.CharField(max_length=1000)
    requested_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='+')
    assigned_reviewer = models.ForeignKey('clinical.ClinicalReviewerAppointment', on_delete=models.PROTECT, related_name='+')
    due_at = models.DateTimeField()
    requested_at = models.DateTimeField(auto_now_add=True)
    operation_id = models.UUIDField(unique=True)
    state = models.CharField(max_length=12, choices=STATES, default='PENDING')
    revision = models.PositiveIntegerField(default=0)
    reviewer = models.ForeignKey('clinical.ClinicalReviewerAppointment', null=True, blank=True, on_delete=models.PROTECT)
    reviewed_by = models.ForeignKey('accounts.UserAccount', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=1000, blank=True)
    approval_scope = models.JSONField(default=dict)
    result_document = models.OneToOneField('clinical.ClinicalDocumentVersion', null=True, blank=True, on_delete=models.PROTECT)
    result_record = models.OneToOneField('clinical.ClinicalRecordVersion', null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        db_table = 'adc_archive_amendment'
        constraints = [models.CheckConstraint(condition=Q(target__in=['DOCUMENT', 'RECORD']), name='archive_amendment_target'),
            models.CheckConstraint(condition=Q(state__in=['PENDING','RETURNED','REJECTED','APPROVED','APPLIED','CANCELLED']), name='archive_amendment_state'),
            models.CheckConstraint(condition=(Q(state='APPLIED', target='DOCUMENT', result_document__isnull=False, result_record__isnull=True) |
                Q(state='APPLIED', target='RECORD', result_record__isnull=False, result_document__isnull=True) |
                (~Q(state='APPLIED') & Q(result_document__isnull=True, result_record__isnull=True))), name='archive_amendment_result'),
            models.UniqueConstraint(fields=['archive','target'],condition=Q(state__in=['PENDING','APPROVED']),name='archive_one_open_amendment')]


class ArchiveEvent(models.Model):
    archive = models.ForeignKey(ClinicalArchive, on_delete=models.PROTECT, related_name='events')
    submission = models.ForeignKey(ArchiveSubmission, null=True, blank=True, on_delete=models.PROTECT)
    amendment = models.ForeignKey(ArchiveAmendment, null=True, blank=True, on_delete=models.PROTECT)
    package = models.ForeignKey(ArchivePackage, null=True, blank=True, on_delete=models.PROTECT)
    actor = models.ForeignKey('accounts.UserAccount', null=True, blank=True, on_delete=models.PROTECT)
    operation_id = models.UUIDField(unique=True)
    action = models.CharField(max_length=24)
    note = models.CharField(max_length=1000, blank=True)
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_archive_event'
