"""Explicit patient-facing projection; no implicit model-field serialization."""
from scheduling.service_content import CATEGORY_CHOICES, fee_label


def service_data(profile, *, actor=None):
    access=None
    if actor:
        from portal.policies import patient_access
        access=patient_access(actor)
    service = profile.service
    clinic = service.department.clinic
    return dict(id=service.pk, name=profile.title, clinic=clinic.pk,
        clinic_name=clinic.name, address=clinic.postal_address, phone=clinic.phone,
        department=service.department.name, duration=service.duration_minutes,
        category=profile.category, category_label=dict(CATEGORY_CHOICES)[profile.category],
        summary=profile.summary, suitable_for=profile.suitable_for,
        visit_content=profile.visit_content, limitations=profile.limitations,
        preparation=profile.preparation, fee_mode=profile.fee_mode,
        fee_amount=str(profile.fee_amount) if profile.fee_amount is not None else None,
        fee_label=fee_label(profile.fee_mode, profile.fee_amount), fee_note=profile.fee_note,
        self_booking=profile.category != 'CHILDREN' or bool(access and access.delegated and access.clinic_id==clinic.pk),
        dentists=[dict(id=d.pk, name=d.name) for d in service.public_dentists])
