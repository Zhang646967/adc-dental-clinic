from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from adc_core.rules import ROLE_CHOICES, SCOPE_CHOICES

class UserAccount(AbstractUser):
    dentist = models.OneToOneField("registry.Dentist", on_delete=models.PROTECT, null=True, blank=True)
    class Meta:
        db_table = "adc_user"
        verbose_name = "员工账号"
        verbose_name_plural = "员工账号"

class RoleAssignment(models.Model):
    user = models.ForeignKey("accounts.UserAccount", on_delete=models.PROTECT, related_name="role_assignments")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    scope_kind = models.CharField(max_length=16, choices=SCOPE_CHOICES)
    clinic = models.ForeignKey("registry.Clinic", on_delete=models.PROTECT, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    class Meta:
        db_table = "adc_role_assignment"
        constraints = [
            models.CheckConstraint(condition=(Q(role__in=["FRONT_DESK", "MANAGER"], scope_kind="CLINIC", clinic__isnull=False) | Q(role="DENTIST", scope_kind="SELF_DENTIST", clinic__isnull=True) | Q(role__in=["HQ", "FINANCE"], scope_kind="CHAIN", clinic__isnull=True) | Q(role="SYSADMIN", scope_kind="TECHNICAL", clinic__isnull=True)), name="role_scope_valid"),
            models.UniqueConstraint(fields=["user", "role", "scope_kind", "clinic"], condition=Q(clinic__isnull=False), name="role_clinic_unique"),
            models.UniqueConstraint(fields=["user", "role", "scope_kind"], condition=Q(clinic__isnull=True), name="role_noclinic_unique"),
        ]
