"""Purpose-specific copies, distinct from appointment and medical decision authority."""
from django.db import models
from django.db.models import Q


class RecordCopyRequest(models.Model):
    KINDS=[('SELF','本人'),('GUARDIAN','经核验监护人'),('WRITTEN','本用途书面受托人')]
    STATES=[('PENDING','待身份与用途核验'),('NEED_INFO','待补充材料'),('REVIEW','待独立医务审核'),
        ('APPROVED','待生成副本'),('FAILED','生成失败，待重试'),('READY','可领取'),
        ('DELIVERED','已记录文件交付响应'),('REJECTED','未通过'),('WITHDRAWN','已撤回'),('REVOKED','领取权已撤销')]
    patient=models.ForeignKey('patients.Patient',on_delete=models.PROTECT)
    clinic=models.ForeignKey('registry.Clinic',on_delete=models.PROTECT)
    recipient=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT,related_name='record_copy_requests')
    created_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT,related_name='+')
    kind=models.CharField(max_length=12,choices=KINDS)
    purpose=models.CharField(max_length=500)
    recipient_name=models.CharField(max_length=80)
    created_at=models.DateTimeField(auto_now_add=True)
    state=models.CharField(max_length=12,choices=STATES,default='PENDING')
    revision=models.PositiveIntegerField(default=0)
    verified_by=models.ForeignKey('accounts.UserAccount',null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    verified_at=models.DateTimeField(null=True,blank=True)
    verification=models.JSONField(default=dict)
    identity_snapshot=models.JSONField(default=dict)
    assigned_reviewer=models.ForeignKey('clinical.ClinicalReviewerAppointment',null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    reviewed_by=models.ForeignKey('accounts.UserAccount',null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    reviewed_at=models.DateTimeField(null=True,blank=True)
    approval=models.JSONField(default=dict)
    pickup_until=models.DateTimeField(null=True,blank=True)
    patient_message=models.CharField(max_length=500,blank=True)
    generation_error=models.CharField(max_length=40,blank=True)
    attempts=models.PositiveIntegerField(default=0)

    class Meta:
        db_table='adc_record_copy_request'
        constraints=[models.CheckConstraint(condition=Q(kind__in=['SELF','GUARDIAN','WRITTEN']),name='copy_applicant_kind'),
            models.CheckConstraint(condition=Q(state__in=['PENDING','NEED_INFO','REVIEW','APPROVED','FAILED','READY','DELIVERED','REJECTED','WITHDRAWN','REVOKED']),name='copy_request_state')]
        indexes=[models.Index(fields=['clinic','state','created_at'],name='copy_clinic_queue')]


class RecordCopyItem(models.Model):
    request=models.ForeignKey(RecordCopyRequest,on_delete=models.PROTECT,related_name='items')
    visit=models.ForeignKey('scheduling.Visit',on_delete=models.PROTECT)
    package=models.ForeignKey('clinical.ArchivePackage',null=True,blank=True,on_delete=models.PROTECT)
    sections=models.JSONField()
    class Meta:
        db_table='adc_record_copy_item'
        constraints=[models.UniqueConstraint(fields=['request','visit'],name='copy_one_visit_scope')]


class RecordCopyFile(models.Model):
    request=models.OneToOneField(RecordCopyRequest,on_delete=models.PROTECT,related_name='file')
    pdf=models.BinaryField()
    sha256=models.CharField(max_length=64)
    manifest=models.JSONField()
    renderer=models.CharField(max_length=80)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:db_table='adc_record_copy_file'


class RecordCopyEvent(models.Model):
    request=models.ForeignKey(RecordCopyRequest,on_delete=models.PROTECT,related_name='events')
    actor=models.ForeignKey('accounts.UserAccount',null=True,blank=True,on_delete=models.PROTECT)
    operation_id=models.UUIDField(unique=True)
    action=models.CharField(max_length=24)
    snapshot=models.JSONField(default=dict)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:db_table='adc_record_copy_event'
