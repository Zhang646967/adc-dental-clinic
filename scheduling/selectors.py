from django.db.models import Q
from accounts.policies import bindings, clinic_ids
from scheduling.models import Visit, AvailabilitySlot

def visible_visits(user):
    if not user.is_authenticated:
        return Visit.objects.none()
    grants = bindings(user)
    if grants.filter(role="HQ", scope_kind="CHAIN").exists():
        return Visit.objects.all()
    scope = Q(clinic_id__in=clinic_ids(user, ("FRONT_DESK", "MANAGER")))
    own = grants.filter(role="DENTIST", scope_kind="SELF_DENTIST", user__dentist__isnull=False)
    if own.exists():
        scope |= Q(dentist_id=own.values_list("user__dentist_id", flat=True).first())
    return Visit.objects.filter(scope)

def booking_slots(user):
    from django.utils import timezone
    return AvailabilitySlot.objects.filter(clinic_id__in=clinic_ids(user), is_active=True, booking_paused=False,
                                           clinic__is_active=True, dentist__is_active=True,
                                           ends_at__gt=timezone.now()).select_related("clinic", "dentist")

def can_read_visit_details(user, visit):
    # Supervisors/HQ receive operational metadata only, not clinical/free text.
    if bindings(user).filter(role="FRONT_DESK", scope_kind="CLINIC", clinic_id=visit.clinic_id).exists():
        return True
    return bindings(user).filter(role="DENTIST", scope_kind="SELF_DENTIST", user__dentist_id=visit.dentist_id).exists()
