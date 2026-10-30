from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef, Subquery, F, Q, Case, When, Value, BooleanField
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from adc_core.snapshots import reporting_snapshot
from adc_core.rules import RuleError
from clinical.authority import readable_assigned_visits, require_visit_authority
from clinical.document_models import ClinicalDocument, ClinicalDocumentDraft, ClinicalDocumentVersion
from clinical.documents import latest_version, normalize, source_projection, active_deadline
from clinical.encounter_models import ClinicalRecordVersion, ClinicalHistoryVersion
from care.models import VisitRecordVersion
from scheduling.models import Visit
from workspaces.context import require_active


def prior_versions(actor, visit):
    allowed = readable_assigned_visits(actor, actor.dentist_id, strict=True).filter(
        patient_id=visit.patient_id, clinic_id=visit.clinic_id, attended_at__lt=visit.attended_at).exclude(pk=visit.pk)
    return ClinicalDocumentVersion.objects.filter(document__encounter__visit__in=allowed).select_related(
        'document__encounter__visit').order_by('-confirmed_at', '-pk')


def document_details(actor, visit_id, *, revision=None):
    with reporting_snapshot():
        require_active(actor, ('DENTIST',))
        visit = get_object_or_404(Visit.objects.select_related('patient', 'clinic', 'dentist'), pk=visit_id)
        require_visit_authority(actor, visit, 'READ', always=True)
        can_record = True
        try:
            require_visit_authority(actor, visit, 'RECORD', always=True)
        except PermissionDenied:
            can_record = False
        head = ClinicalDocument.objects.filter(encounter__visit=visit).select_related('encounter', 'responsible').first()
        current = latest_version(head) if head else None
        displayed = current
        if revision is not None:
            try:
                displayed = ClinicalDocumentVersion.objects.get(document=head, revision=int(revision))
            except (ValueError, TypeError, ClinicalDocumentVersion.DoesNotExist):
                raise Http404('没有本次就诊的指定文书版本。')
        draft = ClinicalDocumentDraft.objects.filter(document=head).first() if head and revision is None else None
        payload = normalize(draft.payload if draft else displayed.content if displayed else {})
        source = None; cursor = None; source_error = ''
        if head:
            try:
                source, cursor, _, _ = source_projection(actor, visit, head.encounter)
            except RuleError as exc:
                source_error = str(exc)
        return dict(visit=visit, document=head, document_version=displayed, current_version=current, draft=draft,
                    payload=payload, source=source, source_error=source_error,
                    source_changed=bool(current and cursor != current.source_cursor),
                    can_edit=can_record and visit.patient.is_active and revision is None and visit.status in ('CHECKED_IN', 'COMPLETED', 'CLOSED_NO_TREATMENT'),
                    overdue=bool(head and timezone.now() > active_deadline(head)),
                    active_deadline=active_deadline(head) if head else None,
                    versions=list(ClinicalDocumentVersion.objects.filter(document=head).select_related('confirmed_by').order_by('-revision')) if head else [],
                    events=list(head.events.select_related('actor').order_by('-pk')[:30]) if head else [],
                    prior_versions=prior_versions(actor, visit), historical=revision is not None)


def document_worklist(actor):
    require_active(actor, ('DENTIST',))
    visits = readable_assigned_visits(actor, actor.dentist_id, strict=True)
    rows = ClinicalDocument.objects.filter(encounter__visit__in=visits).select_related(
        'encounter__visit__patient', 'encounter__visit__clinic', 'responsible').annotate(
        has_draft=Exists(ClinicalDocumentDraft.objects.filter(document_id=OuterRef('pk'))),
        has_confirmed=Exists(ClinicalDocumentVersion.objects.filter(document_id=OuterRef('pk'))),
        deadline=Coalesce('review_due_at', 'due_at'),
        current_record_id=Subquery(ClinicalRecordVersion.objects.filter(encounter_id=OuterRef('encounter_id')).order_by('-revision').values('pk')[:1]),
        confirmed_record_id=Subquery(ClinicalDocumentVersion.objects.filter(document_id=OuterRef('pk')).order_by('-revision').values('source_record_id')[:1]),
        current_care_id=Subquery(VisitRecordVersion.objects.filter(visit_id=OuterRef('encounter__visit_id')).exclude(state='ABANDONED').filter(
            Q(correction_request__isnull=True) | Q(state='PUBLISHED')).order_by('-revision_no').values('pk')[:1]),
        confirmed_care_id=Subquery(ClinicalDocumentVersion.objects.filter(document_id=OuterRef('pk')).order_by('-revision').values('care_record_id')[:1]),
        last_confirmed_at=Subquery(ClinicalDocumentVersion.objects.filter(document_id=OuterRef('pk')).order_by('-revision').values('confirmed_at')[:1]),
    ).annotate(new_history=Exists(ClinicalHistoryVersion.objects.filter(
        patient_id=OuterRef('encounter__visit__patient_id'), recorded_at__gt=OuterRef('last_confirmed_at')).filter(
            Q(scope_clinic_id=OuterRef('encounter__visit__clinic_id')) | Q(scope_clinic__isnull=True))))
    return rows.annotate(needs_source_review=Case(When(
        Q(has_confirmed=True) & (~Q(current_record_id=F('confirmed_record_id')) |
                                ~Q(current_care_id=F('confirmed_care_id')) | Q(new_history=True)),
        then=Value(True)), default=Value(False), output_field=BooleanField())).order_by('deadline', 'pk')


def compare_versions(document, left, right):
    try:
        a = ClinicalDocumentVersion.objects.get(document=document, revision=int(left))
        b = ClinicalDocumentVersion.objects.get(document=document, revision=int(right))
    except (TypeError, ValueError, ClinicalDocumentVersion.DoesNotExist):
        raise Http404('请选择本次文书中可比较的两个版本。')
    labels = {'kind': '初诊／复诊', 'prior_visit_version': '既往文书', 'prior_context': '复诊来源与变化',
              'diagnosis': '诊断／判断', 'ancillary_results': '辅助检查', 'instructions': '离诊医嘱',
              'follow_up': '复诊安排', 'evidence_kind': '确认凭据', 'evidence_reference': '纸质原件引用',
              'late_reason': '迟记原因', 'amendment_reason': '更正依据'}
    rows = [dict(label=label, before=a.content.get(key, ''), after=b.content.get(key, ''),
                 changed=a.content.get(key) != b.content.get(key)) for key, label in labels.items()]
    for key, label in [('record', '检查与牙位来源'), ('history', '病史来源'), ('actual', '实际执行来源'),
                       ('plans', '治疗计划来源'), ('care', '接诊处置来源')]:
        import json
        rows.append(dict(label=label, before=json.dumps(a.source_snapshot.get(key), ensure_ascii=False, indent=2),
                         after=json.dumps(b.source_snapshot.get(key), ensure_ascii=False, indent=2),
                         changed=a.source_snapshot.get(key) != b.source_snapshot.get(key)))
    return dict(left=a, right=b, comparison_rows=rows)
