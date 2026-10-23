"""Read projections of explicitly published clinic services. Never reserves."""
from django.db.models import Prefetch
from adc_core.rules import RuleError
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


def public_services(actor=None):
    from portal.policies import patient_access
    access=patient_access(actor) if actor else None
    return BookingService.objects.filter(pk__in=[p.service_id for p in public_profiles()
        if (p.category!='CHILDREN' or access and access.delegated) and
        (not access or not access.delegated or p.service.department.clinic_id==access.clinic_id)]).select_related(
        'department__clinic', 'patient_presentation')


def public_profile(service_id):
    profile = published_profiles().get(service_id=service_id)
    if not complete(profile):
        raise ServicePresentation.DoesNotExist
    return profile


def require_self_service(service_id, *, clinic_id=None, actor=None):
    """New patient requests only; retained visits/offers use their own commands."""
    if not service_id:
        raise RuleError('请先选择已发布的预约服务。')
    try:
        profile = public_profile(service_id)
    except ServicePresentation.DoesNotExist as exc:
        raise RuleError('该服务暂不可在线预约，请重新查看服务或联系前台。') from exc
    if clinic_id is not None and profile.service.department.clinic_id != clinic_id:
        raise RuleError('服务与所选诊所不一致，请重新选择。')
    from portal.policies import patient_access
    access=patient_access(actor) if actor else None
    if access:access.require_clinic(profile.service.department.clinic_id)
    if profile.category == 'CHILDREN' and not (access and access.delegated):
        raise RuleError('儿童就诊需由前台核验监护人与就诊人，请联系本店前台。')
    return profile
