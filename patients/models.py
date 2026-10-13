from django.db import models
from django.db.models import Q
from adc_core.identifiers import patient_no

class Patient(models.Model):
    patient_no = models.CharField(max_length=40, unique=True, default=patient_no, editable=False)
    name = models.CharField(max_length=80)
    date_of_birth = models.DateField()
    billing_address = models.CharField(max_length=255)
    phone = models.CharField(max_length=32)
    email = models.EmailField(blank=True, default="")
    emergency_name = models.CharField(max_length=80)
    emergency_phone = models.CharField(max_length=32)
    allergy_status = models.CharField(max_length=12, default="UNKNOWN", choices=[("UNKNOWN", "未询问/未知"), ("NO_KNOWN", "已确认无已知过敏"), ("KNOWN", "已知过敏")])
    allergy_info_version = models.PositiveIntegerField(default=1)
    created_in_clinic = models.ForeignKey("registry.Clinic", on_delete=models.PROTECT, related_name="registered_patients")
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = "adc_patient"
        ordering = ["-id"]
        indexes = [models.Index(fields=["phone"], name="patient_phone_idx")]
        constraints = [models.CheckConstraint(condition=Q(allergy_status__in=["UNKNOWN", "NO_KNOWN", "KNOWN"]), name="patient_allergy_status_valid"), models.CheckConstraint(condition=Q(allergy_info_version__gte=1), name="allergy_version_positive")]
    def __str__(self):
        return f"{self.name} · {self.patient_no}"

class PatientAllergy(models.Model):
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="allergy_links")
    allergy = models.ForeignKey("registry.Allergy", on_delete=models.PROTECT)
    notes = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = "adc_patient_allergy"
        constraints = [models.UniqueConstraint(fields=["patient", "allergy"], name="patient_allergy_unique")]
