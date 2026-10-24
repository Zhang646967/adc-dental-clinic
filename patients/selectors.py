from django.db.models import Q
from accounts.policies import bindings, clinic_ids
from patients.models import Patient
from scheduling.models import Visit

def visible_patients(user):
    if not user.is_authenticated:
        return Patient.objects.none()
    clinics = clinic_ids(user, ("FRONT_DESK",))
    scope = Q(created_in_clinic_id__in=clinics) | Q(pk__in=
        Visit.objects.filter(clinic_id__in=clinics).values('patient_id'))
    # Re-read the current binding/account relation, respecting the active role.
    dentist_id = bindings(user).filter(role="DENTIST", scope_kind="SELF_DENTIST",
        user__dentist__isnull=False).values_list("user__dentist_id", flat=True).first()
    if dentist_id is not None:
        from clinical.authority import readable_assigned_visits
        scope |= Q(pk__in=readable_assigned_visits(user,dentist_id).values('patient_id'))
    # Association existence preserves shared-patient access without multiplying
    # each patient by their complete visit history before DISTINCT/pagination.
    return Patient.objects.filter(scope)
