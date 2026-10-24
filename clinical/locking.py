"""Shared clinical lock protocol. Call only inside an atomic command."""
from django.core.exceptions import PermissionDenied
from accounts.models import RoleAssignment,UserAccount
from accounts.policies import require_writable
from workspaces.context import require_active
from scheduling.models import Visit
from scheduling.coordination import lock_slots
from clinical.authority import require_visit_authority


def lock_clinical_visit(actor,visit_id,*,strict=True):
    require_active(actor,('DENTIST',))
    require_writable(actor)
    user=UserAccount.objects.get(pk=actor.pk)
    preview=Visit.objects.only('availability_slot_id','dentist_id','clinic_id').get(pk=visit_id)
    grant=RoleAssignment.objects.select_for_update().filter(user=actor,is_active=True,role='DENTIST',scope_kind='SELF_DENTIST').first()
    if grant is None or user.dentist_id!=preview.dentist_id:
        raise PermissionDenied('只有本次负责医师可以记录或确认本次检查。')
    require_visit_authority(actor,preview,'RECORD',lock=True,always=strict)
    lock_slots([preview.availability_slot_id])
    visit=Visit.objects.select_for_update().get(pk=visit_id)
    if visit.dentist_id!=user.dentist_id:raise PermissionDenied('本次负责医师已经变化，请核对交接。')
    return visit
