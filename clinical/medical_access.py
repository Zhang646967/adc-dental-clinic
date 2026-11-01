"""Authority for a specific plan step, never a general chart permission."""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from accounts.policies import require_writable
from clinical.plan_models import PlanStepVersion, TreatmentPlan
from patients.models import Patient
from portal.medical_authority import is_proxy_context, selected_proxy, verify_version
from portal.policies import patient_access


def patient_step(actor, step_id, *, lock=False):
    if is_proxy_context(actor):
        step=PlanStepVersion.objects.select_related('version__plan__origin_encounter__visit__patient','step').get(pk=step_id)
        version=selected_proxy(actor,step=step,lock=lock)
        return step, version.proxy.patient
    access=patient_access(actor,lock=lock,self_only=True)
    step=PlanStepVersion.objects.select_related('version__plan__origin_encounter__visit__patient','step').get(
        pk=step_id,version__plan__origin_encounter__visit__patient_id=access.patient_id)
    return step,access.patient


def lock_proxy_plan(actor,plan_id,step_id):
    require_writable(actor)
    step,patient=patient_step(actor,step_id,lock=True)
    if step.version.plan_id!=plan_id:raise PermissionDenied('医疗授权不包含此方案。')
    patient=Patient.objects.select_for_update().get(pk=patient.pk,is_active=True)
    plan=TreatmentPlan.objects.select_for_update().get(pk=plan_id)
    return selected_proxy(actor,step=step,lock=True),patient,plan
