"""Shared website/native projection, reached only through exact clinical access."""
from django.core.exceptions import PermissionDenied
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from clinical import consents
from clinical.consent_models import MedicalConsent
from clinical.disclosures import projection


def details(actor, step_id, *, visit_id=None, revision=None):
    with reporting_snapshot():
        return _details(actor, step_id, visit_id=visit_id, revision=revision)


def _details(actor, step_id, *, visit_id=None, revision=None):
    step, patient = consents.step_for(actor, step_id, visit_id)
    case = MedicalConsent.objects.filter(step=step.step).first()
    versions = list(case.versions.select_related('step_version__version', 'prepared_by__dentist', 'source_record').order_by('-revision')) if case else []
    version = versions[0] if versions else None
    if revision:
        version = next((v for v in versions if str(v.revision) == str(revision)), None)
        if version is None:raise RuleError('未找到这份医疗告知历史版本。')
    selected_step = version.step_version if version else step
    notice = projection(selected_step.version.disclosures.get(str(selected_step.step.step_key)))
    events = list(case.events.select_related('actor', 'reply_to').order_by('sequence')) if case else []
    answered = {e.reply_to_id for e in events if e.reply_to_id}
    decisions = [e for e in events if version and e.version_id == version.pk and e.action in consents.DECISIONS]
    decision = decisions[-1] if decisions else None
    current = bool(version and versions[0].pk == version.pk)
    reason = '请先由医师核对本人身份并确认本步骤告知。'
    can_agree = False
    if version:
        try:
            consents.current_scope(selected_step, patient, version)
            can_agree = current and not decision and not any(e.action == 'QUESTION' and e.pk not in answered for e in events)
            reason = '请先等待医师答复未解决的疑问。' if any(e.action == 'QUESTION' and e.pk not in answered for e in events) else '请核对具体内容后明确决定。'
        except (RuleError, PermissionDenied) as exc:reason = str(exc)
    return dict(step=step, patient=patient, case=case, version=version, versions=versions,
        data=dict(step=selected_step.pk, plan=selected_step.version.plan_id, plan_version=selected_step.version.revision,
            consent=case.pk if case else None, version=version.pk if version else None,
            revision=version.revision if version else None, is_current=current,
            versions=[dict(revision=v.revision, step=v.step_version_id, plan_version=v.step_version.version.revision) for v in versions],
            patient=patient.name, clinic=selected_step.version.plan.origin_encounter.visit.clinic.name,
            description=selected_step.description, tooth=selected_step.tooth, surface=selected_step.surface,
            doctor=version.prepared_by.dentist.name if version else '',
            disclosure=notice, recorded_at=version.recorded_at.isoformat() if version else None,
            scope_digest=version.scope_digest if version else None,
            identity_basis='负责医师已核对成年患者本人身份与理解表达条件' if version else '待医师核对',
            can_agree=can_agree, can_withdraw=bool(decision and decision.action == 'AGREED'),
            can_decide=bool(version and not decision), status=decision.get_action_display() if decision else '待本人决定' if version else '待医师告知',
            applicability=reason, evidence_notice='本人账号确认与纸质原件登记分别记录；请核对所显示的来源。',
            events=[dict(id=e.pk, version=e.version_id, revision=next(v.revision for v in versions if v.pk == e.version_id),
                action=e.action, label=e.get_action_display(), source=e.source, source_label=e.get_source_display(),
                text=e.text, reference=e.reference, reply_to=e.reply_to_id, unanswered=e.action == 'QUESTION' and e.pk not in answered,
                occurred_at=e.occurred_at.isoformat(), recorded_at=e.recorded_at.isoformat()) for e in events]))
