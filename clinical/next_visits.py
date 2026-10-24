"""Clinical instructions and explicit links to scheduling-owned promises."""
from datetime import date
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from accounts.policies import require_clinic,lock_clinic_grant
from adc_core.commands import business_errors
from adc_core.proposals import proposal,read_proposal
from adc_core.rules import RuleError
from clinical.encounters import operation
from clinical.plan_locks import lock_plan_visit,require_plan_service
from clinical.plan_models import NextVisitInstruction,PlanAppointment,PlanStepVersion,PlanEvent
from clinical.plan_payload import text,identity
from clinical.plans import current_version,event_replay
from clinical.authority import visit_service_id
from patients.models import Patient
from scheduling.coordination import lock_slots
from scheduling.models import Visit,BookingService
from workspaces.context import require_active

CONTRACT='adc.next-visit.c22.v1'


def instruction_fields(raw):
    def day(key):
        value=raw.get(key)
        try:return value if isinstance(value,date) else date.fromisoformat(value)
        except (TypeError,ValueError):raise RuleError('请核对后续就诊起止日期。')
    earliest,latest=day('earliest_on'),day('latest_on')
    if earliest>latest:raise RuleError('建议最晚日期不能早于最早日期。')
    step=raw.get('step_version')
    completion=raw.get('completion_rule')
    if completion not in ('EXAM_CONFIRMED','STEP_COMPLETED') or (completion=='STEP_COMPLETED' and step in (None,'')):
        raise RuleError('请选择医师明确的复诊完成目标；指定步骤完成需同时选择具体步骤。')
    return dict(service=identity(raw.get('service'),'后续服务'),step_version=identity(step,'计划步骤') if step not in (None,'') else None,
        completion_rule=completion,
        earliest_on=earliest.isoformat(),latest_on=latest.isoformat(),
        clinical_purpose=text(raw.get('clinical_purpose',''),1000,'后续诊疗目标',True),
        booking_note=text(raw.get('booking_note',''),500,'前台安排说明'))


def check_instruction_step(visit,values):
    service=BookingService.objects.select_related('department').get(pk=values['service'])
    if values['step_version'] is not None:
        step=PlanStepVersion.objects.select_related('version__plan__origin_encounter__visit').get(pk=values['step_version'])
        origin=step.version.plan.origin_encounter.visit
        if (origin.patient_id,origin.clinic_id)!=(visit.patient_id,visit.clinic_id):raise PermissionDenied('后续步骤与本次患者或诊所不一致。')
        if current_version(step.version.plan).pk!=step.version_id or step.service_id!=service.pk:
            raise RuleError('步骤版本或后续服务已变化，请核对当前方案。')
    return service


def prepare_instruction(*,actor,visit_id,fields):
    from clinical.encounter_selectors import encounter_details
    d=encounter_details(actor,visit_id)
    if not d['can_record'] or d['current_record'] is None:raise PermissionDenied('请由有记录范围的负责医师核对已确认检查。')
    values=instruction_fields(fields);service=check_instruction_step(d['visit'],values)
    require_plan_service(actor,d['visit'],service)
    data=dict(action='CREATE',visit=visit_id,source_record=d['current_record'].pk,values=values)
    return dict(proposal_token=proposal(actor,CONTRACT,('DENTIST',),data),values=values,service=service)


def prepare_withdrawal(*,actor,visit_id,instruction_id,reason):
    from clinical.encounter_selectors import encounter_details
    d=encounter_details(actor,visit_id)
    if not d['can_record']:raise PermissionDenied('没有当前患者的后续指示记录范围。')
    row=NextVisitInstruction.objects.get(pk=instruction_id,source_record__encounter__visit__patient_id=d['visit'].patient_id,
        source_record__encounter__visit__clinic_id=d['visit'].clinic_id)
    from clinical.authority import professional_scope
    professional_scope(actor.pk,d['visit'].clinic_id,row.service_id,'RECORD')
    data=dict(action='WITHDRAW',visit=visit_id,instruction=row.pk,revision=row.revision,reason=text(reason,1000,'撤回指示依据',True))
    return dict(proposal_token=proposal(actor,CONTRACT,('DENTIST',),data),instruction=row,reason=data['reason'])


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm_instruction(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请明确核对后续就诊指示及前台可见说明。')
    p=read_proposal(actor,CONTRACT,('DENTIST',),proposal_token);data=p['data']
    visit,patient,head,record,_=lock_plan_visit(actor,data['visit']);op=operation(p['operation'])
    read_proposal(actor,CONTRACT,('DENTIST',),proposal_token)
    action='NEXT_VISIT_CREATED' if data['action']=='CREATE' else 'NEXT_VISIT_WITHDRAWN'
    old=event_replay(actor,op,action,encounter=head)
    if old:return old.instruction,True
    if data['action']=='CREATE':
        from clinical.completion import completion_blockers
        blocked=completion_blockers(visit)
        if blocked:raise RuleError(blocked[0])
        if record.pk!=data['source_record']:raise RuleError('检查依据已有新版本，请重新预览后续安排。')
        values=instruction_fields(data['values']);service=check_instruction_step(visit,values)
        require_plan_service(actor,visit,service,lock=True)
        values.pop('service');step=values.pop('step_version')
        for key in ('earliest_on','latest_on'):values[key]=date.fromisoformat(values[key])
        row=NextVisitInstruction.objects.create(source_record=record,service=service,step_version_id=step,recorded_by=actor,**values)
        note=''
    else:
        row=NextVisitInstruction.objects.select_for_update().get(pk=data['instruction'],source_record__encounter__visit__patient=patient,
            source_record__encounter__visit__clinic_id=visit.clinic_id)
        from clinical.authority import professional_scope
        professional_scope(actor.pk,visit.clinic_id,row.service_id,'RECORD',lock=True)
        if row.revision!=data['revision'] or row.state!='OPEN':raise RuleError('后续指示已有变化，请核对保留的当前结果。')
        row.state='WITHDRAWN';row.revision+=1;row.save(update_fields=['state','revision']);note=data['reason']
    PlanEvent.objects.create(actor=actor,operation_id=op,action=action,encounter=head,instruction=row,note=note,
        snapshot={'revision':row.revision,'state':row.state,'service':row.service_id})
    from care.audit import emit
    emit(actor,action,row,visit=visit,summary={'instruction':row.pk,'revision':row.revision})
    return row,False


def current_promise(visit):
    """Project the existing unique replacement chain; retain every original link."""
    seen=set()
    while visit.status=='RESCHEDULED':
        if visit.pk in seen:raise RuleError('原改期链需要核对，请从预约记录协调。')
        seen.add(visit.pk)
        replacement=Visit.objects.filter(replaces_visit_id=visit.pk).first()
        if replacement is None:return visit
        visit=replacement
    return visit


def front_instructions(actor):
    require_active(actor,('FRONT_DESK',));clinic_id=actor._adc_workspace.clinic_id
    require_clinic(actor,clinic_id)
    # No clinical purpose, chart, plan estimate or tooth/surface field is projected.
    return NextVisitInstruction.objects.filter(source_record__encounter__visit__clinic_id=clinic_id).select_related('service','source_record__encounter__visit__patient').order_by('latest_on','pk')


def instruction_booking_projection(row):
    visit=row.source_record.encounter.visit
    links=list(row.appointment_links.select_related('visit').order_by('-pk'))
    promises=[dict(original=link.visit,current=current_promise(link.visit)) for link in links]
    fulfilled=has_completed_goal(row)
    return dict(id=row.pk,patient=visit.patient,service=row.service,earliest_on=row.earliest_on,latest_on=row.latest_on,
        booking_note=row.booking_note,state=row.state,revision=row.revision,promises=promises,
        completion_available=fulfilled,
        needs_booking=row.state=='OPEN' and not fulfilled and not any(p['current'].status in ('SCHEDULED','CHECKED_IN') or (row.completion_rule=='UNSPECIFIED' and p['current'].status in ('COMPLETED','CLOSED_NO_TREATMENT')) for p in promises),
        overdue=row.state=='OPEN' and row.latest_on<timezone.localdate())


def has_completed_goal(instruction):
    if instruction.completion_rule=='UNSPECIFIED':return False
    from clinical.recall import completion_candidates
    return bool(completion_candidates(instruction))


def check_promise(row,visit):
    source=row.source_record.encounter.visit
    if (visit.patient_id,visit.clinic_id)!=(source.patient_id,source.clinic_id):raise PermissionDenied('只能关联同一患者在本店的预约。')
    if row.state!='OPEN' or visit.status!='SCHEDULED' or visit.scheduled_start<=timezone.now():raise RuleError('请关联开放指示和仍有效的未来预约。')
    if visit_service_id(visit)!=row.service_id:raise RuleError('预约服务与医师后续指示不一致。')
    day=timezone.localtime(visit.scheduled_start).date()
    if not row.earliest_on<=day<=row.latest_on:raise RuleError('预约日期不在医师建议窗口；请先请医师明确调整指示，保留原承诺。')
    for link in row.appointment_links.select_related('visit'):
        live=current_promise(link.visit)
        protected=live.status in ('SCHEDULED','CHECKED_IN') or (live.status in ('COMPLETED','CLOSED_NO_TREATMENT') and (row.completion_rule=='UNSPECIFIED' or has_completed_goal(row)))
        if live.pk!=visit.pk and protected:
            raise RuleError('已有本指示的有效预约或到诊事实，请先核对原安排，不能重复挂接。')


def prepare_link(*,actor,instruction_id,visit_id):
    require_active(actor,('FRONT_DESK',))
    row=front_instructions(actor).get(pk=instruction_id)
    visit=Visit.objects.get(pk=visit_id,clinic_id=actor._adc_workspace.clinic_id)
    check_promise(row,visit)
    data=dict(action='LINK',instruction=row.pk,revision=row.revision,visit=visit.pk,visit_revision=visit.lock_version)
    return dict(proposal_token=proposal(actor,CONTRACT,('FRONT_DESK',),data),instruction=instruction_booking_projection(row),visit=visit)


@business_errors
@transaction.atomic
def confirm_link(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请核对患者、服务、预约时间和后续日期窗口。')
    p=read_proposal(actor,CONTRACT,('FRONT_DESK',),proposal_token);data=p['data'];ctx=actor._adc_workspace
    lock_clinic_grant(actor,ctx.clinic_id)
    preview=Visit.objects.get(pk=data['visit'],clinic_id=ctx.clinic_id)
    lock_slots([preview.availability_slot_id]);visit=Visit.objects.select_for_update().get(pk=preview.pk)
    Patient.objects.select_for_update().get(pk=visit.patient_id,is_active=True)
    row=NextVisitInstruction.objects.select_for_update().select_related('source_record__encounter__visit').get(pk=data['instruction'],source_record__encounter__visit__clinic_id=ctx.clinic_id)
    read_proposal(actor,CONTRACT,('FRONT_DESK',),proposal_token);op=operation(p['operation'])
    previous=PlanAppointment.objects.filter(operation_id=op).first()
    if previous:
        if previous.linked_by_id!=actor.pk or previous.instruction_id!=row.pk or previous.visit_id!=visit.pk:raise RuleError('本操作编号已有其他关联结果。')
        return previous,True
    if row.revision!=data['revision'] or visit.lock_version!=data['visit_revision']:raise RuleError('指示或预约已有变化，请重新核对。')
    check_promise(row,visit)
    if row.appointment_links.filter(visit=visit).exists():raise RuleError('这个预约已关联本指示，请查看已有结果。')
    link=PlanAppointment.objects.create(instruction=row,visit=visit,linked_by=actor,operation_id=op)
    row.revision+=1;row.save(update_fields=['revision'])
    PlanEvent.objects.create(actor=actor,operation_id=op,action='NEXT_VISIT_LINKED',instruction=row,snapshot={'visit':visit.pk,'revision':row.revision})
    from care.audit import emit
    emit(actor,'NEXT_VISIT_LINKED',row,visit=visit,summary={'instruction':row.pk,'visit':visit.pk})
    return link,False
