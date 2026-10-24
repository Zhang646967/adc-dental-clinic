"""Clinical continuity ownership and shared lock boundaries."""
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from adc_core.rules import RuleError
from clinical.locking import lock_clinical_visit
from clinical.models import ClinicalEncounter,ClinicalRecordVersion
from clinical.plan_models import TreatmentPlan
from clinical.completion import completion_blockers
from clinical.authority import require_visit_authority,professional_scope
from patients.models import Patient
from portal.policies import patient_access
from workspaces.context import require_active
from accounts.policies import require_writable


def plan_services(plan,*,version=None,include_draft=True):
    from clinical.plan_models import PlanVersion,PlanDraft
    version=version or PlanVersion.objects.filter(plan=plan).order_by('-revision').first()
    services=set(version.steps.values_list('service_id',flat=True)) if version else set()
    if include_draft:
        draft=PlanDraft.objects.filter(plan=plan).first()
        if draft:services.update(row['service'] for row in draft.payload['steps'])
    return services


def readable_services(actor,clinic_id=None):
    from django.conf import settings
    from clinical.models import ProfessionalAuthorization
    now=timezone.now()
    scopes=ProfessionalAuthorization.objects.filter(user=actor,clinic__is_active=True,state='APPROVED',can_read=True,valid_from__lte=now,valid_until__gt=now)
    if clinic_id is not None:scopes=scopes.filter(clinic_id=clinic_id)
    if not settings.ADC_CLINICAL_SYNTHETIC:scopes=scopes.exclude(source_kind='SYNTHETIC')
    return set(scopes.values_list('service_id',flat=True))


def require_plan_scope(actor,visit,plan,action,*,version=None,include_draft=True,lock=False):
    for service_id in sorted(plan_services(plan,version=version,include_draft=include_draft)):
        professional_scope(actor.pk,visit.clinic_id,service_id,action,lock=lock)


def lock_plan_visit(actor,visit_id,plan_id=None,*,actual=False,ready=False):
    visit=lock_clinical_visit(actor,visit_id)
    patient=Patient.objects.select_for_update().get(pk=visit.patient_id,is_active=True)
    head=ClinicalEncounter.objects.select_for_update().filter(visit=visit).first()
    if head is None:raise RuleError('请先完成本次实际检查，再整理治疗计划或记录执行。')
    record=ClinicalRecordVersion.objects.filter(encounter=head).order_by('-revision').first()
    if record is None:raise RuleError('本次尚无确认检查版本，请先在检查工作台核对。')
    if actual and (visit.status!='CHECKED_IN' or not visit.attended_at or visit.attended_at>timezone.now()):
        raise RuleError('只能在本次实际到诊且尚未关闭时确认执行。')
    if ready:
        blocked=completion_blockers(visit)
        if blocked:raise RuleError(blocked[0])
    plan=None
    if plan_id is not None:
        plan=TreatmentPlan.objects.select_for_update().select_related('origin_encounter__visit').get(pk=plan_id)
        source=plan.origin_encounter.visit
        if source.patient_id!=patient.pk or source.clinic_id!=visit.clinic_id:
            raise PermissionDenied('本次患者或诊所与所选治疗计划不一致。')
    return visit,patient,head,record,plan


def lock_self_plan(actor,plan_id):
    require_active(actor,('PATIENT',));require_writable(actor)
    access=patient_access(actor,lock=True,self_only=True)
    patient=Patient.objects.select_for_update().get(pk=access.patient_id,is_active=True)
    plan=TreatmentPlan.objects.select_for_update().select_related('origin_encounter__visit').get(pk=plan_id)
    if plan.origin_encounter.visit.patient_id!=patient.pk:raise PermissionDenied('仅本人可核对此治疗计划。')
    return access.source,patient,plan


def require_plan_service(actor,visit,service,*,lock=False):
    if service.department.clinic_id!=visit.clinic_id or not service.is_active or not service.department.is_active:
        raise RuleError('计划步骤的预约服务不属于本店或已停用，请先核对。')
    professional_scope(actor.pk,visit.clinic_id,service.pk,'RECORD',lock=lock)
