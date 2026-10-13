from django.db.models import Q
from accounts.policies import bindings, clinic_ids
from patients.models import Patient

def visible_patients(user):
    if not user.is_authenticated:
        return Patient.objects.none()
    clinics = clinic_ids(user, ("FRONT_DESK",))
    scope = Q(created_in_clinic_id__in=clinics) | Q(visits__clinic_id__in=clinics)
    if bindings(user).filter(role="DENTIST", scope_kind="SELF_DENTIST", user__dentist__isnull=False).exists():
        # Fetch the current account relation rather than trusting client data.
        dentist_id = bindings(user).filter(role="DENTIST").values_list("user__dentist_id", flat=True).first()
        scope |= Q(visits__dentist_id=dentist_id)
    return Patient.objects.filter(scope).distinct()
