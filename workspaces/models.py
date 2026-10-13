from uuid import uuid4
from django.db import models
from django.db.models import Q

class WorkspaceContext(models.Model):
    """Server-side active workspace. Session stores its opaque id, never a grant."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user = models.ForeignKey('accounts.UserAccount', on_delete=models.CASCADE)
    role = models.CharField(max_length=16, default='', blank=True)
    clinic = models.ForeignKey('registry.Clinic', null=True, blank=True, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        db_table = 'adc_workspace_context'
        constraints = [models.CheckConstraint(condition=Q(clinic__isnull=True) | Q(role__in=['MANAGER','FRONT_DESK']), name='workspace_clinic_role')]
