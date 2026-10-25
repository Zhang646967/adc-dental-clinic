from uuid import uuid4
from django.db import models
from django.db.models import Q

class WorkspaceContext(models.Model):
    """Server-side active workspace. Session stores its opaque id, never a grant."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user = models.ForeignKey('accounts.UserAccount', on_delete=models.CASCADE)
    role = models.CharField(max_length=16, default='', blank=True)
    login_channel = models.CharField(max_length=8, default='', blank=True,
        choices=[('', '内部上下文'), ('PATIENT', '患者通道'), ('STAFF', '员工通道')])
    clinic = models.ForeignKey('registry.Clinic', null=True, blank=True, on_delete=models.PROTECT)
    patient_grant = models.ForeignKey('portal.PatientAppointmentGrant', null=True, blank=True, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        db_table = 'adc_workspace_context'
        constraints = [models.CheckConstraint(condition=Q(clinic__isnull=True) | Q(role__in=['MANAGER','FRONT_DESK']), name='workspace_clinic_role'),
            models.CheckConstraint(condition=Q(patient_grant__isnull=True) | Q(role='PATIENT'), name='workspace_patient_subject'),
            models.CheckConstraint(condition=Q(login_channel='') | Q(login_channel='PATIENT', role__in=['','PATIENT']) |
                (Q(login_channel='STAFF') & ~Q(role='PATIENT')), name='workspace_login_channel')]
