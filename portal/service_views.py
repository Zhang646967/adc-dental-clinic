"""Public patient discovery. No account/workspace context processors or writes."""
from django.conf import settings
from django.http import Http404, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_safe
from scheduling.service_content import CATEGORY_CHOICES, GUIDES, GUIDE_BY_KEY, SOURCES, URGENT_NOTICE, positive_id
from portal.service_catalogue import public_profiles
from portal.discovery import discovery_data,service_discovery


def public_page(request, template, **context):
    return HttpResponse(render_to_string(template, {
        'signed_in': request.user.is_authenticated,
        'environment_label': settings.ADC_PUBLIC_ENVIRONMENT_LABEL,
        'urgent_notice': URGENT_NOTICE, **context,
    }), headers={'Cache-Control': 'no-store'})


@require_safe
def landing(request):
    profiles = public_profiles()
    return public_page(request, 'services/landing.html', guides=GUIDES, featured=profiles[:4],
        service_count=len(profiles), clinic_count=len({p.service.department.clinic_id for p in profiles}),
        discovery=discovery_data(),directory_limit=4)


@require_safe
def catalogue(request):
    category = request.GET.get('category', '')
    if category and category not in dict(CATEGORY_CHOICES):
        raise Http404
    clinic = request.GET.get('clinic', '')
    clinic_id = positive_id(clinic) if clinic else None
    if clinic and not clinic_id:
        raise Http404
    profiles = public_profiles()
    clinics = sorted({p.service.department.clinic_id: p.service.department.clinic for p in profiles}.values(),
                     key=lambda c: (c.name, c.pk))
    if clinic_id and clinic_id not in {c.pk for c in clinics}:
        raise Http404
    selected = [p for p in profiles if (not category or p.category == category) and
                (not clinic_id or p.service.department.clinic_id == clinic_id)]
    return public_page(request, 'services/catalogue.html', profiles=selected, categories=CATEGORY_CHOICES,
        selected_category=category, selected_clinic=clinic_id, clinics=clinics)


@require_safe
def detail(request, service_id):
    profile = next((p for p in public_profiles() if p.service_id == service_id), None)
    if profile is None:
        raise Http404
    return public_page(request, 'services/detail.html', profile=profile,
        guide=GUIDE_BY_KEY.get(profile.category),public_service=service_discovery(service_id))


@require_safe
def guide(request, category):
    content = GUIDE_BY_KEY.get(category)
    if content is None:
        raise Http404
    return public_page(request, 'services/guide.html', guide=content,
        profiles=public_profiles(category=category), sources=SOURCES)


@require_safe
def clinics(request):
    # Public branches are those with a complete, published offering. Employee
    # contacts, qualification notes, home addresses and patient data are absent.
    return public_page(request, 'services/clinics.html', discovery=discovery_data())
