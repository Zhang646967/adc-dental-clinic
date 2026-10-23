"""Explicit login binding; a patient number is NOT a credential."""
from django.db import models
from django.db.models import Q, F

class PatientAccess(models.Model):
    user = models.OneToOneField("accounts.UserAccount", on_delete=models.PROTECT, related_name="patient_access")
    patient = models.OneToOneField("patients.Patient", on_delete=models.PROTECT, related_name="portal_access")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = "adc_patient_access"

class BookingReceipt(models.Model):
    """A booking or rescheduling confirmation receipt; one request and one resulting visit."""
    nonce = models.UUIDField(unique=True, editable=False)
    access = models.ForeignKey(PatientAccess, on_delete=models.PROTECT, null=True, blank=True)
    appointment_grant = models.ForeignKey('PatientAppointmentGrant', on_delete=models.PROTECT, null=True, blank=True)
    visit = models.OneToOneField("scheduling.Visit", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = "adc_portal_booking_receipt"
        constraints = [models.CheckConstraint(condition=(Q(access__isnull=False, appointment_grant__isnull=True) | Q(access__isnull=True, appointment_grant__isnull=False)), name='booking_receipt_one_authority')]


class PatientRelationship(models.Model):
    """A clinic's retained claim and verification case, never a clinical permission."""
    KINDS = [('PARENT','父母'),('GUARDIAN','法定监护人'),('DELEGATE','患者委托代约人'),('FAMILY','其他亲属（仅关系）'),('CONTACT','联系人（仅联络）')]
    STATES = [('PENDING','待核验'),('VERIFIED','已核验'),('SUSPENDED','已暂停'),('REJECTED','未通过'),('REVOKED','已撤销'),('WITHDRAWN','已撤回')]
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT)
    related_name = models.CharField(max_length=100)
    kind = models.CharField(max_length=16, choices=KINDS)
    delegate_user = models.ForeignKey('accounts.UserAccount', null=True, blank=True, on_delete=models.PROTECT, related_name='patient_relationships')
    state = models.CharField(max_length=16, choices=STATES, default='PENDING')
    revision = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'adc_patient_relationship'
        indexes = [models.Index(fields=['clinic','state','created_at'], name='relationship_clinic_queue')]
        constraints = [models.CheckConstraint(condition=Q(state__in=['PENDING','VERIFIED','SUSPENDED','REJECTED','REVOKED','WITHDRAWN']), name='relationship_state_valid'),
            models.CheckConstraint(condition=Q(kind__in=['PARENT','GUARDIAN','DELEGATE','FAMILY','CONTACT']), name='relationship_kind_valid')]


class PatientAppointmentGrant(models.Model):
    """All appointment actions, one patient and clinic; no chart, money or consent rights."""
    relationship = models.OneToOneField(PatientRelationship, on_delete=models.PROTECT, related_name='appointment_grant')
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    revision = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'adc_patient_appointment_grant'
        constraints = [models.CheckConstraint(condition=Q(valid_until__gt=F('valid_from')), name='appointment_grant_interval')]


class PatientRelationshipEvent(models.Model):
    relationship = models.ForeignKey(PatientRelationship, on_delete=models.PROTECT, related_name='events')
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    operation_id = models.UUIDField(unique=True)
    action = models.CharField(max_length=24)
    prior_state = models.CharField(max_length=16, blank=True)
    resulting_state = models.CharField(max_length=16)
    basis = models.CharField(max_length=32, blank=True)
    reference = models.CharField(max_length=160, blank=True)
    note = models.CharField(max_length=500, blank=True)
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'adc_patient_relationship_event'
