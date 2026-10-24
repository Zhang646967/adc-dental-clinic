"""Actual-work bridge; neither estimates nor decisions post cash."""
from datetime import datetime
from decimal import Decimal
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from adc_core.commands import business_errors
from adc_core.proposals import proposal,read_proposal
from adc_core.rules import RuleError,line_amount
from clinical.encounters import operation
from clinical.plan_locks import lock_plan_visit
from clinical.plan_models import PlanStepVersion,PerformedProcedure,PlanEvent
from clinical.plan_payload import decimal_value,identity,text
from clinical.plans import current_version,latest_decision,bump,event_replay
from clinical.tooth_rules import validate_finding
from clinical.authority import visit_service_id
from clinical.completion import completion_blockers
from registry.models import TreatmentType
from care.models import VisitRecordVersion
from care.audit import emit

ACTUAL_CONTRACT='adc.actual-procedure.c22.v1'
VOID_CONTRACT='adc.actual-procedure-void.c22.v1'


def execution_fields(raw):
    progress=raw.get('progress');mode=raw.get('charge_mode')
    if progress not in ('PARTIAL','COMPLETE') or mode not in ('CHARGE','NO_CHARGE'):raise RuleError('请明确实际完成情况及本次计费方式。')
    row=dict(treatment_type=identity(raw.get('treatment_type'),'实际项目'),quantity=decimal_value(raw.get('quantity'),3,'实际数量'),
        progress=progress,charge_mode=mode,reason=text(raw.get('reason',''),1000,'执行及差异依据'))
    step=raw.get('step_version');row['step_version']=identity(step,'方案步骤') if step not in (None,'') else None
    tooth=raw.get('tooth');surface=raw.get('surface','')
    if tooth not in (None,''):
        f=validate_finding(dict(tooth=identity(tooth,'牙位'),surface=surface,kind='OBSERVATION',detail='实际执行位置'),'MIXED');row.update(tooth=f['tooth'],surface=f['surface'])
    else:
        if surface:raise RuleError('填写实际牙面时请同时明确牙位。')
        row.update(tooth=None,surface='')
    observed=raw.get('observed_at') or timezone.now()
    if isinstance(observed,str):
        try:observed=datetime.fromisoformat(observed)
        except ValueError:raise RuleError('请核对实际执行时间。')
    if not isinstance(observed,datetime) or timezone.is_naive(observed) or observed>timezone.now():raise RuleError('实际执行时间必须明确且不晚于当前时间。')
    row['observed_at']=observed.isoformat()
    if (row['step_version'] is None or mode=='NO_CHARGE') and not row['reason']:raise RuleError('计划外实际处置或本次不另计费时，请说明具体依据。')
    return row


def actual_ready(visit):
    if visit.status!='CHECKED_IN' or not visit.attended_at or visit.attended_at>timezone.now():raise RuleError('请先核对实际到诊，已关闭接诊不能新增执行。')
    if visit_service_id(visit) is None:raise RuleError('本次尚未明确预约服务，请由前台先核对原承诺及资源服务，不能以旧无服务范围代替。')
    blocked=completion_blockers(visit)
    if blocked:raise RuleError(blocked[0])


def checked_step(visit,row,plan=None):
    if row['step_version'] is None:return None
    step=PlanStepVersion.objects.select_related('version__plan','step').get(pk=row['step_version'])
    if plan is not None and step.version.plan_id!=plan.pk:raise PermissionDenied('实际步骤不属于当前治疗计划。')
    origin=step.version.plan.origin_encounter.visit
    if (origin.patient_id,origin.clinic_id)!=(visit.patient_id,visit.clinic_id):raise PermissionDenied('步骤患者或诊所与本次实际就诊不一致。')
    if current_version(step.version.plan).pk!=step.version_id:raise RuleError('此步骤属于旧方案，请核对当前版本及本人决定。')
    decision=latest_decision(step)
    if not decision or decision.decision!='ACCEPTED':raise RuleError('本步骤尚无当前版本的本人认可，请先完成方案讨论。')
    if step.service_id!=visit_service_id(visit):raise RuleError('本次预约服务与计划步骤不一致，请先按实际安排协调。')
    if (step.treatment_type_id,step.tooth,step.surface)!=(row['treatment_type'],row['tooth'],row['surface']):raise RuleError('项目或位置与计划步骤不一致；计划外实际处置须另行明确说明，不能改写原步骤。')
    active=PerformedProcedure.objects.filter(step_version__step=step.step,state='ACTIVE')
    if active.filter(progress='COMPLETE').exists():raise RuleError('此稳定步骤已经实际完成；新的诊疗目标请另建步骤，不能重复开单。')
    if active.filter(encounter__visit=visit).exists():raise RuleError('本次已经记录过此步骤，请核对原结果；误录按明确更正流程办理。')
    return step


def quote(visit,row,step,*,lock=False):
    qs=TreatmentType.objects
    if lock:qs=qs.select_for_update()
    treatment=qs.get(pk=row['treatment_type'],is_active=True)
    if row['charge_mode']=='NO_CHARGE':
        if step is None or step.charge_basis!='ON_COMPLETION' or row['progress']!='PARTIAL':
            raise RuleError('阶段不另计费仅适用于本人已认可的分次完成计费步骤；不能据此免除已提供收费项目。')
    elif step and step.charge_basis=='ON_COMPLETION' and row['progress']=='PARTIAL':
        raise RuleError('此步骤约定完成时计费；请记录当前阶段不另计费，实际提供的其他项目另行确认。')
    amount=line_amount(Decimal(row['quantity']),treatment.standard_unit_price,row['reason']) if row['charge_mode']=='CHARGE' else Decimal('0.00')
    variance=False
    if step and row['charge_mode']=='CHARGE' and step.estimated_unit_price is not None:
        prior=PerformedProcedure.objects.filter(step_version__step=step.step,state='ACTIVE',charge_mode='CHARGE')
        prior_amount=sum(Decimal(r['line_amount']) for r in prior.values_list('charge_snapshot',flat=True))
        estimated=(step.estimated_quantity*step.estimated_unit_price).quantize(Decimal('.01'))
        variance=treatment.standard_unit_price!=step.estimated_unit_price or prior_amount+amount>estimated
        if variance and not row['reason']:raise RuleError('本次价格或累计原开单预计超过讨论估算，请先核对并记录差异依据。')
    return dict(catalogue=treatment.pk,name=treatment.name,unit=treatment.unit_definition,quantity=row['quantity'],
        unit_price=str(treatment.standard_unit_price),line_amount=str(amount),mode=row['charge_mode'],estimate_variance=variance)


def prepare_execution(*,actor,visit_id,fields):
    from clinical.encounter_selectors import encounter_details
    d=encounter_details(actor,visit_id);visit=d['visit']
    if not d['can_record']:raise PermissionDenied('当前没有记录本次实际执行的范围。')
    row=execution_fields(fields);actual_ready(visit);step=checked_step(visit,row);q=quote(visit,row,step)
    observed=datetime.fromisoformat(row['observed_at'])
    if observed<visit.attended_at:raise RuleError('执行发生时间不能早于本次实际到诊。')
    plan=step.version.plan if step else None
    from clinical.lab_readiness import execution_readiness
    readiness=execution_readiness(visit,row,step)
    data=dict(visit=visit.pk,visit_revision=visit.lock_version,source_record=d['current_record'].pk,plan=plan.pk if plan else None,
        plan_revision=plan.revision if plan else None,values=row,quote=q,readiness=readiness)
    return dict(proposal_token=proposal(actor,ACTUAL_CONTRACT,('DENTIST',),data),values=row,quote=q,step=step,readiness=readiness)


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm_execution(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请明确核对实际已提供项目、位置、数量及本次计费。')
    p=read_proposal(actor,ACTUAL_CONTRACT,('DENTIST',),proposal_token);data=p['data']
    visit,patient,head,record,plan=lock_plan_visit(actor,data['visit'],data['plan']);op=operation(p['operation'])
    read_proposal(actor,ACTUAL_CONTRACT,('DENTIST',),proposal_token)
    previous=event_replay(actor,op,'PROCEDURE_RECORDED',plan=plan,encounter=head)
    if previous:return previous.performed,True
    actual_ready(visit)
    if visit.lock_version!=data['visit_revision'] or record.pk!=data['source_record'] or (plan and plan.revision!=data['plan_revision']):raise RuleError('本次接诊、检查或方案决定已变化，请重新核对实际执行。')
    row=execution_fields(data['values']);step=checked_step(visit,row,plan);q=quote(visit,row,step,lock=True)
    from clinical.lab_readiness import execution_readiness
    readiness=execution_readiness(visit,row,step)
    if readiness!=data.get('readiness'):raise RuleError('加工件准备或验收依据已有变化，请重新核对实际执行。')
    if q!=data['quote']:raise RuleError('目录价格或估算差异已变化，请重新预览本次实际开单。')
    observed=datetime.fromisoformat(row['observed_at'])
    if observed<visit.attended_at:raise RuleError('执行发生时间不能早于实际到诊。')
    line=None
    if row['charge_mode']=='CHARGE':
        from care.services import add_treatment
        line=add_treatment(actor=actor,visit_id=visit.pk,expected_version=visit.lock_version,treatment_id=row['treatment_type'],quantity=Decimal(row['quantity']),price_reason=row['reason'],_structured_source=True)
        assert line.line_amount==Decimal(q['line_amount'])
    snapshot=dict(q,original_line=line.pk if line else None,readiness=readiness)
    actual=PerformedProcedure.objects.create(encounter=head,source_record=record,step_version=step,treatment_type_id=row['treatment_type'],quantity=row['quantity'],tooth=row['tooth'],surface=row['surface'],
        progress=row['progress'],charge_mode=row['charge_mode'],reason=row['reason'],charge_line=line,charge_snapshot=snapshot,recorded_by=actor,observed_at=observed,operation_id=op)
    if line is None:
        from care.services import record_no_charge_effect
        record_no_charge_effect(actor=actor,visit_id=visit.pk,expected_version=visit.lock_version,performed_id=actual.pk)
    if plan:bump(plan)
    PlanEvent.objects.create(actor=actor,operation_id=op,action='PROCEDURE_RECORDED',plan=plan,encounter=head,performed=actual,snapshot={'source_record':record.pk,'step':step.pk if step else None,'charge_line':line.pk if line else None,'mode':row['charge_mode']})
    emit(actor,'PROCEDURE_RECORDED',actual,visit=visit,summary={'performed':actual.pk,'step':step.pk if step else None,'mode':actual.charge_mode})
    return actual,False


def prepare_void(*,actor,visit_id,performed_id,reason):
    from clinical.encounter_selectors import encounter_details
    d=encounter_details(actor,visit_id)
    if not d['can_record']:raise PermissionDenied('当前没有本次执行更正范围。')
    actual=PerformedProcedure.objects.get(pk=performed_id,encounter__visit_id=visit_id)
    reason=text(reason,1000,'执行误录的更正依据',True)
    data=dict(visit=visit_id,performed=actual.pk,revision=actual.revision,visit_revision=d['visit'].lock_version,reason=reason)
    return dict(proposal_token=proposal(actor,VOID_CONTRACT,('DENTIST',),data),performed=actual,reason=reason)


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm_void(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请明确核对误录执行及尚未发布的计费影响。')
    p=read_proposal(actor,VOID_CONTRACT,('DENTIST',),proposal_token);data=p['data']
    visit,patient,head,record,_=lock_plan_visit(actor,data['visit']);op=operation(p['operation'])
    actual=PerformedProcedure.objects.select_for_update(of=('self',)).select_related('charge_line__record_version','step_version__version__plan').get(pk=data['performed'],encounter=head)
    plan=actual.step_version.version.plan if actual.step_version_id else None
    if plan:plan=type(plan).objects.select_for_update().get(pk=plan.pk)
    read_proposal(actor,VOID_CONTRACT,('DENTIST',),proposal_token)
    previous=event_replay(actor,op,'PROCEDURE_VOIDED',plan=plan,encounter=head)
    if previous:return previous.performed,True
    if actual.state!='ACTIVE' or actual.revision!=data['revision'] or visit.lock_version!=data['visit_revision']:raise RuleError('执行或接诊状态已变化，请核对当前结果。')
    if visit.status!='CHECKED_IN' or (actual.charge_line_id and actual.charge_line.record_version.state!='DRAFT'):
        raise RuleError('已发布的实际执行不能在此撤回；请保留原事实并按临床更正及独立财务更正流程办理。')
    line=actual.charge_line;actual.state='VOIDED';actual.charge_line=None;actual.revision+=1;actual.save(update_fields=['state','charge_line','revision'])
    if line:
        from care.services import remove_treatment
        remove_treatment(actor=actor,visit_id=visit.pk,expected_version=visit.lock_version,line_id=line.pk,reason=data['reason'])
    else:
        from care.services import record_no_charge_effect
        record_no_charge_effect(actor=actor,visit_id=visit.pk,expected_version=visit.lock_version,performed_id=actual.pk)
    if plan:bump(plan)
    PlanEvent.objects.create(actor=actor,operation_id=op,action='PROCEDURE_VOIDED',plan=plan,encounter=head,performed=actual,note=data['reason'],snapshot={'revision':actual.revision,'original_charge':actual.charge_snapshot})
    emit(actor,'PROCEDURE_VOIDED',actual,visit=visit,summary={'performed':actual.pk,'revision':actual.revision})
    return actual,False
