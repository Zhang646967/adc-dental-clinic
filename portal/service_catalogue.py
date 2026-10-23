"""Read projections of explicitly published clinic services. Never reserves."""
from django.db.models import Prefetch
from registry.models import Dentist
from scheduling.resource_models import BookingService, ResourcePolicy, ServicePresentation
from scheduling.service_content import presentation_values, validate_presentation


def published_profiles():
    return ServicePresentation.objects.filter(is_published=True, service__is_active=True,
        service__department__is_active=True, service__department__clinic__is_active=True,
        service__department__clinic_id__in=ResourcePolicy.objects.filter(state='ENABLED').values('clinic_id'),
        service__dentists__is_active=True).select_related('service__department__clinic').prefetch_related(
            Prefetch('service__dentists', queryset=Dentist.objects.filter(is_active=True).only('pk', 'name'),
                     to_attr='public_dentists')).distinct()


def complete(profile):
    return not validate_presentation(presentation_values(profile))


def public_profiles(*, category=None, clinic_id=None):
    rows = published_profiles()
    if category:
        rows = rows.filter(category=category)
    if clinic_id:
        rows = rows.filter(service__department__clinic_id=clinic_id)
    # Fail closed even if a maintenance/import path bypassed ModelForm.clean().
    return [profile for profile in rows if complete(profile)]


def public_services():
    return BookingService.objects.filter(pk__in=[p.service_id for p in public_profiles() if p.category!='CHILDREN']).select_related(
        'department__clinic', 'patient_presentation')
