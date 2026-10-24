"""Attributed recall work; contact and appointments never substitute for actual care."""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from accounts.policies import lock_clinic_grant
from adc_core.commands import business_errors
from adc_core.proposals import proposal,read_proposal
from adc_core.rules import RuleError
from care.audit import emit
from clinical.continuity_models import RecallEpisode,RecallEvent
from clinical.continuity_rules import front_clinic,moment,available_front,require_owner
from clinical.encounters import operation
from clinical.models import ClinicalRecordVersion
from clinical.next_visits import current_promise
from clinical.plan_models import NextVisitInstruction,PerformedProcedure
from clinical.plan_payload import text,identity
from clinical.authority import visit_service_id
from patients.models import Patient

CONTRACT='adc.clinical-recall.c23.v1'


def scoped_instructions(actor):
    clinic=front_clinic(actor)
    return NextVisitInstruction.objects.filter(source_record__encounter__visit__clinic_id=clinic).select_related('source_record__encounter__visit__patient','service')


def scoped_episodes(actor):
    clinic=front_clinic(actor)
    return RecallEpisode.objects.filter(instruction__source_record__encounter__visit__clinic_id=clinic).select_related('owner','instruction__service','instruction__source_record__encounter__visit__patient')


def completion_candidates(instruction):
    if instruction.completion_rule=='UNSPECIFIED':return []
    source=instruction.source_record.encounter.visit;rows=[];seen=set()
    for link in instruction.appointment_links.select_related('visit'):
        visit=current_promise(link.visit)
        if visit.pk in seen:continue
        seen.add(visit.pk)
        if visit.pk==source.pk or (visit.patient_id,visit.clinic_id)!=(source.patient_id,source.clinic_id):continue
        if visit.status not in ('COMPLETED','CLOSED_NO_TREATMENT') or visit_service_id(visit)!=instruction.service_id:continue
        facts=[]
        if instruction.completion_rule=='EXAM_CONFIRMED':
            record=ClinicalRecordVersion.objects.filter(encounter__visit=visit,observed_at__gte=instruction.recorded_at).order_by('-revision').first()
            if record:facts.append(('RECORD',record.pk,record.observed_at))
        else:
            facts=[('PERFORMED',r.pk,r.observed_at) for r in PerformedProcedure.objects.filter(encounter__visit=visit,step_version_id=instruction.step_version_id,
                state='ACTIVE',progress='COMPLETE',observed_at__gte=instruction.recorded_at)]
        for kind,pk,actual_at in facts:
            actual_day=timezone.localdate(actual_at)
            if actual_day<instruction.earliest_on:continue
            rows.append(dict(kind=kind,id=pk,visit=visit.pk,visit_no=visit.visit_no,actual_at=actual_at.isoformat(),
                late_days=max((actual_day-instruction.latest_on).days,0)))
    return sorted(rows,key=lambda r:(r['actual_at'],r['id']))


def fields_for(action,raw):
    values=dict(note=text(raw.get('note',''),500,'联系／协调记录',action not in ('OPEN','COMPLETE')))
    if action in ('OPEN','CONTACT','REASSIGN','RESUME'):
        values['followup_due_at']=moment(raw.get('followup_due_at'),'下次内部跟进期限',future=True).isoformat()
    if action=='CONTACT':
        outcome=raw.get('outcome')
        if outcome not in ('REACHED','NO_ANSWER','DECLINED','COORDINATION'):raise RuleError('请选择实际联系结果。')
        values['outcome']=outcome
    if action=='COMPLETE':
        kind=raw.get('evidence_kind')
        if kind not in ('RECORD','PERFORMED'):raise RuleError('请选择已实际完成的复诊依据。')
        values.update(evidence_kind=kind,evidence_id=identity(raw.get('evidence_id'),'实际复诊依据'))
    return values


def selected_evidence(instruction,values):
    item=next((r for r in completion_candidates(instruction) if (r['kind'],r['id'])==(values['evidence_kind'],values['evidence_id'])),None)
    if item is None:raise RuleError('尚无符合医师目标的实际已关闭复诊；联系、预约、到诊或部分执行不能代替完成。')
    return item


def prepare_recall(*,actor,action,instruction_id=None,episode_id=None,fields=None):
    if action not in ('OPEN','CONTACT','REASSIGN','RESUME','COMPLETE','WITHDRAW'):raise RuleError('未知复诊协调操作。')
    values=fields_for(action,fields or {})
    episode=None
    if action=='OPEN':instruction=scoped_instructions(actor).get(pk=instruction_id)
    else:episode=scoped_episodes(actor).get(pk=episode_id);instruction=episode.instruction
    if instruction.completion_rule=='UNSPECIFIED':raise RuleError('原指示尚无明确完成目标，请医师确认新的后续指示；不推断旧记录。')
    data=dict(action=action,instruction=instruction.pk,instruction_revision=instruction.revision,episode=episode.pk if episode else None,
        revision=episode.revision if episode else None,values=values)
    evidence=selected_evidence(instruction,values) if action=='COMPLETE' else None
    if evidence:data['evidence']=evidence
    return dict(proposal_token=proposal(actor,CONTRACT,('FRONT_DESK',),data),instruction=instruction,episode=episode,values=values,evidence=evidence)


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm_recall(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请明确核对就诊人、复诊目标、联系责任及本次结果。')
    p=read_proposal(actor,CONTRACT,('FRONT_DESK',),proposal_token);data=p['data'];clinic=front_clinic(actor)
    lock_clinic_grant(actor,clinic)
    preview=scoped_instructions(actor).get(pk=data['instruction']);source=preview.source_record.encounter.visit
    Patient.objects.select_for_update().get(pk=source.patient_id,is_active=True)
    instruction=NextVisitInstruction.objects.select_for_update().get(pk=preview.pk)
    episode=RecallEpisode.objects.select_for_update().filter(instruction=instruction).first();op=operation(p['operation'])
    read_proposal(actor,CONTRACT,('FRONT_DESK',),proposal_token)
    previous=RecallEvent.objects.filter(operation_id=op).select_related('episode').first()
    if previous:
        if previous.actor_id!=actor.pk or previous.action!=data['action'] or previous.episode.instruction_id!=instruction.pk:raise RuleError('本操作编号已有其他复诊办理结果。')
        return previous.episode,True
    if instruction.revision!=data['instruction_revision']:raise RuleError('后续指示或预约关联已有变化，请核对当前安排。')
    if instruction.completion_rule=='UNSPECIFIED':raise RuleError('需要医师明确后续完成目标，不能推断旧指示。')
    action=data['action'];values=fields_for(action,data['values']);evidence=None
    due=moment(values['followup_due_at'],'下次内部跟进期限',future=True) if 'followup_due_at' in values else None
    if action=='OPEN':
        if episode is not None:raise RuleError('已有联系责任，请查看原复诊任务，不能重复建单。')
        if instruction.state!='OPEN':raise RuleError('后续指示已撤回，不再建立新的联系任务。')
        episode=RecallEpisode.objects.create(instruction=instruction,owner=actor,followup_due_at=due,opened_by=actor)
    else:
        if episode is None or episode.pk!=data['episode'] or episode.revision!=data['revision']:raise RuleError('联系责任或处理进度已有变化，请核对当前结果。')
        if episode.state in ('COMPLETED','WITHDRAWN'):raise RuleError('此复诊事项已有明确结果，保留历史，不重复变更。')
        if action=='REASSIGN':
            if episode.owner_id!=actor.pk and available_front(episode.owner_id,clinic):raise RuleError('原负责人仍在岗，请由原负责人继续协调。')
            episode.owner=actor
        else:require_owner(actor,episode.owner_id,clinic)
        if action=='WITHDRAW':
            if instruction.state!='WITHDRAWN':raise RuleError('只有医师明确撤回的指示才能结束为已撤回；患者暂不继续应记录并转医师核对。')
            episode.state='WITHDRAWN'
        else:
            if instruction.state!='OPEN':raise RuleError('医师已撤回原指示，请核对原预约后明确结束此协调事项。')
            if action=='CONTACT':
                if episode.state=='REVIEW' and values['outcome']!='COORDINATION':raise RuleError('本人暂不继续时先做内部医师核对；重新联系前需明确恢复安排。')
                if values['outcome']=='DECLINED':episode.state='REVIEW'
            elif action=='RESUME':
                if episode.state!='REVIEW':raise RuleError('此事项当前不在待医师核对状态。')
                episode.state='OPEN'
            elif action=='COMPLETE':
                evidence=selected_evidence(instruction,values)
                if evidence!=data['evidence']:raise RuleError('实际复诊依据已有更新，请重新核对。')
                episode.state='COMPLETED';episode.completed_at=timezone.now()
                if evidence['kind']=='RECORD':episode.completion_record_id=evidence['id']
                else:episode.completion_performed_id=evidence['id']
        if due is not None:episode.followup_due_at=due
        episode.revision+=1;episode.save(update_fields=['owner','followup_due_at','state','revision','completed_at','completion_record','completion_performed'])
    snapshot=dict(revision=episode.revision,state=episode.state,owner=episode.owner_id,followup_due_at=str(episode.followup_due_at),outcome=values.get('outcome'),evidence=evidence)
    RecallEvent.objects.create(episode=episode,actor=actor,action=action,note=values['note'],snapshot=snapshot,operation_id=op)
    emit(actor,'CLINICAL_RECALL_'+action,episode,summary={'recall':episode.pk,'state':episode.state,'revision':episode.revision})
    return episode,False
