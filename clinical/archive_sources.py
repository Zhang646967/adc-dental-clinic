"""Exact archive sources. Callers own authorization; generation reads no live text for rendering."""
import copy,json
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q
from django.utils import timezone
from adc_core.rules import RuleError
from clinical.clinical_payload import draft_digest
from clinical.document_models import ClinicalDocument, ClinicalDocumentDraft, ClinicalDocumentVersion
from clinical.documents import source_projection
from clinical.encounter_models import ClinicalDraft
from clinical.encounters import current_record,history_cursor
from clinical.models import ClinicalEncounter
from clinical.plan_models import PerformedProcedure,TreatmentPlan,PlanVersion,PlanStepVersion,PlanDecision,PlanDraft
from clinical.consent_models import MedicalConsent,ConsentVersion,ConsentEvent
from clinical.preflight_models import TreatmentPreflight,ClinicalConsentRule,ProcedureGap,ProcedureGapReview
from clinical.continuity_models import LabCase,LabReview,LabEvent
from portal.medical_models import MedicalProxyVersion,MedicalProxyEvent
from care.models import VisitRecordVersion,Invoice


def plain(value):
    return json.loads(json.dumps(value,cls=DjangoJSONEncoder,ensure_ascii=False))


def rows(model,**filters):
    return list(model.objects.filter(**filters).order_by('pk').values())


def medical_content(snapshot):
    """Billing-only revision IDs and copied line IDs do not change clinical prose."""
    result=copy.deepcopy({k:v for k,v in snapshot.items() if k!='header'})
    if result.get('care'):
        for key in ('id','revision','state'):result['care'].pop(key,None)
        for line in result['care']['lines']:line.pop('id',None)
    return result


def capture(visit,*,fee_version_id=None):
    encounter=ClinicalEncounter.objects.get(visit=visit)
    doc=ClinicalDocumentVersion.objects.filter(document__encounter=encounter).order_by('-revision').first()
    record=current_record(encounter);issues=[]
    def missing(code,message,route):issues.append(dict(code=code,message=message,route=route,owner='负责医师'))
    if visit.status not in ('COMPLETED','CLOSED_NO_TREATMENT'):
        missing('CARE_OPEN','本次接诊尚未结束，请先如实完成接诊。','care_workspace')
    if record is None:missing('RECORD_MISSING','本次检查尚无确认版本。','clinical_encounter')
    if doc is None:missing('DOCUMENT_MISSING','完整病历文书尚未由医师确认。','clinical_document')
    if ClinicalDraft.objects.filter(encounter=encounter).exists():
        missing('RECORD_DRAFT','检查仍有未确认草稿，请确认或明确放弃。','clinical_encounter')
    if ClinicalDocumentDraft.objects.filter(document__encounter=encounter).exists():
        missing('DOCUMENT_DRAFT','完整文书仍有未确认草稿，请继续办理。','clinical_document')
    live=None
    if record:
        live,_,_,_=source_projection(None,visit,encounter,check_plan_authority=False)
        if record.history_cursor!=history_cursor(visit.patient_id,visit.clinic_id):
            missing('HISTORY_CHANGED','出现新的健康自述，请负责医师核对并追加准确检查及文书。','clinical_encounter')
    if doc and live and medical_content(doc.source_snapshot)!=medical_content(live):
        missing('DOCUMENT_SOURCE_CHANGED','检查、实际处置或计划来源已变化，请完善对应病历文书版本。','clinical_document')
    if PlanDraft.objects.filter(plan__origin_encounter=encounter).exists():
        missing('PLAN_DRAFT','本次治疗计划仍有未确认草稿，请明确保留、确认或放弃。','clinical_plans')
    actuals=rows(PerformedProcedure,encounter=encounter)
    active=[r for r in actuals if r['state']=='ACTIVE']
    for item in active:
        if not item['preflight_id']:
            missing('PREFLIGHT_MISSING','有效实际治疗缺少事前核对依据；不得补造，可选择缺项资料保全。','clinical_retrospective')
    gaps=rows(ProcedureGap,performed__encounter=encounter)
    if any(g['performed_id'] in {r['id'] for r in active} for g in gaps):
        missing('HISTORICAL_GAP','已发生治疗保留材料缺口；医务复核不等于事前已通过，暂不能正常完整归档。','clinical_gaps')
    care=VisitRecordVersion.objects.filter(visit=visit).exclude(state='ABANDONED').order_by('-revision_no').first()
    if care and care.outcome=='TREATED' and not active:
        missing('ACTUAL_MISSING','处置结果为已治疗，但没有有效实际治疗来源，请核对真实记录。','clinical_actual')
    plans=list(TreatmentPlan.objects.filter(origin_encounter=encounter).order_by('pk'))
    version_ids=set(PlanVersion.objects.filter(plan__in=plans).values_list('pk',flat=True))
    version_ids.update(PlanStepVersion.objects.filter(pk__in=[a['step_version_id'] for a in actuals if a['step_version_id']]).values_list('version_id',flat=True))
    version_ids.discard(None)
    steps=rows(PlanStepVersion,version_id__in=version_ids)
    step_ids={r['step_id'] for r in steps}
    consents=rows(MedicalConsent,step_id__in=step_ids)
    notices=rows(ConsentVersion,consent_id__in=[r['id'] for r in consents])
    events=rows(ConsentEvent,consent_id__in=[r['id'] for r in consents])
    replied={r['reply_to_id'] for r in events if r['reply_to_id']}
    if any(e['action']=='QUESTION' and e['id'] not in replied for e in events):
        missing('UNANSWERED_QUESTION','相关医疗疑问尚未答复，请由负责医师继续医疗问答。','clinical_consents')
    checks=rows(TreatmentPreflight,pk__in=[a['preflight_id'] for a in actuals if a['preflight_id']])
    basis_ids={r['proxy_version_id'] for r in notices if r['proxy_version_id']}
    decisions=rows(PlanDecision,step_version__version_id__in=version_ids)
    basis_ids.update(r['proxy_version_id'] for r in decisions if r['proxy_version_id'])
    published=VisitRecordVersion.objects.filter(visit=visit,state='PUBLISHED').order_by('-revision_no')
    fee=published.filter(pk=fee_version_id).first() if fee_version_id else published.first()
    if fee_version_id and fee is None:raise RuleError('收费版本不属于本次已发布记录，请重新选择。')
    fee_data=None
    if fee:
        fee_data=dict(id=fee.pk,revision=fee.revision_no,header=fee.billing_header_snapshot,
            amount=str(fee.total_amount),published_at=fee.published_at,
            lines=list(fee.treatment_lines.order_by('line_no').values('name_snapshot','unit_snapshot','quantity','unit_price','line_amount')))
        from care.medication_charges import charge_projection
        medicine=charge_projection(fee)
        if medicine:
            fee_data['medication_lines']=medicine
    header=doc.source_snapshot['header'] if doc else dict(patient_id=visit.patient_id,patient_no=visit.patient.patient_no,
        patient_name=visit.patient.name,clinic_id=visit.clinic_id,clinic_name=visit.clinic.name,
        dentist_id=visit.dentist_id,dentist_name=visit.dentist.name,employee_no=visit.dentist.employee_no,visit_no=visit.visit_no)
    result=dict(contract='adc.clinical-archive.c33a.v1',header=header,
        visit=dict(id=visit.pk,status=visit.status,attended_at=visit.attended_at,completed_at=visit.completed_at),
        document=plain(dict(id=doc.pk,revision=doc.revision,content=doc.content,source=doc.source_snapshot,
            confirmed_by=doc.confirmed_by_id,confirmed_at=doc.confirmed_at,recorded_at=doc.recorded_at,
            digest=doc.content_digest,evidence_kind=doc.evidence_kind,evidence_reference=doc.evidence_reference)) if doc else None,
        clinical_source=doc.source_snapshot if doc else live,actuals=actuals,
        plan_versions=rows(PlanVersion,pk__in=version_ids),steps=steps,scheme_decisions=decisions,
        medical_consents=consents,medical_notices=notices,medical_events=events,
        proxy_versions=rows(MedicalProxyVersion,pk__in=basis_ids),
        proxy_events=rows(MedicalProxyEvent,version_id__in=basis_ids),
        preflights=checks,rules=rows(ClinicalConsentRule,pk__in={r['rule_id'] for r in checks}),
        gaps=gaps,gap_reviews=rows(ProcedureGapReview,gap_id__in=[g['id'] for g in gaps]),
        laboratory=rows(LabCase,source_record__encounter=encounter),
        laboratory_reviews=rows(LabReview,case__source_record__encounter=encounter),
        laboratory_events=rows(LabEvent,case__source_record__encounter=encounter),
        drafts=dict(examinations=rows(ClinicalDraft,encounter=encounter),
            documents=rows(ClinicalDocumentDraft,document__encounter=encounter),
            plans=rows(PlanDraft,plan__origin_encounter=encounter)),
        fee=fee_data,issues=issues)
    from supplies.models import NursingExecution
    nursing=list(NursingExecution.objects.filter(visit=visit).values(
        'id','kind','observed_at','recorded_at','quantity','performed_id','issue_id','actor_id','reason',
        'sterile_pack__code','sterile_pack__process_reference','stock_movement__lot__code',
    ).order_by('pk'))
    if nursing:
        result['nursing']=nursing
    return plain(result)


def required_services(visit,snapshot):
    from clinical.authority import visit_service_id
    values={visit_service_id(visit)}|{r['service_id'] for r in snapshot['steps']}
    return sorted(values,key=lambda v:-1 if v is None else v)


def digest(snapshot):return draft_digest(snapshot)
