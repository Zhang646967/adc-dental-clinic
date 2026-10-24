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
        require_visit_authority(actor,visit,'READ')
        draft = visit.record_versions.filter(state='DRAFT',correction_request__isnull=True).first()
        lines = list(draft.treatment_lines.order_by('line_no')) if draft else []
        snap = draft.allergy_review_snapshot if draft else {}
        allergy_current = (snap.get('status') in ['KNOWN','NO_KNOWN'] and
            snap.get('information_version') == visit.patient.allergy_info_version and bool(snap.get('reviewed_at')))
        editable = visit.status == 'CHECKED_IN'
        blockers = []
        if not editable: blockers.append('只有已到诊、尚未关闭的记录可编辑。')
        if not visit.patient.is_active: blockers.append('患者资料已停用，请先由获授权人员核对。')
        if not visit.attended_at or visit.attended_at > timezone.now(): blockers.append('实际到诊时间需先核对。')
        treated_blockers = list(blockers)
        if not lines: treated_blockers.append('尚无实际治疗明细；未治疗时请选择无治疗关闭并填写原因。')
        if not allergy_current: treated_blockers.append('过敏信息仍未知、尚未复核或资料版本已变化。')
        if any(line.confirmed_by_id != actor.pk or not line.confirmed_at for line in lines):
            treated_blockers.append('部分治疗尚未由本次负责牙医确认。')
        invoice = Invoice.objects.filter(visit_id=visit.pk).select_related('current_record_version').first()
        published = invoice.current_record_version if invoice else None
        display_record=draft or published
        display_lines=lines if draft else list(published.treatment_lines.order_by('line_no')) if published else []
        from clinical.authority import may_refer
        return dict(visit=visit, record=display_record, lines=display_lines, invoice=invoice, published=published, can_refer=may_refer(actor,visit),
            editable=editable, allergy_current=allergy_current, treated_blockers=treated_blockers,
            no_treatment_allowed=not blockers and not lines,
            clinical_note=draft.clinical_note if draft else published.clinical_note if published else '')
