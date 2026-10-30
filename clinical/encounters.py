"""Actual encounter, attributed history and retained clinical record commands.

These commands never create treatments, bills, payments or appointment effects.
"""
from datetime import datetime
import uuid
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from adc_core.commands import business_errors
from adc_core.proposals import proposal,read_proposal
from adc_core.rules import RuleError
from accounts.policies import require_writable
from care.audit import emit
from clinical.authority import require_visit_authority
from clinical.locking import lock_clinical_visit
from clinical.models import ClinicalHistoryVersion,ClinicalEncounter,ClinicalDraft,ClinicalRecordVersion,ClinicalRecordEvent,ToothFinding
from clinical.clinical_payload import history_fields,normalize_draft,draft_digest,TEXT_KEYS
from clinical.tooth_rules import validate_finding
from patients.models import Patient
from portal.policies import patient_access
from scheduling.models import Visit
from workspaces.context import require_active

CONTRACT='adc.clinical-record.c21.v1'


def visible_history(patient_id,clinic_id):
    return ClinicalHistoryVersion.objects.filter(patient_id=patient_id).filter(
        Q(source='SELF')|Q(scope_clinic_id=clinic_id)).order_by('-recorded_at','-pk')


def history_cursor(patient_id,clinic_id):
    heads=[ClinicalHistoryVersion.objects.filter(patient_id=patient_id,scope_clinic_id=scope).order_by('-revision').values_list('pk','revision').first()
        for scope in (None,clinic_id)]
    return draft_digest(heads)


def operation(value):
    try:return uuid.UUID(str(value))
    except (ValueError,TypeError,AttributeError):raise RuleError('操作编号无效，请重新打开办理页面。')


def same_event(actor,op,action,*,encounter=None,patient=None,clinic=None):
    event=ClinicalRecordEvent.objects.filter(actor=actor,operation_id=op).select_related('history').first()
    if event:
        if event.action!=action or event.encounter_id!=(encounter.pk if encounter else None):
            raise RuleError('操作编号已经用于其他办理，请重新打开页面。')
        if patient and (not event.history_id or event.history.patient_id!=patient.pk or event.history.scope_clinic_id!=clinic):
            raise RuleError('患者或自述来源已变化，请重新核对。')
    return event


@business_errors
@transaction.atomic
@sensitive_variables()
def submit_history(*,actor,fields,expected_revision,operation_id,confirmed,visit_id=None):
    require_active(actor,('PATIENT','DENTIST'))
    require_writable(actor)
    if confirmed is not True:raise RuleError('请确认本次内容是患者自述，仍须医师另行核对。')
    ctx=actor._adc_workspace
    if ctx.role=='PATIENT':
        if visit_id is not None:raise PermissionDenied('患者自述不能指定其他就诊人或医师面谈来源。')
        authority=patient_access(actor,lock=True,self_only=True)
        patient=Patient.objects.select_for_update().get(pk=authority.patient_id,is_active=True)
        clinic=None;visit=None;source='SELF'
    else:
        if visit_id is None:raise RuleError('请从本次负责接诊记录患者面谈自述。')
        visit=lock_clinical_visit(actor,visit_id)
        if visit.status!='CHECKED_IN' or not visit.attended_at or visit.attended_at>timezone.now():raise RuleError('面谈自述须在本次实际到诊后记录，请核对到诊时间。')
        patient=Patient.objects.select_for_update().get(pk=visit.patient_id,is_active=True)
        clinic=visit.clinic_id;source='INTERVIEW'
    op=operation(operation_id)
    values=history_fields(fields)
    previous_event=same_event(actor,op,'HISTORY_REPORTED',patient=patient,clinic=clinic)
    if previous_event:
        if any(getattr(previous_event.history,key)!=value for key,value in values.items()):
            raise RuleError('同次提交已经保留；新填写内容尚未提交，请核对当前版本后重新办理。')
        return previous_event.history,True
    latest=ClinicalHistoryVersion.objects.filter(patient=patient,scope_clinic_id=clinic).order_by('-revision').first()
    cursor=latest.revision if latest else 0
    if expected_revision!=cursor:raise RuleError('同一来源已有新的自述版本；已填写内容未提交，请核对最新版本后再保存。')
    row=ClinicalHistoryVersion.objects.create(patient=patient,revision=cursor+1,previous=latest,source=source,
        scope_clinic_id=clinic,source_visit=visit,reported_by=actor,**values)
    ClinicalRecordEvent.objects.create(actor=actor,operation_id=op,action='HISTORY_REPORTED',history=row,
        snapshot={'patient':patient.pk,'scope_clinic':clinic,'revision':row.revision,'source':source})
    emit(actor,'CLINICAL_HISTORY_REPORTED',row,visit=visit,summary={'source':source,'revision':row.revision})
    return row,False


@business_errors
@transaction.atomic
def start_encounter(*,actor,visit_id,expected_visit_version,operation_id):
    visit=lock_clinical_visit(actor,visit_id)
    patient=Patient.objects.select_for_update().get(pk=visit.patient_id,is_active=True)
    existing=ClinicalEncounter.objects.select_for_update().filter(visit=visit).first()
    if existing:return existing,True
    if visit.status!='CHECKED_IN' or not visit.attended_at or visit.attended_at>timezone.now():
        raise RuleError('仅已实际到诊的负责就诊可以开始检查记录；预约本身不是诊疗事实。')
    if visit.lock_version!=expected_visit_version:raise RuleError('接诊状态已经变化，请重新核对本次就诊。')
    op=operation(operation_id)
    if ClinicalRecordEvent.objects.filter(operation_id=op).exists():raise RuleError('此操作编号已使用，请重新打开页面。')
    row=ClinicalEncounter.objects.create(visit=visit,opened_by=actor)
    from clinical.documents import open_document
    open_document(row,actor)
    ClinicalRecordEvent.objects.create(actor=actor,operation_id=op,action='ENCOUNTER_OPENED',encounter=row,
        snapshot={'patient':patient.pk,'visit':visit.pk,'revision':0})
    emit(actor,'CLINICAL_ENCOUNTER_OPENED',row,visit=visit,summary={'encounter':row.pk})
    return row,False


def lock_encounter(actor,visit_id):
    visit=lock_clinical_visit(actor,visit_id)
    patient=Patient.objects.select_for_update().get(pk=visit.patient_id,is_active=True)
    row=ClinicalEncounter.objects.select_for_update().get(visit=visit)
    return visit,patient,row


def current_record(encounter):
    return ClinicalRecordVersion.objects.filter(encounter=encounter).order_by('-revision').first()


def record_payload(record):
    return dict(chief_complaint=record.chief_complaint,examination=record.examination,
        history_id=record.history_id,history_review=record.history_review,history_assessment=record.history_assessment,
        history_discrepancy=record.history_discrepancy,dentition=record.dentition,observed_at=record.observed_at.isoformat(),
        amendment_reason='',findings=list(record.findings.values('tooth','surface','kind','detail')))


def check_history(payload,visit):
    if payload['history_id'] is not None and not visible_history(visit.patient_id,visit.clinic_id).filter(pk=payload['history_id']).exists():
        raise PermissionDenied('自述来源不属于当前患者或本店允许核对的范围。')


def edit_digest(action,fields):
    keys={'NOTES':(*TEXT_KEYS,'history_id','history_review','dentition','observed_at'),
        'ADD_FINDING':('tooth','surface','kind','detail'),'REMOVE_FINDING':('line_no',),
        'BEGIN_AMEND':('reason',),'DISCARD':('reason',)}[action]
    data={key:fields[key].isoformat() if isinstance(fields.get(key),datetime) else fields.get(key) for key in keys}
    return draft_digest(data)


@business_errors
@transaction.atomic
@sensitive_variables()
def change_draft(*,actor,visit_id,expected_revision,operation_id,action,fields=None):
    actions={'NOTES','ADD_FINDING','REMOVE_FINDING','BEGIN_AMEND','DISCARD'}
    if action not in actions:raise RuleError('未知检查草稿操作。')
    visit,patient,head=lock_encounter(actor,visit_id)
    op=operation(operation_id);event_action='DRAFT_'+action
    fields=fields or {};intent=edit_digest(action,fields)
    previous_event=same_event(actor,op,event_action,encounter=head)
    if previous_event:
        if previous_event.snapshot.get('intent_digest')!=intent:
            raise RuleError('同次保存已经完成；后来填写的新内容尚未提交，请核对当前草稿后重新办理。')
        return head,True
    if head.revision!=expected_revision:raise RuleError('另一页面已经保存新的版本；本页填写内容仍保留，请核对后继续。')
    draft=ClinicalDraft.objects.select_for_update().filter(encounter=head).first();record=current_record(head)
    note=''
    if action=='BEGIN_AMEND':
        if record is None or draft is not None:raise RuleError('请先核对已确认版本；已有草稿时继续办理原草稿。')
        note=fields.get('reason','').strip()
        if not 4<=len(note)<=500:raise RuleError('请填写4至500字的更正依据。')
        payload=record_payload(record);payload['amendment_reason']=note
        draft=ClinicalDraft(encounter=head,base_record=record,saved_by=actor,payload=payload)
    elif action=='DISCARD':
        if draft is None:raise RuleError('当前没有可放弃的检查草稿。')
        note=fields.get('reason','').strip()
        if not 4<=len(note)<=500:raise RuleError('请明确说明放弃草稿的原因（4至500字）。')
        payload=dict(draft.payload);draft.delete();draft=None
    else:
        if draft is None:
            if record is not None:raise RuleError('已确认内容不能原地修改，请先发起带依据的新更正版本。')
            if visit.status!='CHECKED_IN':raise RuleError('请先核对本次接诊状态。')
            draft=ClinicalDraft(encounter=head,saved_by=actor,payload={})
        payload=dict(draft.payload)
        if action=='NOTES':
            for key in (*TEXT_KEYS,'history_id','history_review','dentition','observed_at'):
                if key in fields:payload[key]=fields[key]
            if not fields.get('observed_at'):
                payload['observed_at']=draft.payload.get('observed_at') or timezone.now().isoformat()
        else:
            payload=normalize_draft(payload)
            if action=='ADD_FINDING':
                payload['findings'].append(validate_finding(fields,payload['dentition']))
            else:
                try:index=int(fields.get('line_no'))-1
                except (ValueError,TypeError):raise RuleError('请选择仍在草稿中的观察条目。')
                if not 0<=index<len(payload['findings']):raise RuleError('观察条目已经变化，请刷新核对。')
                payload['findings'].pop(index);note='移除尚未确认的草稿观察；已确认历史不变。'
        payload=normalize_draft(payload)
    if draft is not None:
        payload=normalize_draft(payload);check_history(payload,visit)
        draft.saved_by=actor;draft.payload=payload;draft.save()
    head.revision+=1;head.save(update_fields=['revision'])
    ClinicalRecordEvent.objects.create(actor=actor,operation_id=op,action=event_action,encounter=head,note=note,
        snapshot={'revision':head.revision,'payload_digest':draft_digest(payload),'intent_digest':intent,'finding_count':len(payload.get('findings',[]))})
    emit(actor,'CLINICAL_DRAFT_CHANGED',head,visit=visit,
        summary={'action':action,'revision':head.revision,'finding_count':len(payload.get('findings',[]))})
    return head,False


def prepare_record(*,actor,visit_id):
    visit=Visit.objects.select_related('patient').get(pk=visit_id)
    require_visit_authority(actor,visit,'RECORD',always=True)
    head=ClinicalEncounter.objects.get(visit=visit);draft=ClinicalDraft.objects.get(encounter=head)
    payload=normalize_draft(draft.payload,complete=True);check_history(payload,visit)
    if payload['history_review']=='UNAVAILABLE' and visible_history(visit.patient_id,visit.clinic_id).exists():
        raise RuleError('已有可核对的患者自述，请选择具体来源并说明核对结论。')
    if draft.base_record_id and not payload['amendment_reason']:raise RuleError('更正版本必须保留明确依据。')
    data=dict(visit=visit.pk,encounter=head.pk,revision=head.revision,digest=draft_digest(payload),
        base_record=draft.base_record_id,history_cursor=history_cursor(visit.patient_id,visit.clinic_id))
    return dict(proposal_token=proposal(actor,CONTRACT,('DENTIST',),data),payload=payload,visit=visit,encounter=head)


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm_record(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请明确核对就诊人、检查内容和本次版本，再确认记录。')
    p=read_proposal(actor,CONTRACT,('DENTIST',),proposal_token);data=p['data']
    visit,patient,head=lock_encounter(actor,data['visit'])
    read_proposal(actor,CONTRACT,('DENTIST',),proposal_token)
    op=operation(p['operation'])
    if same_event(actor,op,'RECORD_CONFIRMED',encounter=head):return head,True
    if head.pk!=data['encounter'] or head.revision!=data['revision']:raise RuleError('检查草稿已经变化，请核对保存的新版本后重新预览。')
    draft=ClinicalDraft.objects.select_for_update().get(encounter=head)
    payload=normalize_draft(draft.payload,complete=True);check_history(payload,visit)
    latest=current_record(head)
    if draft.base_record_id!=(latest.pk if latest else None) or draft.base_record_id!=data['base_record']:
        raise RuleError('更正依据版本已经变化，请先核对当前检查历史。')
    if draft_digest(payload)!=data['digest']:raise RuleError('服务器保存的草稿已变化，请重新预览。')
    if history_cursor(patient.pk,visit.clinic_id)!=data['history_cursor']:
        raise RuleError('患者新增了可核对的自述资料；草稿仍保留，请查看最新来源后重新预览。')
    observed=datetime.fromisoformat(payload['observed_at'])
    if not visit.attended_at or observed<visit.attended_at:raise RuleError('检查发生时间不能早于本次实际到诊。')
    if latest and not 4<=len(payload['amendment_reason'])<=500:raise RuleError('更正版本须保留4至500字依据。')
    row=ClinicalRecordVersion.objects.create(encounter=head,revision=latest.revision+1 if latest else 1,previous=latest,
        history_id=payload['history_id'],recorded_by=actor,observed_at=observed,
        chief_complaint=payload['chief_complaint'],examination=payload['examination'],history_review=payload['history_review'],
        history_assessment=payload['history_assessment'],history_discrepancy=payload['history_discrepancy'],dentition=payload['dentition'],
        history_cursor=data['history_cursor'],
        amendment_reason=payload['amendment_reason'] if latest else '')
    ToothFinding.objects.bulk_create([ToothFinding(record=row,line_no=i,**f) for i,f in enumerate(payload['findings'],1)])
    head.revision+=1;head.save(update_fields=['revision']);draft.delete()
    ClinicalRecordEvent.objects.create(actor=actor,operation_id=op,action='RECORD_CONFIRMED',encounter=head,record=row,
        note=payload['amendment_reason'] if latest else '',snapshot={'revision':head.revision,'record_revision':row.revision,
            'finding_count':len(payload['findings']),'payload_digest':data['digest']})
    emit(actor,'CLINICAL_RECORD_CONFIRMED',row,visit=visit,summary={'revision':row.revision,'finding_count':len(payload['findings'])})
    return head,False
