"""Plan and decision commands; estimates never create actual treatment."""
from decimal import Decimal
import uuid
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from adc_core.commands import business_errors
from adc_core.proposals import proposal,read_proposal
from adc_core.rules import RuleError
from clinical.encounters import operation,draft_digest
from clinical.plan_locks import lock_plan_visit,lock_self_plan,require_plan_service,require_plan_scope
from clinical.plan_models import TreatmentPlan,PlanDraft,PlanVersion,TreatmentStep,PlanStepVersion,PlanDecision,PerformedProcedure,PlanEvent
from clinical.plan_payload import normalize_plan,step_fields
from scheduling.resource_models import BookingService
from care.audit import emit
from workspaces.context import require_active

PLAN_CONTRACT='adc.treatment-plan.c22.v1'
DECISION_CONTRACT='adc.plan-decision.c22.v1'


def current_version(plan):return PlanVersion.objects.filter(plan=plan).order_by('-revision').first()
def latest_decision(step):return PlanDecision.objects.filter(step_version=step).order_by('-pk').first()


def event_replay(actor,op,action,*,plan=None,encounter=None):
    event=PlanEvent.objects.filter(operation_id=op).first()
    if event and (event.actor_id!=actor.pk or event.action!=action or (plan and event.plan_id!=plan.pk) or (encounter and event.encounter_id!=encounter.pk)):
        raise RuleError('该操作编号已经办理其他事项，请重新核对当前页面。')
    return event


def append_event(actor,op,action,*,plan=None,encounter=None,decision=None,note='',snapshot=None):
    row=PlanEvent.objects.create(actor=actor,operation_id=op,action=action,plan=plan,encounter=encounter,decision=decision,note=note,snapshot=snapshot or {})
    emit(actor,action,row,visit=encounter.visit if encounter else None,summary={'plan':plan.pk if plan else None,'decision':decision.pk if decision else None})
    return row


def bump(plan):
    plan.revision+=1;plan.save(update_fields=['revision'])


def version_payload(version):
    rows=[]
    for row in version.steps.select_related('step').order_by('sequence'):
        rows.append(dict(step_key=str(row.step.step_key),treatment_type=row.treatment_type_id,service=row.service_id,
            description=row.description,goal=row.goal,tooth=row.tooth,surface=row.surface,
            estimated_quantity=str(row.estimated_quantity),estimated_unit_price=str(row.estimated_unit_price) if row.estimated_unit_price is not None else None,
            estimate_note=row.estimate_note,alternative_group=row.alternative_group,charge_basis=row.charge_basis,requires_lab=row.requires_lab))
    from clinical.disclosures import retained
    return dict(summary=version.summary,discussion_note=version.discussion_note,amendment_reason='',steps=rows,disclosures=retained(version))


@business_errors
@transaction.atomic
def start_plan(*,actor,visit_id,operation_id):
    visit,patient,head,record,_=lock_plan_visit(actor,visit_id)
    op=operation(operation_id);previous=event_replay(actor,op,'PLAN_OPENED',encounter=head)
    if previous:return previous.plan,True
    from clinical.completion import completion_blockers
    blocked=completion_blockers(visit)
    if blocked:raise RuleError(blocked[0])
    plan=TreatmentPlan.objects.create(origin_encounter=head,opened_by=actor)
    PlanDraft.objects.create(plan=plan,source_record=record,saved_by=actor,payload=normalize_plan({}))
    append_event(actor,op,'PLAN_OPENED',plan=plan,encounter=head,snapshot={'source_record':record.pk})
    return plan,False


@business_errors
@transaction.atomic
@sensitive_variables()
def change_plan(*,actor,visit_id,plan_id,expected_revision,operation_id,action,fields=None):
    if action not in ('NOTES','ADD_STEP','UPDATE_STEP','REMOVE_STEP','BEGIN_AMEND','DISCARD','REFRESH_SOURCE','DISCLOSURE'):raise RuleError('未知治疗计划操作。')
    visit,patient,head,record,plan=lock_plan_visit(actor,visit_id,plan_id)
    require_plan_scope(actor,visit,plan,'RECORD',lock=True)
    op=operation(operation_id);fields=fields or {};intent=draft_digest({'action':action,'fields':fields})
    previous=event_replay(actor,op,'PLAN_'+action,plan=plan)
    if previous:
        if previous.snapshot.get('intent_digest')!=intent:raise RuleError('原提交已保存；新填写内容仍未提交，请核对当前草稿后继续。')
        return plan,True
    if plan.revision!=expected_revision:raise RuleError('计划或患者决定已有更新，本页填写未提交，请比较当前版本后继续。')
    draft=PlanDraft.objects.select_for_update().filter(plan=plan).first();published=current_version(plan);reason=''
    if action=='BEGIN_AMEND':
        if draft is not None or published is None:raise RuleError('请继续已有草稿，或先核对已发布方案。')
        reason=str(fields.get('reason','')).strip()
        if not 4<=len(reason)<=500:raise RuleError('请填写4至500字的新版本依据。')
        payload=version_payload(published);payload['amendment_reason']=reason
        draft=PlanDraft(plan=plan,source_record=record,base_version=published,saved_by=actor,payload=payload)
    else:
        if draft is None:raise RuleError('当前没有工作草稿；已发布方案应另建带依据的新版本。')
        payload=normalize_plan(draft.payload)
        if action=='DISCARD':
            reason=str(fields.get('reason','')).strip()
            if not 4<=len(reason)<=500:raise RuleError('请填写4至500字的放弃依据。')
            draft.delete();draft=None
        elif action=='NOTES':
            for key in ('summary','discussion_note','amendment_reason'):
                if key in fields:payload[key]=fields[key]
        elif action=='ADD_STEP':
            values=dict(fields,step_key=str(uuid.uuid4()));payload['steps'].append(step_fields(values))
        elif action in ('UPDATE_STEP','REMOVE_STEP'):
            try:index=int(fields.get('sequence'))-1
            except (ValueError,TypeError):raise RuleError('请选择当前草稿中的步骤。')
            if not 0<=index<len(payload['steps']):raise RuleError('步骤已变化，请重新核对。')
            if action=='REMOVE_STEP':
                removed=payload['steps'].pop(index);payload['disclosures'].pop(removed['step_key'],None)
            else:payload['steps'][index]=step_fields(dict(fields,step_key=payload['steps'][index]['step_key']))
        elif action=='DISCLOSURE':
            from clinical.disclosures import content,scope_digest
            try:index=int(fields.get('sequence'))-1
            except (ValueError,TypeError):raise RuleError('请从当前草稿的具体步骤准备治疗说明。')
            if not 0<=index<len(payload['steps']) or str(fields.get('step_key',''))!=payload['steps'][index]['step_key']:
                raise RuleError('治疗说明对应步骤已变化，请返回当前步骤核对；本页填写未保存。')
            row=payload['steps'][index];notice=content(fields)
            if notice['prepared'] and not payload['summary']:raise RuleError('请先保存方案摘要，再完成本步骤的治疗说明。')
            validate_steps(actor,visit,plan,[row],lock=True)
            definition=definition_bundle([row],lock=True)[row['step_key']]
            notice.update(scope_digest=scope_digest(row,summary=payload['summary'],source_record=draft.source_record_id,definition=definition),
                prepared_by=actor.pk,prepared_by_name=actor.dentist.name,prepared_at=timezone.now().isoformat())
            payload['disclosures'][row['step_key']]=notice
        elif action=='REFRESH_SOURCE':draft.source_record=record
    if draft is not None:
        payload=normalize_plan(payload)
        if action in ('ADD_STEP','UPDATE_STEP'):
            validate_steps(actor,visit,plan,[payload['steps'][-1] if action=='ADD_STEP' else payload['steps'][index]],lock=True)
        draft.payload=payload;draft.saved_by=actor;draft.save()
    bump(plan);append_event(actor,op,'PLAN_'+action,plan=plan,encounter=head,note=reason,snapshot={'revision':plan.revision,'intent_digest':intent,'draft_digest':draft_digest(payload)})
    return plan,False


def validate_steps(actor,visit,plan,rows,*,lock=False):
    from registry.models import TreatmentType
    for row in rows:
        if not TreatmentType.objects.filter(pk=row['treatment_type'],is_active=True).exists():raise RuleError('部分治疗目录已停用，请先核对计划。')
        service=BookingService.objects.select_related('department').get(pk=row['service'])
        require_plan_service(actor,visit,service,lock=lock)
        stable=TreatmentStep.objects.filter(step_key=row['step_key']).first()
        if stable and stable.plan_id!=plan.pk:raise PermissionDenied('步骤标识不属于当前治疗计划。')
        if stable and PerformedProcedure.objects.filter(step_version__step=stable,state='ACTIVE').exists():
            old=PlanStepVersion.objects.filter(step=stable).order_by('-version__revision').first()
            if any(getattr(old,field)!=row[key] for field,key in [('treatment_type_id','treatment_type'),('service_id','service'),('tooth','tooth'),('surface','surface')]):
                raise RuleError('已有实际执行的步骤不能改变项目、服务或位置；新目标请另建步骤，原执行仍保留。')


def definition_bundle(rows,*,lock=False):
    from registry.models import TreatmentType
    types=TreatmentType.objects.filter(pk__in={r['treatment_type'] for r in rows}).order_by('pk')
    services=BookingService.objects.filter(pk__in={r['service'] for r in rows}).select_related('department').order_by('pk')
    if lock:types=types.select_for_update();services=services.select_for_update(of=('self',))
    types={r.pk:r for r in types};services={r.pk:r for r in services};result={}
    for row in rows:
        t=types.get(row['treatment_type']);s=services.get(row['service'])
        if t is None or s is None or not t.is_active or not s.is_active or not s.department.is_active:
            raise RuleError('方案目录或科室已变化，请核对当前可用定义。')
        result[row['step_key']]=dict(treatment=dict(id=t.pk,code=t.code,name=t.name,unit=t.unit_definition),
            service=dict(id=s.pk,code=s.code,name=s.name,duration=s.duration_minutes,department_id=s.department_id,department_name=s.department.name))
    return result


def prepare_plan(*,actor,visit_id,plan_id):
    from clinical.encounter_selectors import encounter_details
    details=encounter_details(actor,visit_id);plan=TreatmentPlan.objects.select_related('origin_encounter__visit').get(pk=plan_id)
    source=plan.origin_encounter.visit;visit=details['visit']
    if source.patient_id!=visit.patient_id or source.clinic_id!=visit.clinic_id:raise PermissionDenied('当前患者或诊所不匹配。')
    if not details['can_record']:raise PermissionDenied('当前没有记录本次计划的专业范围。')
    require_plan_scope(actor,visit,plan,'RECORD')
    draft=PlanDraft.objects.get(plan=plan);payload=normalize_plan(draft.payload,complete=True)
    validate_steps(actor,visit,plan,payload['steps'])
    definitions=definition_bundle(payload['steps'])
    from clinical.disclosures import validate_prepared
    validate_prepared(payload,source_record=draft.source_record_id,definitions=definitions)
    data=dict(visit=visit.pk,plan=plan.pk,revision=plan.revision,source_record=draft.source_record_id,base_version=draft.base_version_id,digest=draft_digest(payload),definition_digest=draft_digest(definitions))
    return dict(proposal_token=proposal(actor,PLAN_CONTRACT,('DENTIST',),data),payload=payload,definitions=definitions)


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm_plan(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请核对本次方案版本及估算说明后明确确认。')
    p=read_proposal(actor,PLAN_CONTRACT,('DENTIST',),proposal_token);data=p['data']
    visit,patient,head,record,plan=lock_plan_visit(actor,data['visit'],data['plan'])
    require_plan_scope(actor,visit,plan,'RECORD',lock=True)
    read_proposal(actor,PLAN_CONTRACT,('DENTIST',),proposal_token);op=operation(p['operation'])
    previous=event_replay(actor,op,'PLAN_CONFIRMED',plan=plan)
    if previous:return PlanVersion.objects.get(pk=previous.snapshot['version']),True
    # Confirm only against a current, reviewed clinical source.
    from clinical.completion import completion_blockers
    blocked=completion_blockers(visit)
    if blocked:raise RuleError(blocked[0])
    draft=PlanDraft.objects.select_for_update().get(plan=plan);latest=current_version(plan)
    payload=normalize_plan(draft.payload,complete=True)
    if plan.revision!=data['revision'] or draft_digest(payload)!=data['digest']:raise RuleError('方案草稿或患者决定已有更新，请重新预览。')
    if draft.base_version_id!=(latest.pk if latest else None) or draft.base_version_id!=data['base_version']:raise RuleError('方案依据版本已变化，请重新核对。')
    if draft.source_record_id!=record.pk or draft.source_record_id!=data['source_record']:raise RuleError('检查记录已有新版本，请先刷新方案依据再确认。')
    if latest and not 4<=len(payload['amendment_reason'])<=500:raise RuleError('新方案版本必须保留明确依据。')
    validate_steps(actor,visit,plan,payload['steps'],lock=True)
    definitions=definition_bundle(payload['steps'],lock=True)
    from clinical.disclosures import validate_prepared
    validate_prepared(payload,source_record=draft.source_record_id,definitions=definitions)
    if draft_digest(definitions)!=data.get('definition_digest'):raise RuleError('服务名称、时长或目录定义已变化，请重新预览后再确认。')
    version=PlanVersion.objects.create(plan=plan,revision=latest.revision+1 if latest else 1,previous=latest,source_record=record,recorded_by=actor,summary=payload['summary'],discussion_note=payload['discussion_note'],disclosures=payload['disclosures'],amendment_reason=payload['amendment_reason'] if latest else '')
    for index,row in enumerate(payload['steps'],1):
        row=dict(row);key=row.pop('step_key');stable=TreatmentStep.objects.filter(step_key=key).first()
        if stable is None:stable=TreatmentStep.objects.create(plan=plan,step_key=key,created_by=actor)
        PlanStepVersion.objects.create(version=version,step=stable,sequence=index,treatment_type_id=row.pop('treatment_type'),service_id=row.pop('service'),definition_snapshot=definitions[key],**row)
    draft.delete();bump(plan)
    append_event(actor,op,'PLAN_CONFIRMED',plan=plan,encounter=head,snapshot={'version':version.pk,'revision':version.revision,'steps':len(payload['steps']),'digest':data['digest']})
    return version,False


def decision_fields(fields):
    decision=fields.get('decision')
    if decision not in ('ACCEPTED','DEFERRED','DECLINED'):raise RuleError('请选择本步骤的明确决定。')
    reference=str(fields.get('reference','')).strip();note=str(fields.get('note','')).strip()
    if len(reference)>500 or len(note)>1000:raise RuleError('决定依据或说明过长，请整理后提交。')
    if decision in ('DEFERRED','DECLINED') and not note:raise RuleError('暂缓或不选择时请说明后续安排或原因。')
    return dict(decision=decision,reference=reference,note=note)


def prepare_decision(*,actor,step_id,fields,visit_id=None):
    require_active(actor,('PATIENT','DENTIST'))
    values=decision_fields(fields);ctx=actor._adc_workspace
    if ctx.role=='PATIENT':
        from portal.policies import patient_access
        access=patient_access(actor,self_only=True)
        step=PlanStepVersion.objects.select_related('version__plan__origin_encounter__visit').get(pk=step_id,version__plan__origin_encounter__visit__patient_id=access.patient_id)
        plan=step.version.plan;source='SELF';visit_id=None
    else:
        from clinical.encounter_selectors import encounter_details
        if visit_id is None:raise RuleError('请从当前负责就诊记录本人表态。')
        details=encounter_details(actor,visit_id);v=details['visit']
        if not details['can_record']:raise PermissionDenied('当前没有记录此患者表态的范围。')
        step=PlanStepVersion.objects.select_related('version__plan__origin_encounter__visit').get(pk=step_id,version__plan__origin_encounter__visit__patient_id=v.patient_id,version__plan__origin_encounter__visit__clinic_id=v.clinic_id)
        plan=step.version.plan
        from clinical.authority import professional_scope
        professional_scope(actor.pk,v.clinic_id,step.service_id,'READ')
        professional_scope(actor.pk,v.clinic_id,step.service_id,'RECORD')
        if not values['reference']:raise RuleError('请注明患者本人表态的依据或沟通记录编号。')
        source='MANUAL'
    if current_version(plan).pk!=step.version_id:raise RuleError('患者讨论的方案已有新版本，请核对当前步骤。')
    data=dict(plan=plan.pk,step=step.pk,version=step.version_id,revision=plan.revision,source=source,visit=visit_id,values=values)
    return dict(proposal_token=proposal(actor,DECISION_CONTRACT,('PATIENT','DENTIST'),data),step=step,values=values)


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm_decision(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请核对具体方案版本及步骤后明确确认。')
    p=read_proposal(actor,DECISION_CONTRACT,('PATIENT','DENTIST'),proposal_token);data=p['data']
    if data['source']=='SELF':
        access,patient,plan=lock_self_plan(actor,data['plan']);head=None;visit=None
    else:
        visit,patient,head,record,plan=lock_plan_visit(actor,data['visit'],data['plan']);access=None
    read_proposal(actor,DECISION_CONTRACT,('PATIENT','DENTIST'),proposal_token);op=operation(p['operation'])
    previous=event_replay(actor,op,'PLAN_DECIDED',plan=plan)
    if previous:return previous.decision,True
    step=PlanStepVersion.objects.select_related('version','step').get(pk=data['step'],version__plan=plan)
    if data['source']=='MANUAL':
        from clinical.authority import professional_scope
        professional_scope(actor.pk,visit.clinic_id,step.service_id,'RECORD',lock=True)
    if plan.revision!=data['revision'] or current_version(plan).pk!=data['version'] or step.version_id!=data['version']:
        raise RuleError('方案或已有决定已变化，请重新核对当前版本。')
    values=decision_fields(data['values'])
    if values['decision']=='ACCEPTED' and step.alternative_group:
        for other in step.version.steps.filter(alternative_group=step.alternative_group).exclude(pk=step.pk):
            decision=latest_decision(other)
            if decision and decision.decision=='ACCEPTED':raise RuleError('同一互斥组选项已有认可步骤，请先明确暂缓或不选择原选项。')
    row=PlanDecision.objects.create(step_version=step,actor=actor,source=data['source'],self_access=access,source_visit=visit,operation_id=op,**values)
    bump(plan);append_event(actor,op,'PLAN_DECIDED',plan=plan,encounter=head,decision=row,snapshot={'version':step.version_id,'step':step.pk,'decision':row.decision,'source':row.source,'revision':plan.revision})
    return row,False
