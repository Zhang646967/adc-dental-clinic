"""Clinical authority is distinct from directory evidence and financial records."""
from django.db import models
from django.db.models import Q, F


class ClinicalReviewerAppointment(models.Model):
    user = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    reference = models.CharField(max_length=160)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    revision = models.PositiveIntegerField(default=0)
    appointed_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='+')
    appointed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_clinical_reviewer'
        constraints = [
            models.UniqueConstraint(fields=['user', 'clinic'], name='clinical_reviewer_clinic_unique'),
            models.CheckConstraint(condition=Q(valid_until__gt=F('valid_from')), name='clinical_reviewer_interval'),
        ]


class ProfessionalAuthorization(models.Model):
    STATES = [('PENDING', '待专业审核'), ('APPROVED', '已批准'), ('REJECTED', '未通过'),
              ('SUSPENDED', '已暂停'), ('REVOKED', '已撤销')]
    SOURCES = [('REGISTRY', '登记机构核验'), ('DOCUMENT', '人工核验原始证明'), ('SYNTHETIC', '明确的合成演练资料')]
    user = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    service = models.ForeignKey('scheduling.BookingService', null=True, blank=True, on_delete=models.PROTECT)
    source_kind = models.CharField(max_length=16, choices=SOURCES)
    source_reference = models.CharField(max_length=160)
    issuer = models.CharField(max_length=160)
    credential_from = models.DateTimeField()
    credential_until = models.DateTimeField()
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    can_read = models.BooleanField(default=True)
    can_record = models.BooleanField(default=False)
    can_refer = models.BooleanField(default=False)
    state = models.CharField(max_length=16, choices=STATES, default='PENDING')
    revision = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_professional_authorization'
        indexes = [models.Index(fields=['user', 'clinic', 'state'], name='professional_action_lookup')]
        constraints = [
            models.CheckConstraint(condition=Q(state__in=['PENDING','APPROVED','REJECTED','SUSPENDED','REVOKED']), name='professional_state_valid'),
            models.CheckConstraint(condition=Q(source_kind__in=['REGISTRY','DOCUMENT','SYNTHETIC']), name='professional_source_valid'),
            models.CheckConstraint(condition=Q(valid_until__gt=F('valid_from')) & Q(valid_from__gte=F('credential_from')) & Q(valid_until__lte=F('credential_until')), name='professional_within_evidence'),
            models.CheckConstraint(condition=Q(can_read=True), name='professional_requires_read'),
        ]


class ClinicalAuthorityPolicy(models.Model):
    """A retained clinic activation, not a mutable bypass switch."""
    clinic = models.OneToOneField('registry.Clinic', on_delete=models.PROTECT)
    activated_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    activated_at = models.DateTimeField(auto_now_add=True)
    reference = models.CharField(max_length=160)

    class Meta:
        db_table = 'adc_clinical_authority_policy'


class ClinicalAuthorityEvent(models.Model):
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    authorization = models.ForeignKey(ProfessionalAuthorization, null=True, blank=True, on_delete=models.PROTECT, related_name='events')
    reviewer = models.ForeignKey(ClinicalReviewerAppointment, null=True, blank=True, on_delete=models.PROTECT)
    operation_id = models.UUIDField(unique=True)
    action = models.CharField(max_length=24)
    prior_state = models.CharField(max_length=16, blank=True)
    resulting_state = models.CharField(max_length=16, blank=True)
    note = models.CharField(max_length=500)
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_clinical_authority_event'


class ClinicalReferral(models.Model):
    STATES = [('REQUESTED', '待接收店核对身份'), ('IDENTITY_CONFIRMED', '身份已核对，待医师接收'),
        ('IDENTITY_DISPUTED', '身份待澄清'), ('ACCEPTED', '已接收'), ('DECLINED', '未接收'),
        ('WITHDRAWN', '已撤回'), ('REVOKED', '查阅已撤销')]
    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT)
    source_visit = models.ForeignKey('scheduling.Visit', on_delete=models.PROTECT)
    source_record = models.ForeignKey('care.VisitRecordVersion', null=True, blank=True, on_delete=models.PROTECT)
    source_clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT, related_name='+')
    destination_clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT, related_name='+')
    destination_service = models.ForeignKey('scheduling.BookingService', null=True, blank=True, on_delete=models.PROTECT)
    receiver = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='+')
    created_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    consent_basis = models.CharField(max_length=24, choices=[('PATIENT', '患者本人明确同意'), ('LEGAL_REPRESENTATIVE', '已另行核验的法定代理同意')])
    consent_reference = models.CharField(max_length=160)
    purpose = models.CharField(max_length=500)
    valid_until = models.DateTimeField()
    state = models.CharField(max_length=24, choices=STATES, default='REQUESTED')
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'adc_clinical_referral'
        constraints = [
            models.CheckConstraint(condition=~Q(source_clinic=F('destination_clinic')), name='referral_distinct_clinics'),
            models.CheckConstraint(condition=Q(state__in=['REQUESTED','IDENTITY_CONFIRMED','IDENTITY_DISPUTED','ACCEPTED','DECLINED','WITHDRAWN','REVOKED']), name='referral_state_valid'),
            models.CheckConstraint(condition=Q(consent_basis__in=['PATIENT','LEGAL_REPRESENTATIVE']), name='referral_consent_valid'),
        ]


class ClinicalReferralEvent(models.Model):
    referral = models.ForeignKey(ClinicalReferral, on_delete=models.PROTECT, related_name='events')
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    operation_id = models.UUIDField(unique=True)
    action = models.CharField(max_length=24)
    prior_state = models.CharField(max_length=24, blank=True)
    resulting_state = models.CharField(max_length=24)
    note = models.CharField(max_length=500)
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_clinical_referral_event'


class SensitiveReadEvent(models.Model):
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    role = models.CharField(max_length=16, blank=True)
    object_kind = models.CharField(max_length=24)
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    purpose = models.CharField(max_length=24)
    outcome = models.CharField(max_length=8, choices=[('ALLOW', '已授权查阅'), ('DENY', '查阅未获准')])
    trace_id = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_sensitive_read_event'
        indexes = [models.Index(fields=['actor', 'created_at'], name='sensitive_actor_time')]
        constraints = [models.CheckConstraint(condition=Q(outcome__in=['ALLOW','DENY']), name='sensitive_outcome_valid')]
