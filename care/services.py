"""UC-06/07/11: explicit dentist commands; AI has no entry to these functions."""
from decimal import Decimal
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from adc_core.rules import RuleError, CLOSED_STATUSES, line_amount, total_amount, validate_allergies
from care.audit import emit
from care.models import VisitRecordVersion, TreatmentRecord, Invoice
from patients.models import Patient, PatientAllergy
from registry.models import Allergy, TreatmentType
from scheduling.models import Visit
from adc_core.commands import business_errors, assert_revision as _assert_current


def _lock_care(actor, visit_id):
    from clinical.locking import lock_clinical_visit
    from clinical.models import ClinicalEncounter
    return lock_clinical_visit(actor,visit_id,strict=ClinicalEncounter.objects.filter(visit_id=visit_id).exists())


def _draft(actor,visit):
    if visit.status != "CHECKED_IN": raise RuleError("仅已到诊记录可以录入治疗。")
    obj,_=VisitRecordVersion.objects.get_or_create(visit=visit,revision_no=1,
        defaults={"prepared_by":actor,"outcome":"TREATED"})
    obj=VisitRecordVersion.objects.select_for_update().get(pk=obj.pk)
    if obj.state != "DRAFT": raise RuleError("已发布内容不允许原地修改。")
    return obj


def _bump(v):
    v.lock_version+=1
    v.save(update_fields=["lock_version"])


@business_errors
@transaction.atomic
@sensitive_variables('clinical_note')
def save_clinical_note(*,actor,visit_id,expected_version,clinical_note):
    if not isinstance(clinical_note,str) or len(clinical_note)>4000:
        raise RuleError("接诊草稿最多4000字。")
    v=_lock_care(actor,visit_id);_assert_current(v,expected_version)
    from clinical.models import ClinicalEncounter
    if ClinicalEncounter.objects.filter(visit=v).exists():
        raise RuleError("本次已开始结构化检查，请在检查记录工作台维护检查与核对结论。")
    draft=_draft(actor,v)
    draft.clinical_note=clinical_note.strip()
    draft.save(update_fields=["clinical_note"]);_bump(v)
    emit(actor,"CARE_NOTE_SAVED",draft,visit=v,summary={"revision":draft.revision_no})
    return draft


@business_errors
@transaction.atomic
def review_allergies(*,actor,visit_id,expected_version,patient_version,status,allergy_ids=()):
    v=_lock_care(actor,visit_id); _assert_current(v,expected_version)
    if v.status!="CHECKED_IN": raise RuleError("只有已到诊记录可以执行接诊复核。")
    patient=Patient.objects.select_for_update().get(pk=v.patient_id,is_active=True)
    if patient.allergy_info_version!=patient_version: raise RuleError("患者过敏资料已经更新，请刷新后复核。")
    ids=validate_allergies(status,allergy_ids)
    entries=list(Allergy.objects.filter(pk__in=ids,is_active=True).order_by("pk"))
    if len(entries)!=len(ids): raise RuleError("部分过敏目录不可用。")
    before_ids=tuple(patient.allergy_links.filter(is_active=True).order_by("allergy_id").values_list("allergy_id",flat=True))
    if patient.allergy_status!=status or before_ids!=ids:
        patient.allergy_links.update(is_active=False)
        for entry in entries:
            PatientAllergy.objects.update_or_create(patient=patient,allergy=entry,defaults={"is_active":True})
        patient.allergy_status=status;patient.allergy_info_version+=1
        patient.save(update_fields=["allergy_status","allergy_info_version"])
    draft=_draft(actor,v)
    draft.allergy_review_snapshot={"status":status,"items":[{"code":a.code,"name":a.name} for a in entries],
        "information_version":patient.allergy_info_version,"reviewed_by":actor.pk,"reviewed_at":timezone.now().isoformat()}
    draft.save(update_fields=["allergy_review_snapshot"])
    _bump(v)
    emit(actor,"CARE_ALLERGY_REVIEWED",draft,visit=v,summary={"information_version":patient.allergy_info_version})
    return draft


@business_errors
@transaction.atomic
def add_treatment(*,actor,visit_id,expected_version,treatment_id,quantity,price_reason=""):
    v=_lock_care(actor,visit_id);_assert_current(v,expected_version)
    draft=_draft(actor,v)
    treatment=TreatmentType.objects.select_for_update().get(pk=treatment_id,is_active=True)
    if draft.treatment_lines.count()>=40: raise RuleError("单次演示接诊最多40行治疗明细。")
    amount=line_amount(quantity,treatment.standard_unit_price,price_reason)
    from django.db.models import Max
    seq=(draft.treatment_lines.aggregate(n=Max("line_no"))["n"] or 0)+1
    line=TreatmentRecord.objects.create(record_version=draft,line_no=seq,treatment_type=treatment,
        name_snapshot=treatment.name,unit_snapshot=treatment.unit_definition,quantity=quantity,
        unit_price=treatment.standard_unit_price,line_amount=amount,confirmed_by=actor,
        confirmed_at=timezone.now(),price_reason=price_reason.strip()[:500])
    draft.total_amount=total_amount(draft.treatment_lines.values_list("line_amount",flat=True))
    draft.save(update_fields=["total_amount"]);_bump(v)
    emit(actor,"TREATMENT_CONFIRMED",line,visit=v,summary={"line_no":seq,"catalogue_code":treatment.code})
    return line


@business_errors
@transaction.atomic
def remove_treatment(*,actor,visit_id,expected_version,line_id,reason):
    if not isinstance(reason,str) or not 1<=len(reason.strip())<=500: raise RuleError("请填写撤回误录明细的原因。")
    v=_lock_care(actor,visit_id);_assert_current(v,expected_version)
    draft=_draft(actor,v)
    line=TreatmentRecord.objects.get(pk=line_id,record_version=draft)
    emit(actor,"DRAFT_LINE_REMOVED",line,visit=v,reason=reason.strip(),summary={"line_no":line.line_no})
    line.delete()
    draft.total_amount=total_amount(draft.treatment_lines.values_list("line_amount",flat=True))
    draft.save(update_fields=["total_amount"]);_bump(v)
    return draft


@business_errors
@transaction.atomic
def complete_visit(*,actor,visit_id,expected_version,outcome,reason=""):
    v=_lock_care(actor,visit_id)
    target={"TREATED":"COMPLETED","NO_TREATMENT":"CLOSED_NO_TREATMENT"}.get(outcome)
    if target is None: raise RuleError("未知关闭类型。")
    if v.status in CLOSED_STATUSES:
        if v.status!=target: raise RuleError("此次就诊已经以其他结果关闭，不能改写。")
        return Invoice.objects.get(visit=v)  # Retry-safe AFTER rechecking current authorization.
    _assert_current(v,expected_version)
    # Global patient lock precedes version lock, as in allergy review.
    patient=Patient.objects.select_for_update().get(pk=v.patient_id,is_active=True)
    from clinical.completion import completion_blockers
    clinical_blockers=completion_blockers(v)
    if clinical_blockers:raise RuleError(clinical_blockers[0])
    draft=_draft(actor,v)
    lines=list(draft.treatment_lines.select_for_update().order_by("line_no"))
    if outcome=="TREATED":
        if not lines: raise RuleError("有治疗完成必须包含实际治疗；没有治疗请选择无治疗关闭。")
        snap=draft.allergy_review_snapshot
        if snap.get("status") not in ("KNOWN","NO_KNOWN") or snap.get("information_version")!=patient.allergy_info_version or not snap.get("reviewed_at"):
            raise RuleError("过敏信息未知、未复核或已经更新，请重新复核。")
    else:
        if lines: raise RuleError("已有实际治疗，不能作为无治疗关闭。")
        if not isinstance(reason,str) or not 1<=len(reason.strip())<=500: raise RuleError("无治疗关闭必须填写原因（1至500字）。")
    for item in lines:
        if item.confirmed_by_id!=actor.pk or item.confirmed_at is None:
            raise RuleError("全部治疗必须由本次负责牙医明确确认。")
        if item.line_amount!=line_amount(item.quantity,item.unit_price,item.price_reason): raise RuleError("治疗金额不一致。")
    now=timezone.now()
    if not v.attended_at or now < v.attended_at: raise RuleError("完成时间不能早于实际到诊。")
    draft.billing_header_snapshot={"patient_name":patient.name,"patient_no":patient.patient_no,
        "billing_address":patient.billing_address,"clinic_name":v.clinic.name,
        "clinic_address":v.clinic.postal_address,"dentist_name":v.dentist.name}
    draft.total_amount=total_amount(i.line_amount for i in lines)
    draft.outcome=outcome;draft.no_treatment_reason=reason.strip() if outcome=="NO_TREATMENT" else ""
    draft.reviewed_by=actor;draft.state="PUBLISHED";draft.published_at=now
    draft.save(update_fields=["billing_header_snapshot","total_amount","outcome","no_treatment_reason","reviewed_by","state","published_at"])
    invoice=Invoice.objects.create(visit=v,current_record_version=draft)
    v.status=target;v.completed_at=now;v.lock_version+=1
    v.save(update_fields=["status","completed_at","lock_version"])
    emit(actor,"CARE_COMPLETED",invoice,visit=v,summary={"outcome":outcome,"revision":draft.revision_no})
    return invoice
