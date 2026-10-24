"""One read-only snapshot for the assigned dentist's care checklist."""
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from adc_core.snapshots import reporting_snapshot
from accounts.policies import bindings
from scheduling.models import Visit
from care.models import Invoice

def care_progress(actor, visit_id):
    with reporting_snapshot():
        visit = Visit.objects.select_related('patient','dentist','clinic').get(pk=visit_id)
        if not bindings(actor).filter(role='DENTIST',scope_kind='SELF_DENTIST',user__dentist_id=visit.dentist_id).exists():
            raise PermissionDenied('仅负责牙医可以查看接诊记录。')
        from clinical.authority import require_visit_authority
        from clinical.models import ClinicalEncounter,ClinicalRecordVersion
        structured=ClinicalEncounter.objects.filter(visit=visit).exists()
        require_visit_authority(actor,visit,'READ',always=structured)
        clinical_available=True
        try:require_visit_authority(actor,visit,'READ',always=True)
        except PermissionDenied:clinical_available=False
        draft = visit.record_versions.filter(state='DRAFT',correction_request__isnull=True).first()
        lines = list(draft.treatment_lines.order_by('line_no')) if draft else []
        snap = draft.allergy_review_snapshot if draft else {}
        allergy_current = (snap.get('status') in ['KNOWN','NO_KNOWN'] and
            snap.get('information_version') == visit.patient.allergy_info_version and bool(snap.get('reviewed_at')))
        from clinical.completion import completion_blockers
        from clinical.actual_summary import actual_care_summary,bind_performed_sources
        actual=actual_care_summary(visit.pk)
        can_record=True
        try:require_visit_authority(actor,visit,'RECORD',always=structured)
        except PermissionDenied:can_record=False
        editable = visit.status == 'CHECKED_IN' and can_record
        blockers = []
        if visit.status!='CHECKED_IN': blockers.append('只有已到诊、尚未关闭的记录可编辑。')
        if not can_record:blockers.append('当前专业范围允许查阅，尚不允许记录本次诊疗。')
        if not visit.patient.is_active: blockers.append('患者资料已停用，请先由获授权人员核对。')
        if not visit.attended_at or visit.attended_at > timezone.now(): blockers.append('实际到诊时间需先核对。')
        clinical_blockers=completion_blockers(visit)
        treated_blockers = list(blockers)+clinical_blockers
        if not lines and not actual['stage_no_charge']: treated_blockers.append('尚无实际治疗明细；未治疗时请选择无治疗关闭并填写原因。')
        if not allergy_current: treated_blockers.append('过敏信息仍未知、尚未复核或资料版本已变化。')
        if any(line.confirmed_by_id != actor.pk or not line.confirmed_at for line in lines):
            treated_blockers.append('部分治疗尚未由本次负责牙医确认。')
        invoice = Invoice.objects.filter(visit_id=visit.pk).select_related('current_record_version').first()
        published = invoice.current_record_version if invoice else None
        display_record=draft or published
        display_lines=lines if draft else list(published.treatment_lines.order_by('line_no')) if published else []
        bind_performed_sources(display_lines)
        from clinical.authority import may_refer
        clinical_record=ClinicalRecordVersion.objects.filter(encounter__visit=visit).order_by('-revision').first() if structured else None
        return dict(visit=visit, clinical_started=structured,clinical_available=clinical_available,clinical_record=clinical_record,record=display_record, lines=display_lines, invoice=invoice, published=published, can_refer=may_refer(actor,visit),
            editable=editable, allergy_current=allergy_current, treated_blockers=treated_blockers,
            actual=actual,no_treatment_allowed=not blockers and not clinical_blockers and not lines and not actual['provided'],
            clinical_note=draft.clinical_note if draft else published.clinical_note if published else '')
