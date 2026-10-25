from django.db import models
from django.db.models import Q


class PatientEnrollment(models.Model):
    KINDS=[('NEW','新患者建档'),('EXISTING','已有档案关联')]
    STATES=[('PENDING','待前台核验'),('NEED_INFO','待补充资料'),('APPROVED','已关联本人'),('REJECTED','未通过'),('WITHDRAWN','已撤回')]
    user=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT,related_name='enrollments')
    clinic=models.ForeignKey('registry.Clinic',on_delete=models.PROTECT)
    kind=models.CharField(max_length=8,choices=KINDS)
    state=models.CharField(max_length=16,choices=STATES,default='PENDING')
    details=models.JSONField(default=dict)
    patient_message=models.CharField(max_length=500,blank=True)
    patient=models.ForeignKey('patients.Patient',on_delete=models.PROTECT,null=True,blank=True)
    revision=models.PositiveIntegerField(default=0)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        db_table='adc_patient_enrollment'
        constraints=[models.CheckConstraint(condition=Q(kind__in=['NEW','EXISTING']),name='enrollment_kind_valid'),
            models.CheckConstraint(condition=Q(state__in=['PENDING','NEED_INFO','APPROVED','REJECTED','WITHDRAWN']),name='enrollment_state_valid'),
            models.CheckConstraint(condition=Q(state='APPROVED',patient__isnull=False)|(~Q(state='APPROVED')&Q(patient__isnull=True)),name='enrollment_approved_patient'),
            models.UniqueConstraint(fields=['user'],condition=Q(state__in=['PENDING','NEED_INFO']),name='one_open_patient_enrollment')]
        indexes=[models.Index(fields=['clinic','state','created_at'],name='enrollment_clinic_queue')]


class PatientEnrollmentEvent(models.Model):
    enrollment=models.ForeignKey(PatientEnrollment,on_delete=models.PROTECT,related_name='events')
    actor=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    operation_id=models.UUIDField(unique=True)
    action=models.CharField(max_length=24)
    basis=models.CharField(max_length=32,blank=True)
    reference=models.CharField(max_length=160,blank=True)
    snapshot=models.JSONField(default=dict)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='adc_patient_enrollment_event'
