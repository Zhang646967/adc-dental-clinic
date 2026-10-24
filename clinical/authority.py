"""Professional action authority; directory qualifications are evidence, not grants."""
from django.core.exceptions import PermissionDenied
from django.conf import settings
from django.utils import timezone
from accounts.models import RoleAssignment, UserAccount
from accounts.policies import bindings
from workspaces.context import require_active
from clinical.models import ClinicalAuthorityPolicy, ProfessionalAuthorization, ClinicalReviewerAppointment


def professional_scope(user_id, clinic_id, service_id, action, *, at=None, lock=False):
    """Caller holds participating account locks for a mutation. Never a role bypass."""
    if action not in ('READ', 'RECORD', 'REFER'):
        raise ValueError('Unknown professional action')
    at = at or timezone.now()
    if not UserAccount.objects.filter(pk=user_id, is_active=True, dentist__is_active=True).exists():
        raise PermissionDenied('医师账号或人员状态已失效，请联系本店主管安排交接。')
    if not RoleAssignment.objects.filter(user_id=user_id, role='DENTIST', scope_kind='SELF_DENTIST', is_active=True).exists():
        raise PermissionDenied('医师工作身份已撤回，请联系本店主管。')
    rows = ProfessionalAuthorization.objects.filter(user_id=user_id, clinic_id=clinic_id, clinic__is_active=True,
        service_id=service_id, state='APPROVED', valid_from__lte=at, valid_until__gt=at,
        **{'can_' + action.lower(): True}).order_by('pk')
    if not settings.ADC_CLINICAL_SYNTHETIC:
        rows=rows.exclude(source_kind='SYNTHETIC')
    if lock:
        rows = rows.select_for_update()
    result = rows.first()
    if result is None:
        raise PermissionDenied('当前诊所、服务或操作没有有效的专业授权，或授权已到期。请联系本店主管。')
    return result


def visit_service_id(visit):
    from scheduling.resource_models import ResourcePlan
    return ResourcePlan.objects.filter(visit_id=visit.pk, is_current=True).values_list('service_id', flat=True).first()


def professional_controls(clinic_id):
    return not settings.ADC_CLINICAL_SYNTHETIC or ClinicalAuthorityPolicy.objects.filter(clinic_id=clinic_id).exists()


def require_visit_authority(actor, visit, action, *, lock=False, always=False):
    require_active(actor, ('DENTIST',))
    if not bindings(actor).filter(role='DENTIST', scope_kind='SELF_DENTIST', user__dentist_id=visit.dentist_id).exists():
        raise PermissionDenied('只有本次负责医师可以办理此临床操作。')
    if always or professional_controls(visit.clinic_id):
        return professional_scope(actor.pk, visit.clinic_id, visit_service_id(visit), action, lock=lock)
    return None  # Explicit pre-activation legacy boundary, not clinical qualification.


def require_reviewer(actor, clinic_id, *, lock=False):
    require_active(actor, ('DENTIST',))
    if not bindings(actor).filter(role='DENTIST', scope_kind='SELF_DENTIST', user__dentist__is_active=True).exists():
        raise PermissionDenied('需要有效的医师身份及本店专业审核职责。')
    now = timezone.now()
    rows = ClinicalReviewerAppointment.objects.filter(user=actor, clinic_id=clinic_id, clinic__is_active=True,
        is_active=True, valid_from__lte=now, valid_until__gt=now)
    if lock:
        rows = rows.select_for_update()
    reviewer = rows.first()
    if reviewer is None:
        raise PermissionDenied('没有当前有效的本店专业审核职责。')
    return reviewer


def require_patient_read(actor, patient):
    """A doctor's existing assigned-patient association also needs current scope."""
    if not bindings(actor).filter(role='DENTIST', scope_kind='SELF_DENTIST').exists():
        return  # The caller still applies the unchanged patient/clinic selector.
    from scheduling.models import Visit
    for visit in Visit.objects.filter(patient=patient, dentist_id=actor.dentist_id).order_by('-pk'):
        try:
            require_visit_authority(actor, visit, 'READ')
            return
        except PermissionDenied:
            continue
    raise PermissionDenied('当前没有对此患者的有效负责医师查阅范围。')


def readable_assigned_visits(actor, dentist_id, *, strict=False):
    """Set-based list boundary, so an expired scope cannot leak allergy status."""
    from django.db.models import Q, OuterRef, Subquery
    from scheduling.models import Visit
    from scheduling.resource_models import ResourcePlan
    visits=Visit.objects.filter(dentist_id=dentist_id)
    now=timezone.now()
    scopes=ProfessionalAuthorization.objects.filter(user_id=actor.pk,user__is_active=True,
        user__dentist__is_active=True,clinic__is_active=True,state='APPROVED',can_read=True,
        valid_from__lte=now,valid_until__gt=now)
    if not settings.ADC_CLINICAL_SYNTHETIC:
        scopes=scopes.exclude(source_kind='SYNTHETIC')
    plans=ResourcePlan.objects.filter(is_current=True,visit__isnull=False)
    permitted_plans=plans.filter(service_id__in=Subquery(scopes.filter(
        clinic_id=OuterRef('visit__clinic_id')).values('service_id')))
    legacy_scope=Q(clinic_id__in=scopes.filter(service__isnull=True).values('clinic_id')) & ~Q(pk__in=plans.values('visit_id'))
    readable=Q(pk__in=permitted_plans.values('visit_id')) | legacy_scope
    if settings.ADC_CLINICAL_SYNTHETIC and not strict:
        readable |= ~Q(clinic_id__in=ClinicalAuthorityPolicy.objects.values('clinic_id'))
    return visits.filter(readable)


def may_refer(actor, visit):
    try:
        require_visit_authority(actor,visit,'REFER',always=True)
        return True
    except PermissionDenied:
        return False
