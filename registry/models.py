from django.db import models
from django.db.models import Q

class Clinic(models.Model):
    clinic_code = models.CharField(max_length=24, unique=True)
    name = models.CharField(max_length=120)
    postal_address = models.CharField(max_length=255)
    supervisor_name = models.CharField(max_length=80)
    phone = models.CharField(max_length=32)
    email = models.EmailField()
    area_sqm = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = "adc_clinic"
        ordering = ["clinic_code"]
        constraints = [models.CheckConstraint(condition=Q(area_sqm__gt=0), name="clinic_area_positive")]
    def __str__(self):
        return self.name

class Dentist(models.Model):
    employee_no = models.CharField(max_length=24, unique=True)
    name = models.CharField(max_length=80)
    date_of_birth = models.DateField()
    home_address = models.CharField(max_length=255)
    phone = models.CharField(max_length=32)
    email = models.EmailField()
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = "adc_dentist"
        ordering = ["employee_no"]
    def __str__(self):
        return self.name

class Qualification(models.Model):
    code = models.CharField(max_length=24, unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = "adc_qualification"
    def __str__(self):
        return self.name

class DentistQualification(models.Model):
    dentist = models.ForeignKey("registry.Dentist", on_delete=models.PROTECT, related_name="qualifications")
    qualification = models.ForeignKey("registry.Qualification", on_delete=models.PROTECT)
    notes = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = "adc_dentist_qualification"
        constraints = [models.UniqueConstraint(fields=["dentist", "qualification"], name="dentist_qualification_unique")]

class Allergy(models.Model):
    code = models.CharField(max_length=24, unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = "adc_allergy"
    def __str__(self):
        return self.name

class TreatmentType(models.Model):
    code = models.CharField(max_length=24, unique=True)
    name = models.CharField(max_length=120)
    unit_definition = models.CharField(max_length=120)
    standard_unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = "adc_treatment_type"
        constraints = [models.CheckConstraint(condition=Q(standard_unit_price__gte=0), name="treatment_price_nonnegative")]
    def __str__(self):
        return self.name
