"""Patient-facing plan facts and the assigned clinician's continuity workspace."""
from decimal import Decimal
from django.db.models import Exists,OuterRef
from django.http import Http404
from django.shortcuts import get_object_or_404
from adc_core.snapshots import reporting_snapshot
from clinical.encounter_selectors import encounter_details,_encounter_details
from clinical.plan_models import TreatmentPlan,PlanDraft,PlanVersion,PlanStepVersion,PerformedProcedure,NextVisitInstruction
from clinical.plan_payload import estimate_totals
from clinical.plans import current_version,version_payload
from clinical.next_visits import instruction_booking_projection
from clinical.plan_locks import plan_services,readable_services,require_plan_scope
from portal.policies import patient_access
from workspaces.context import require_active


def patient_plan_rows(actor):
    require_active(actor,('PATIENT',));access=patient_access(actor,self_only=True)
    return TreatmentPlan.objects.filter(origin_encounter__visit__patient_id=access.patient_id).annotate(
        has_version=Exists(PlanVersion.objects.filter(plan_id=OuterRef('pk')))).filter(has_version=True).select_related('origin_encounter__visit__clinic').order_by('-pk')


def plan_steps(version):
    if version is None:return []
    rows=list(version.steps.select_related('treatment_type','service','step').prefetch_related('decisions','executions').order_by('sequence'))
    stable_ids=[r.step_id for r in rows]
    prior=list(PerformedProcedure.objects.filter(step_version__step_id__in=stable_ids).select_related('encounter__visit','step_version').order_by('pk'))
    for row in rows:
        definition=row.definition_snapshot
        row.definition_retained=definition is not None
        row.saved_catalogue_name=definition['treatment']['name'] if definition else row.treatment_type.name
        row.saved_unit=definition['treatment']['unit'] if definition else row.treatment_type.unit_definition
        row.saved_service_name=definition['service']['name'] if definition else row.service.name
        row.planned_duration=definition['service']['duration'] if definition else None
        decisions=list(row.decisions.all());row.current_decision=max(decisions,key=lambda d:d.pk) if decisions else None
        row.decision_history=sorted(decisions,key=lambda d:d.pk,reverse=True)
        row.actual_history=[p for p in prior if p.step_version.step_id==row.step_id]
        row.is_completed=any(p.state=='ACTIVE' and p.progress=='COMPLETE' for p in row.actual_history)
        from clinical.lab_readiness import step_readiness
        row.readiness=step_readiness(row)
        row.estimate_amount=(row.estimated_quantity*row.estimated_unit_price).quantize(Decimal('.01')) if row.estimated_unit_price is not None else None
    return rows


def selected_version(plan,revision):
    if revision is None:return current_version(plan)
    try:
        number=int(revision)
        if number<1:raise ValueError
        return PlanVersion.objects.get(plan=plan,revision=number)
    except (ValueError,TypeError,PlanVersion.DoesNotExist):raise Http404('未找到所选方案历史版本。')


def self_plan_details(actor,plan_id,*,revision=None):
    with reporting_snapshot():
        plan=get_object_or_404(patient_plan_rows(actor),pk=plan_id);version=selected_version(plan,revision)
        return dict(plan=plan,version=version,steps=plan_steps(version),versions=list(plan.versions.order_by('-revision')),
            is_current=version.pk==current_version(plan).pk,estimate=estimate_totals(version_payload(version)['steps']),
            instructions=list(NextVisitInstruction.objects.filter(source_record__encounter__visit__patient_id=plan.origin_encounter.visit.patient_id,
                source_record__encounter__visit__clinic_id=plan.origin_encounter.visit.clinic_id,state='OPEN').select_related('service')))


def clinician_plans(actor,visit_id):
    d=encounter_details(actor,visit_id);visit=d['visit']
    allowed=readable_services(actor,visit.clinic_id)
    return d,[p for p in _plan_rows(visit) if plan_services(p)<=allowed]


def _plan_rows(visit):
    return TreatmentPlan.objects.filter(origin_encounter__visit__patient_id=visit.patient_id,origin_encounter__visit__clinic_id=visit.clinic_id).select_related('origin_encounter__visit__clinic').order_by('-pk')


def clinician_plan_details(actor,visit_id,plan_id,*,revision=None):
    with reporting_snapshot():
        d=_encounter_details(actor,visit_id);plan=get_object_or_404(_plan_rows(d['visit']),pk=plan_id)
        version=selected_version(plan,revision);draft=PlanDraft.objects.filter(plan=plan).first() if revision is None else None
        require_plan_scope(actor,d['visit'],plan,'READ',version=version,include_draft=revision is None)
        payload=draft.payload if draft else version_payload(version) if version else None
        return dict(d,plan=plan,version=version,draft=draft,plan_payload=payload,steps=plan_steps(version),versions=list(plan.versions.order_by('-revision')),
            plan_revision=plan.revision,is_current=revision is None,estimate=estimate_totals(payload['steps']) if payload else None)


def actual_details(actor,visit_id):
    d=encounter_details(actor,visit_id);visit=d['visit']
    d['actual_rows']=list(PerformedProcedure.objects.filter(encounter__visit=visit).select_related('treatment_type','step_version__version','charge_line__record_version').order_by('-pk'))
    d['instruction_rows']=list(NextVisitInstruction.objects.filter(source_record__encounter__visit__patient_id=visit.patient_id,
        source_record__encounter__visit__clinic_id=visit.clinic_id,service_id__in=readable_services(actor,visit.clinic_id)).select_related('service','step_version').order_by('-pk'))
    return d
