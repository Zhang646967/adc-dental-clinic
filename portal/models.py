"""Explicit login binding; a patient number is NOT a credential."""
from django.db import models

class PatientAccess(models.Model):
    user = models.OneToOneField("accounts.UserAccount", on_delete=models.PROTECT, related_name="patient_access")
    patient = models.OneToOneField("patients.Patient", on_delete=models.PROTECT, related_name="portal_access")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = "adc_patient_access"

class BookingReceipt(models.Model):
    """One confirmed request per signed nonce; safe on refresh and double submission."""
    nonce = models.UUIDField(unique=True, editable=False)
    access = models.ForeignKey(PatientAccess, on_delete=models.PROTECT)
    visit = models.OneToOneField("scheduling.Visit", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = "adc_portal_booking_receipt"
