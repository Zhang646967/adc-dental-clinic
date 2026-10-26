"""Public introductions, retained publication decisions and clinic appointments.

The staff directory owns identity; these records never grant clinical authority.
"""
from django.db import models
from django.db.models import Q, F


class PublicProfile(models.Model):
    dentist = models.OneToOneField('registry.Dentist', null=True, blank=True, on_delete=models.PROTECT)
    clinic = models.OneToOneField('registry.Clinic', null=True, blank=True, on_delete=models.PROTECT)
    draft = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=0)
    submitted_version = models.ForeignKey('registry.ProfileVersion', null=True, blank=True,
        on_delete=models.PROTECT, related_name='+')
    published_version = models.ForeignKey('registry.ProfileVersion', null=True, blank=True,
        on_delete=models.PROTECT, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'adc_public_profile'
        constraints = [models.CheckConstraint(condition=(Q(dentist__isnull=False, clinic__isnull=True) |
            Q(dentist__isnull=True, clinic__isnull=False)), name='public_profile_one_subject')]


class ProfileVersion(models.Model):
    profile = models.ForeignKey(PublicProfile, on_delete=models.PROTECT, related_name='versions')
    sequence = models.PositiveIntegerField()
    content = models.JSONField()
    submitted_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):return f'提交版本 {self.sequence}'

    class Meta:
        db_table = 'adc_profile_version'
        constraints = [models.UniqueConstraint(fields=['profile', 'sequence'], name='profile_version_sequence')]


class ProfileMedia(models.Model):
    profile = models.ForeignKey(PublicProfile, on_delete=models.PROTECT, related_name='images')
    image = models.BinaryField()
    digest = models.CharField(max_length=64)
    width = models.PositiveSmallIntegerField()
    height = models.PositiveSmallIntegerField()
    alt_text = models.CharField(max_length=160)
    uploaded_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_profile_media'


class DentistClinicAffiliation(models.Model):
    dentist = models.ForeignKey('registry.Dentist', on_delete=models.PROTECT, related_name='clinic_affiliations')
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT, related_name='dentist_affiliations')
    kind = models.CharField(max_length=12, choices=[('RESIDENT', '常驻'), ('VISITING', '轮诊')])
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    state = models.CharField(max_length=8, choices=[('ACTIVE', '有效'), ('ENDED', '已结束')], default='ACTIVE')
    revision = models.PositiveIntegerField(default=0)
    published_version = models.ForeignKey(ProfileVersion, null=True, blank=True, on_delete=models.PROTECT)
    listing_published = models.BooleanField(default=False)

    class Meta:
        db_table = 'adc_dentist_clinic_affiliation'
        constraints = [
            models.UniqueConstraint(fields=['dentist', 'clinic'], name='dentist_clinic_affiliation_unique'),
            models.CheckConstraint(condition=Q(ends_on__isnull=True) | Q(ends_on__gte=F('starts_on')),
                name='affiliation_date_order'),
            models.CheckConstraint(condition=Q(state__in=['ACTIVE', 'ENDED']), name='affiliation_state_valid'),
        ]


class ClinicProfilePolicy(models.Model):
    clinic = models.OneToOneField('registry.Clinic', on_delete=models.PROTECT)
    roster_enforced = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'adc_clinic_profile_policy'


class ProfileAction(models.Model):
    profile = models.ForeignKey(PublicProfile, null=True, blank=True, on_delete=models.PROTECT)
    affiliation = models.ForeignKey(DentistClinicAffiliation, null=True, blank=True, on_delete=models.PROTECT)
    version = models.ForeignKey(ProfileVersion, null=True, blank=True, on_delete=models.PROTECT)
    clinic = models.ForeignKey('registry.Clinic', null=True, blank=True, on_delete=models.PROTECT)
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    action = models.CharField(max_length=24)
    operation_id = models.UUIDField(unique=True)
    note = models.CharField(max_length=500, blank=True)
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_profile_action'
        indexes = [models.Index(fields=['clinic', 'action', 'created_at'], name='profile_action_clinic_idx')]
