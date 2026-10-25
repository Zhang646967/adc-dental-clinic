"""Published branch identity, independent of retained clinic and invoice names."""
from django.db import models
from django.db.models import Q


class ClinicDirectory(models.Model):
    clinic = models.OneToOneField('registry.Clinic', on_delete=models.PROTECT, related_name='public_directory')
    display_name = models.CharField(max_length=120)
    province = models.CharField(max_length=40)
    city = models.CharField(max_length=40)
    district = models.CharField(max_length=60)
    address = models.CharField(max_length=255)
    entrance = models.CharField(max_length=160)
    public_phone = models.CharField(max_length=32)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, help_text='WGS-84')
    longitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True, help_text='WGS-84')
    map_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, help_text='GCJ-02')
    map_longitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True, help_text='GCJ-02')
    coordinate_source = models.CharField(max_length=160, blank=True, default='')
    synthetic = models.BooleanField(default=True)
    is_published = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'adc_clinic_directory'
        ordering = ['city', 'display_name', 'clinic_id']
        constraints = [
            models.CheckConstraint(condition=(Q(latitude__isnull=True, longitude__isnull=True) |
                Q(latitude__isnull=False, longitude__isnull=False, latitude__gte=-90, latitude__lte=90,
                    longitude__gte=-180, longitude__lte=180)), name='directory_wgs84_pair'),
            models.CheckConstraint(condition=(Q(map_latitude__isnull=True, map_longitude__isnull=True) |
                Q(map_latitude__isnull=False, map_longitude__isnull=False, map_latitude__gte=-90, map_latitude__lte=90,
                    map_longitude__gte=-180, map_longitude__lte=180)), name='directory_gcj02_pair'),
        ]


class ClinicDirectoryRevision(models.Model):
    directory = models.ForeignKey(ClinicDirectory, on_delete=models.PROTECT, related_name='versions')
    revision = models.PositiveIntegerField()
    snapshot = models.JSONField()
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    operation_id = models.UUIDField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'adc_clinic_directory_revision'
        ordering = ['-revision']
        constraints = [models.UniqueConstraint(fields=['directory', 'revision'], name='directory_revision_unique')]
