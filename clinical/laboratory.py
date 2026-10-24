"""Manual laboratory logistics and separately attributed clinical acceptance."""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from accounts.policies import lock_clinic_grant
from adc_core.commands import business_errors
from adc_core.proposals import proposal,read_proposal
from adc_core.rules import RuleError
from care.audit import emit
from clinical.continuity_models import LabCase,LabReview,LabEvent
from clinical.continuity_rules import front_clinic,moment,day,available_front,require_owner
from clinical.encounters import operation,draft_digest
from clinical.encounter_selectors import encounter_details
from clinical.plan_locks import lock_plan_visit,require_plan_service
from clinical.plan_models import PlanStepVersion
from clinical.plan_payload import identity,text
from clinical.plans import current_version,latest_decision
from patients.models import Patient
from workspaces.context import require_active

CONTRACT='adc.manual-laboratory.c23.v1'
CLINICAL_ACTIONS=('CREATE','REVIEW','WITHDRAW')


def front_cases(actor):
    clinic=front_clinic(actor)
    return LabCase.objects.filter(source_record__encounter__visit__clinic_id=clinic).select_related('coordinator','source_record__encounter__visit__patient','step_version__service')


def case_list_digest(step):return draft_digest(list(LabCase.objects.filter(step_version=step).order_by('pk').values_list('pk','revision')))


def fields_for(action,raw):
    if action=='CREATE':
        kind=raw.get('work_kind')
        if kind not in ('RESTORATION','PROSTHESIS','APPLIANCE','OTHER'):raise RuleError('请选择明确的加工类别。')
        return dict(step_version=identity(raw.get('step_version'),'本人已认可的当前方案步骤'),work_kind=kind,
            specification=text(raw.get('specification',''),3000,'医师加工要求',True),vendor_name=text(raw.get('vendor_name',''),120,'手工记录的加工方',True),
            logistics_note=text(raw.get('logistics_note',''),500,'前台送返说明'),needed_on=day(raw.get('needed_on'),'原计划需要日期').isoformat())
    if action=='REVIEW':
        decision=raw.get('decision')
        if decision not in ('ACCEPTED','REWORK'):raise RuleError('请明确当前周期验收通过或返工。')
        values=dict(target_step_version=identity(raw.get('target_step_version'),'核对适配的当前步骤'),decision=decision,
            findings=text(raw.get('findings',''),3000,'医师验收与适配结论',True),coordination_note=text(raw.get('coordination_note',''),500,'前台返工协调说明',decision=='REWORK'),
            assessed_at=moment(raw.get('assessed_at') or timezone.now(),'实际验收时间').isoformat())
        return values
    values=dict(note=text(raw.get('note',''),500,'办理依据与协调记录',True))
    if action in ('CLAIM','DISPATCH','RECEIVE','DELAY'):
        values['followup_due_at']=moment(raw.get('followup_due_at'),'下次内部跟进期限',future=True).isoformat()
    if action in ('DISPATCH','RECEIVE'):
        values.update(reference=text(raw.get('reference',''),500,'手工送返凭据编号',True),occurred_at=moment(raw.get('occurred_at') or timezone.now(),'实际送返时间').isoformat())
    if action=='DELAY':
        values['expected_on']=day(raw['expected_on'],'本次获悉的预计返回日期').isoformat() if raw.get('expected_on') else None
    return values


def checked_target(actor,visit,step_id,*,case=None,lock=False):
    step=PlanStepVersion.objects.select_related('version__plan__origin_encounter__visit','service__department','step').get(pk=step_id)
    origin=step.version.plan.origin_encounter.visit
    if (origin.patient_id,origin.clinic_id)!=(visit.patient_id,visit.clinic_id):raise PermissionDenied('加工步骤与本次患者或诊所不一致。')
    if current_version(step.version.plan).pk!=step.version_id:raise RuleError('方案已有新版本，请核对当前步骤及本人决定。')
    decision=latest_decision(step)
    if decision is None or decision.decision!='ACCEPTED':raise RuleError('本版本步骤尚未获本人认可，不能据此安排或验收加工。')
    if step.requires_lab is not True:raise RuleError('请先在方案明确加工件依赖；旧记录的未知情况不能视为已核对。')
    require_plan_service(actor,visit,step.service,lock=lock)
    from clinical.authority import professional_scope
    professional_scope(actor.pk,visit.clinic_id,step.service_id,'READ',lock=lock)
    if case:
        old=case.step_version
        if (old.step_id,old.treatment_type_id,old.service_id,old.tooth,old.surface)!=(step.step_id,step.treatment_type_id,step.service_id,step.tooth,step.surface):
            raise RuleError('原加工件与当前步骤不是同一兼容目标，请保留原请求并为新目标重新安排。')
    return step


def check_dispatch_target(case):
    latest=case.reviews.order_by('-pk').first()
    step=latest.target_step_version if latest else case.step_version
    decision=latest_decision(step)
    if current_version(step.version.plan).pk!=step.version_id or decision is None or decision.decision!='ACCEPTED':
        raise RuleError('原方案或本人决定已变化，请先由医师明确加工安排，保留原预约。')


def return_time(case):
    event=case.events.filter(action='RECEIVE').order_by('-pk').first()
    if event is None:raise RuleError('尚无本周期实际返回登记，不能将已送出直接视为已验收。')
    return moment(event.snapshot['occurred_at'],'已登记返回时间')


def prepare_lab(*,actor,action,fields=None,case_id=None,visit_id=None):
    if action not in ('CREATE','CLAIM','DISPATCH','RECEIVE','DELAY','REVIEW','WITHDRAW'):raise RuleError('未知加工协调操作。')
    role='DENTIST' if action in CLINICAL_ACTIONS else 'FRONT_DESK';require_active(actor,(role,))
    values=fields_for(action,fields or {});case=None;step=None;source_record=None;plan=None
    if role=='DENTIST':
        if visit_id is None:raise RuleError('请从本人负责的实际检查与后续计划办理。')
        d=encounter_details(actor,visit_id);visit=d['visit']
        if not d['can_record'] or d['current_record'] is None:raise PermissionDenied('需要当前负责患者的记录范围和已确认检查依据。')
        source_record=d['current_record']
        if action!='CREATE':
            case=LabCase.objects.select_related('step_version__step').get(pk=case_id,source_record__encounter__visit__patient_id=visit.patient_id,source_record__encounter__visit__clinic_id=visit.clinic_id)
            if action=='WITHDRAW':
                from clinical.authority import professional_scope
                professional_scope(actor.pk,visit.clinic_id,case.step_version.service_id,'READ')
                professional_scope(actor.pk,visit.clinic_id,case.step_version.service_id,'RECORD')
        if action in ('CREATE','REVIEW'):
            step=checked_target(actor,visit,values['step_version' if action=='CREATE' else 'target_step_version'],case=case);plan=step.version.plan
    else:case=front_cases(actor).get(pk=case_id);visit=None
    data=dict(action=action,visit=visit_id,source_record=source_record.pk if source_record else None,case=case.pk if case else None,
        revision=case.revision if case else None,plan=plan.pk if plan else None,plan_revision=plan.revision if plan else None,
        source_cases_digest=case_list_digest(step) if action=='CREATE' else None,values=values)
    return dict(proposal_token=proposal(actor,CONTRACT,(role,),data),case=case,step=step,values=values,visit=visit)


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm_lab(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请明确核对本次加工件、责任、实际流转或医师验收结论。')
    p=read_proposal(actor,CONTRACT,('DENTIST','FRONT_DESK'),proposal_token);data=p['data'];action=data['action'];case=None;step=None;review=None;head=None
    if action in CLINICAL_ACTIONS:
        require_active(actor,('DENTIST',))
        visit,patient,head,record,plan=lock_plan_visit(actor,data['visit'],data['plan'])
        if data['case'] is not None:
            case=LabCase.objects.select_for_update().get(pk=data['case'],source_record__encounter__visit__patient=patient,source_record__encounter__visit__clinic_id=visit.clinic_id)
            if action=='WITHDRAW':
                from clinical.authority import professional_scope
                professional_scope(actor.pk,visit.clinic_id,case.step_version.service_id,'RECORD',lock=True)
        clinic=visit.clinic_id
    else:
        clinic=front_clinic(actor);lock_clinic_grant(actor,clinic)
        preview=front_cases(actor).get(pk=data['case']);source=preview.source_record.encounter.visit
        patient=Patient.objects.select_for_update().get(pk=source.patient_id,is_active=True)
        case=LabCase.objects.select_for_update().get(pk=preview.pk);plan=None;record=None;visit=None
    read_proposal(actor,CONTRACT,('DENTIST','FRONT_DESK'),proposal_token);op=operation(p['operation'])
    old=LabEvent.objects.filter(operation_id=op).select_related('case').first()
    if old:
        if old.actor_id!=actor.pk or old.action!=action or (case and old.case_id!=case.pk):raise RuleError('本操作编号已有其他加工件办理结果。')
        return old.case,True
    if case and (case.revision!=data['revision'] or case.state=='WITHDRAWN'):raise RuleError('加工件进度已变化或已撤回，请核对当前结果。')
    if action in CLINICAL_ACTIONS and record.pk!=data['source_record']:raise RuleError('本次检查依据已有新版本，请重新核对加工安排。')
    values=fields_for(action,data['values']);note=values.get('note','');snapshot=dict(source_kind='MANUAL_OPERATOR_ENTRY')
    if action=='CREATE':
        step=checked_target(actor,visit,values['step_version'],lock=True)
        if plan.revision!=data['plan_revision'] or case_list_digest(step)!=data['source_cases_digest']:raise RuleError('方案决定或加工请求列表已有变化，请先核对原请求，不能重复建单。')
        v=dict(values);v.pop('step_version');v['needed_on']=day(v['needed_on'],'原需要日期')
        case=LabCase.objects.create(source_record=record,step_version=step,requester=actor,**v)
    else:
        due=moment(values['followup_due_at'],'下次内部跟进期限',future=True) if 'followup_due_at' in values else None
        if action=='CLAIM':
            if case.coordinator_id and case.coordinator_id!=actor.pk and available_front(case.coordinator_id,clinic):raise RuleError('原加工协调负责人仍在岗，请由原负责人继续。')
            case.coordinator=actor
        elif action in ('DISPATCH','DELAY'):require_owner(actor,case.coordinator_id,clinic)
        if action=='DISPATCH':
            if case.state not in ('REQUESTED','REWORK'):raise RuleError('只有待送出或明确返工的加工件可以登记新的送出周期。')
            check_dispatch_target(case);case.state='DISPATCHED';case.cycle+=1
            snapshot.update(reference=values['reference'],occurred_at=values['occurred_at'])
        elif action=='RECEIVE':
            if case.state!='DISPATCHED':raise RuleError('请先核对本周期原送出记录；返回登记不代表临床验收。')
            dispatch=case.events.filter(action='DISPATCH').order_by('-pk').first()
            if dispatch is None or moment(values['occurred_at'],'实际返回时间')<moment(dispatch.snapshot['occurred_at'],'原送出时间'):
                raise RuleError('实际返回时间不能早于本周期送出。')
            case.state='RECEIVED';snapshot.update(reference=values['reference'],occurred_at=values['occurred_at'])
        elif action=='DELAY':
            if case.state not in ('REQUESTED','DISPATCHED','REWORK'):raise RuleError('此加工件当前不在待送返状态，请核对原进度。')
            snapshot['expected_on']=values['expected_on']
        elif action=='REVIEW':
            if case.state not in ('RECEIVED','ACCEPTED'):raise RuleError('请先登记实际返回；返工后需再次送返，不能直接改为通过。')
            step=checked_target(actor,visit,values['target_step_version'],case=case,lock=True)
            if plan.revision!=data['plan_revision']:raise RuleError('本人决定或方案已有变化，请重新核对当前步骤。')
            assessed=moment(values['assessed_at'],'实际验收时间')
            if assessed<return_time(case):raise RuleError('实际验收时间不能早于本周期返回登记。')
            last=case.reviews.filter(target_step_version=step,cycle=case.cycle).order_by('-pk').first()
            if case.state=='ACCEPTED' and values['decision']=='ACCEPTED' and last and last.decision=='ACCEPTED':raise RuleError('这个版本步骤已有本周期的验收结果，请查看原记录。')
            review=LabReview.objects.create(case=case,target_step_version=step,source_record=record,reviewer=actor,cycle=case.cycle,
                decision=values['decision'],findings=values['findings'],coordination_note=values['coordination_note'],assessed_at=assessed,operation_id=op)
            case.state='ACCEPTED' if review.decision=='ACCEPTED' else 'REWORK';note=values['coordination_note']
            snapshot.update(target_step=step.pk,review=review.pk)
        elif action=='WITHDRAW':case.state='WITHDRAWN'
        if due is not None:case.followup_due_at=due
        case.revision+=1;case.save(update_fields=['state','revision','cycle','coordinator','followup_due_at'])
    snapshot.update(revision=case.revision,state=case.state,cycle=case.cycle,coordinator=case.coordinator_id)
    LabEvent.objects.create(case=case,actor=actor,action=action,note=note,snapshot=snapshot,review=review,operation_id=op)
    emit(actor,'LAB_'+action,case,visit=visit,summary={'case':case.pk,'state':case.state,'revision':case.revision,'cycle':case.cycle})
    return case,False
