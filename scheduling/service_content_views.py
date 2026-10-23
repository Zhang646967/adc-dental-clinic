"""Current-clinic manager workspace for patient service information."""
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET
from equipment.policies import manager_clinic
from registry.models import Dentist
from scheduling.resource_models import BookingService, ResourcePolicy, ServicePresentation
from scheduling.service_content import GUIDES, operational_blockers, publication_readiness, presentation_values


@login_required
@require_GET
def home(request):
    clinic_id = manager_clinic(request.user)
    enabled = ResourcePolicy.objects.filter(clinic_id=clinic_id, state='ENABLED').exists()
    services = BookingService.objects.filter(department__clinic_id=clinic_id).select_related(
        'department__clinic', 'patient_presentation').prefetch_related('dentists').order_by('department__code', 'code', 'pk')
    rows = []
    for service in services:
        try:
            profile = service.patient_presentation
        except ServicePresentation.DoesNotExist:
            profile = None
        issues = operational_blockers(service_active=service.is_active,
            department_active=service.department.is_active, clinic_active=service.department.clinic.is_active,
            has_dentists=any(d.is_active for d in service.dentists.all()), policy_enabled=enabled)
        status = publication_readiness(presentation_values(profile) if profile else None, operational_issues=issues)
        rows.append({'service': service, 'profile': profile, 'status': status})
    return render(request, 'scheduling/service_content_home.html', {'rows': rows, 'guides': GUIDES,
        'visible_count': sum(row['status']['visible'] for row in rows),
        'draft_count': sum(not row['status']['visible'] for row in rows)})


@login_required
@require_GET
def preview(request, pk):
    clinic_id = manager_clinic(request.user)
    profile = get_object_or_404(ServicePresentation.objects.select_related('service__department__clinic').prefetch_related(
        Prefetch('service__dentists', queryset=Dentist.objects.filter(is_active=True).only('pk', 'name'),
            to_attr='public_dentists')), pk=pk, service__department__clinic_id=clinic_id)
    from portal.service_views import public_page
    from scheduling.service_content import GUIDE_BY_KEY
    return public_page(request, 'services/detail.html', profile=profile, guide=GUIDE_BY_KEY.get(profile.category),
        is_draft_preview=True)
