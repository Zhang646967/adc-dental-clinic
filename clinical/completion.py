"""Clinical readiness is distinct from completed treatment and billing."""
from django.conf import settings
from clinical.models import ClinicalEncounter,ClinicalDraft
from clinical.encounters import current_record,history_cursor


def completion_blockers(visit,*,include_gaps=True):
    head=ClinicalEncounter.objects.filter(visit_id=visit.pk).first()
    if head is None:
        return [] if settings.ADC_CLINICAL_SYNTHETIC else ['请先完成本次实际接诊的检查记录。']
    if ClinicalDraft.objects.filter(encounter=head).exists():
        return ['本次仍有未确认检查草稿，请先确认记录，或明确处理不再使用的草稿。']
    record=current_record(head)
    if record is None:return ['本次已开始检查，请先确认检查记录；无治疗也应说明实际检查结果。']
    if record.history_cursor!=history_cursor(visit.patient_id,visit.clinic_id):
        return ['患者补充了新的自述资料，请在检查记录中核对并追加确认版本。']
    if include_gaps:
        from clinical.preflight_models import ProcedureGap
        if ProcedureGap.objects.filter(performed__encounter__visit=visit,state='PENDING',performed__state='ACTIVE').exists():
            return ['本次存在已发生治疗的事前资料缺口，请由另一名有职责的审核医师复核；复核不会补造事前同意。']
    return []
