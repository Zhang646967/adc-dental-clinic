"""C3.1 document operations. Existing clinical and financial owners stay intact."""
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from care.audit import emit
from care.models import VisitRecordVersion
from clinical.authority import require_visit_authority
from clinical.encounters import current_record, history_cursor, lock_encounter, operation
from clinical.clinical_payload import draft_digest
from clinical.document_models import ClinicalDocument, ClinicalDocumentDraft, ClinicalDocumentVersion, ClinicalDocumentEvent
from clinical.models import ClinicalEncounter
from clinical.plan_models import PerformedProcedure, PlanVersion, TreatmentPlan
from clinical.plan_locks import require_plan_scope
from scheduling.models import Visit

CONTRACT = 'adc.clinical-document.c31.v1'
TEXT_FIELDS = {'diagnosis': 2000, 'ancillary_results': 2000, 'instructions': 2000,
               'follow_up': 1000, 'prior_context': 1000, 'amendment_reason': 500,
               'late_reason': 500, 'evidence_reference': 500}
CLOSED = ('COMPLETED', 'CLOSED_NO_TREATMENT')


def open_document(encounter, actor):
    """Called by a locked command; only new encounters get automatic work items."""
    hours = getattr(settings, 'ADC_CLINICAL_DOCUMENT_DUE_HOURS', 24)
    return ClinicalDocument.objects.get_or_create(encounter=encounter, defaults={
        'responsible': actor, 'due_at': timezone.now() + timedelta(hours=hours)})[0]


def latest_version(document):
    return ClinicalDocumentVersion.objects.filter(document=document).order_by('-revision').first()


def active_deadline(document):
    return document.review_due_at or document.due_at


def normalize(data, *, complete=False):
    result = {}
    for key, limit in TEXT_FIELDS.items():
        value = data.get(key, '')
        if not isinstance(value, str) or len(value.strip()) > limit:
            raise RuleError(f'文书说明超过允许长度（{limit}字），请核对后保存。')
        result[key] = value.strip()
    result['kind'] = data.get('kind', 'INITIAL')
    result['evidence_kind'] = data.get('evidence_kind', 'ACCOUNT_CONFIRMATION')
    if result['kind'] not in ('INITIAL', 'FOLLOWUP') or result['evidence_kind'] not in ('ACCOUNT_CONFIRMATION', 'PAPER_REFERENCE'):
        raise RuleError('请选择有效的文书类别和确认凭据类型。')
    try:
        result['prior_visit_version'] = int(data['prior_visit_version']) if data.get('prior_visit_version') else None
    except (ValueError, TypeError):
        raise RuleError('请选择本人有权查阅的既往文书版本。')
    if complete:
        if any(not result[k] for k in ('diagnosis', 'instructions', 'follow_up')):
            raise RuleError('确认前请补齐诊断／判断、离诊医嘱和复诊安排；无须复诊也请明确说明。')
        if result['kind'] == 'INITIAL' and result['prior_visit_version']:
            raise RuleError('初诊文书不关联复诊来源；请核对文书类别。')
        if result['kind'] == 'FOLLOWUP' and not result['prior_visit_version'] and not result['prior_context']:
            raise RuleError('复诊请选择既往准确版本，或说明院外／纸质既往资料及本次变化。')
        if result['evidence_kind'] == 'PAPER_REFERENCE' and not result['evidence_reference']:
            raise RuleError('请登记纸质原件的保管位置和对应确认凭据。')
        if result['evidence_kind'] == 'ACCOUNT_CONFIRMATION' and result['evidence_reference']:
            raise RuleError('账号确认不能登记成纸质原件；请核对凭据类型。')
    return result


def check_prior(actor, visit, payload):
    pk = payload['prior_visit_version']
    if not pk:
        return None
    previous = ClinicalDocumentVersion.objects.select_related('document__encounter__visit').filter(pk=pk).first()
    if previous is None:
        raise RuleError('既往文书版本不存在，请重新选择。')
    prior = previous.document.encounter.visit
    require_visit_authority(actor, prior, 'READ', always=True)
    if prior.patient_id != visit.patient_id or prior.clinic_id != visit.clinic_id or prior.pk == visit.pk:
        raise PermissionDenied('复诊来源必须属于当前患者、本店另一实际就诊。')
    if prior.attended_at is None or visit.attended_at is None or prior.attended_at >= visit.attended_at:
        raise RuleError('复诊来源须是本次到诊前的既往就诊。')
    return previous


def source_projection(actor, visit, encounter):
    record = current_record(encounter)
    if record is None:
        raise RuleError('请先确认本次检查记录，再整理完整病历文书。')
    care = VisitRecordVersion.objects.filter(visit=visit).exclude(state='ABANDONED').filter(
        Q(correction_request__isnull=True) | Q(state='PUBLISHED')).order_by('-revision_no').first()
    procedures = list(PerformedProcedure.objects.filter(encounter=encounter).order_by('pk'))
    actual = [dict(id=p.pk, revision=p.revision, state=p.state, name=p.charge_snapshot.get('name', ''),
                   tooth=p.tooth, surface=p.surface, quantity=str(p.quantity), progress=p.progress,
                   observed_at=p.observed_at.isoformat(), recorded_at=p.recorded_at.isoformat(),
                   source_record=p.source_record_id, reason=p.reason) for p in procedures]
    plans = []
    for plan in TreatmentPlan.objects.filter(origin_encounter=encounter).order_by('pk'):
        version = PlanVersion.objects.filter(plan=plan).order_by('-revision').first()
        if version:
            require_plan_scope(actor, visit, plan, 'READ', version=version, include_draft=False)
            plans.append(dict(id=plan.pk, version=version.pk, revision=version.revision, summary=version.summary))
    history = record.history
    snapshot = dict(
        header=dict(patient_id=visit.patient_id, patient_no=visit.patient.patient_no, patient_name=visit.patient.name,
                    clinic_id=visit.clinic_id, clinic_name=visit.clinic.name, dentist_id=visit.dentist_id,
                    dentist_name=visit.dentist.name, employee_no=visit.dentist.employee_no, visit_no=visit.visit_no),
        visit=dict(id=visit.pk, status=visit.status, attended_at=visit.attended_at.isoformat() if visit.attended_at else None,
                   completed_at=visit.completed_at.isoformat() if visit.completed_at else None),
        record=dict(id=record.pk, revision=record.revision, observed_at=record.observed_at.isoformat(),
                    recorded_at=record.recorded_at.isoformat(), chief_complaint=record.chief_complaint,
                    examination=record.examination, history_review=record.history_review,
                    history_assessment=record.history_assessment, history_discrepancy=record.history_discrepancy,
                    history_cursor=record.history_cursor, dentition=record.dentition,
                    findings=list(record.findings.values('tooth', 'surface', 'kind', 'detail'))),
        history=dict(id=history.pk, source=history.source, revision=history.revision,
                     **{k: getattr(history, k) for k in ('medical_status', 'medical_history', 'medication_status',
                                                        'medications', 'allergy_status', 'reported_allergies')}) if history else None,
        actual=actual, plans=plans,
        care=dict(id=care.pk, revision=care.revision_no, state=care.state, outcome=care.outcome,
                  clinical_note=care.clinical_note, no_treatment_reason=care.no_treatment_reason,
                  lines=list(care.treatment_lines.order_by('line_no').values('id', 'name_snapshot', 'unit_snapshot', 'quantity'))) if care else None)
    if snapshot['care']:
        for line in snapshot['care']['lines']:
            line['quantity'] = str(line['quantity'])
    cursor = draft_digest({k: v for k, v in snapshot.items() if k != 'header'} | {
        'live_history_cursor': history_cursor(visit.patient_id, visit.clinic_id)})
    return snapshot, cursor, record, care


def _lock(actor, visit_id):
    visit, patient, encounter = lock_encounter(actor, visit_id)
    if visit.status not in ('CHECKED_IN', *CLOSED):
        raise RuleError('文书只能办理本次已实际到诊的接诊。')
    head = open_document(encounter, actor)
    return visit, encounter, ClinicalDocument.objects.select_for_update().get(pk=head.pk)


def _replay(actor, head, op, action, intent=None):
    event = ClinicalDocumentEvent.objects.filter(operation_id=op).first()
    if event:
        if event.actor_id != actor.pk or event.document_id != head.pk or event.action != action:
            raise RuleError('操作编号已经用于其他办理，请重新打开文书。')
        if intent is not None and event.snapshot.get('intent') != intent:
            raise RuleError('原提交已保留，新填写内容尚未保存；请核对当前文书。')
    return event


@business_errors
@transaction.atomic
@sensitive_variables()
def save_document(*, actor, visit_id, expected_revision, operation_id, fields, action='SAVE'):
    visit, encounter, head = _lock(actor, visit_id)
    op = operation(operation_id)
    if action not in ('SAVE', 'AMEND', 'DISCARD', 'FOLLOWUP'):
        raise RuleError('未知文书操作。')
    intent = draft_digest({'action': action, 'fields': {
        k: v.isoformat() if hasattr(v, 'isoformat') else v for k, v in fields.items()}})
    if _replay(actor, head, op, action, intent):
        return head, True
    if head.revision != expected_revision:
        raise RuleError('另一页面已更新文书；本页填写仍保留，请比较最新内容后再保存。')
    draft = ClinicalDocumentDraft.objects.select_for_update().filter(document=head).first()
    latest = latest_version(head)
    note = ''
    if action == 'SAVE':
        if latest and not draft:
            raise RuleError('已确认文书不能覆盖，请先建立有依据的更正草稿。')
        payload = normalize(fields)
        check_prior(actor, visit, payload)
        if draft and draft.base_version_id:
            payload['amendment_reason'] = draft.payload['amendment_reason']
        if draft:
            draft.payload = payload; draft.saved_by = actor; draft.save()
        else:
            ClinicalDocumentDraft.objects.create(document=head, saved_by=actor, payload=payload)
    elif action == 'AMEND':
        note = str(fields.get('reason', '')).strip()
        if latest is None or draft is not None or not 4 <= len(note) <= 500:
            raise RuleError('请基于当前确认版本填写4至500字更正依据；已有草稿请继续原草稿。')
        payload = dict(latest.content, amendment_reason=note, late_reason='')
        ClinicalDocumentDraft.objects.create(document=head, base_version=latest, saved_by=actor, payload=payload)
        head.review_due_at = timezone.now() + timedelta(hours=getattr(settings, 'ADC_CLINICAL_DOCUMENT_DUE_HOURS', 24))
    elif action == 'DISCARD':
        note = str(fields.get('reason', '')).strip()
        if draft is None or not 4 <= len(note) <= 500:
            raise RuleError('请填写4至500字依据，明确放弃当前未确认草稿。')
        draft.delete()
    else:
        note = str(fields.get('note', '')).strip()
        deadline = fields.get('due_at')
        if not 4 <= len(note) <= 1000 or not deadline or deadline <= timezone.now():
            raise RuleError('请说明待办进展，并指定下一次联系／办理期限。')
        head.next_action_at = deadline
    head.revision += 1
    head.save(update_fields=['revision', 'next_action_at', 'review_due_at'])
    ClinicalDocumentEvent.objects.create(document=head, actor=actor, operation_id=op, action=action, note=note,
                                         snapshot={'revision': head.revision, 'intent': intent,
                                                   'due_at': head.due_at.isoformat(),
                                                   'review_due_at': head.review_due_at.isoformat() if head.review_due_at else None,
                                                   'next_action_at': head.next_action_at.isoformat() if head.next_action_at else None})
    emit(actor, 'CLINICAL_DOCUMENT_' + action, head, visit=visit, summary={'revision': head.revision})
    return head, False


def prepare_document(*, actor, visit_id):
    visit = Visit.objects.select_related('patient', 'clinic', 'dentist').get(pk=visit_id)
    require_visit_authority(actor, visit, 'RECORD', always=True)
    head = ClinicalDocument.objects.get(encounter__visit=visit)
    draft = ClinicalDocumentDraft.objects.get(document=head)
    payload = normalize(draft.payload, complete=True)
    check_prior(actor, visit, payload)
    if visit.status not in CLOSED:
        raise RuleError('请先按原流程完成本次实际接诊，再确认包含处置和离诊医嘱的完整文书；草稿继续保留。')
    snapshot, cursor, record, care = source_projection(actor, visit, head.encounter)
    if record.history_cursor != history_cursor(visit.patient_id, visit.clinic_id):
        raise RuleError('有新的患者自述待核对，请先追加检查版本，再预览文书。')
    if draft.base_version_id and not 4 <= len(payload['amendment_reason']) <= 500:
        raise RuleError('更正文书须保留明确依据。')
    if timezone.now() > active_deadline(head) and len(payload['late_reason']) < 4:
        raise RuleError('文书已超过工作台办理期限，请说明迟记原因；发生、录入和确认时间分别保留。')
    data = dict(visit=visit.pk, document=head.pk, revision=head.revision,
                base=draft.base_version_id, digest=draft_digest(payload), source_cursor=cursor,
                snapshot_digest=draft_digest(snapshot))
    return dict(visit=visit, payload=payload, source=snapshot,
                proposal_token=proposal(actor, CONTRACT, ('DENTIST',), data))


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm_document(*, actor, proposal_token, confirmed):
    if confirmed is not True:
        raise RuleError('请核对完整文书及确认凭据，再明确确认本版本。')
    p = read_proposal(actor, CONTRACT, ('DENTIST',), proposal_token); data = p['data']
    visit, encounter, head = _lock(actor, data['visit'])
    read_proposal(actor, CONTRACT, ('DENTIST',), proposal_token)
    op = operation(p['operation'])
    event = _replay(actor, head, op, 'CONFIRM')
    if event:
        return event.version, True
    if head.pk != data['document'] or head.revision != data['revision']:
        raise RuleError('文书草稿或待办已变化，请重新核对预览。')
    draft = ClinicalDocumentDraft.objects.select_for_update().get(document=head)
    latest = latest_version(head)
    if draft.base_version_id != (latest.pk if latest else None) or draft.base_version_id != data['base']:
        raise RuleError('当前确认版本已变化，请比较后重新建立更正草稿。')
    prepared = prepare_document(actor=actor, visit_id=visit.pk)
    snapshot = prepared['source']; payload = prepared['payload']
    if draft_digest(payload) != data['digest'] or draft_digest(snapshot) != data['snapshot_digest']:
        raise RuleError('检查、实际处置或文书来源已变化；草稿保留，请核对最新来源后重新预览。')
    _, cursor, record, care = source_projection(actor, visit, encounter)
    if cursor != data['source_cursor']:
        raise RuleError('患者资料来源已变化，请重新核对。')
    version = ClinicalDocumentVersion.objects.create(document=head, revision=latest.revision+1 if latest else 1,
        previous=latest, prior_visit_version_id=payload['prior_visit_version'], source_record=record, care_record=care,
        kind=payload['kind'], content=payload, source_snapshot=snapshot, source_cursor=cursor,
        content_digest=draft_digest({'content': payload, 'source': snapshot}), confirmed_by=actor,
        confirmed_at=timezone.now(), evidence_kind=payload['evidence_kind'],
        evidence_reference=payload['evidence_reference'], amendment_reason=payload['amendment_reason'] if latest else '',
        late_reason=payload['late_reason'])
    draft.delete(); head.revision += 1; head.save(update_fields=['revision'])
    ClinicalDocumentEvent.objects.create(document=head, version=version, actor=actor, operation_id=op, action='CONFIRM',
        snapshot={'revision': head.revision, 'version': version.revision, 'digest': version.content_digest,
                  'evidence_kind': version.evidence_kind})
    emit(actor, 'CLINICAL_DOCUMENT_CONFIRMED', version, visit=visit,
         summary={'revision': version.revision, 'evidence_kind': version.evidence_kind})
    return version, False
