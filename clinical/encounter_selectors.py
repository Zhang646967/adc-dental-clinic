"""Assigned-professional projections; no chain chart search or money fields."""
from django.core.exceptions import PermissionDenied
from django.db.models import Exists,OuterRef,Subquery
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from adc_core.snapshots import reporting_snapshot
from clinical.authority import require_visit_authority,readable_assigned_visits
from clinical.encounters import current_record,record_payload,visible_history,history_cursor
from clinical.clinical_payload import normalize_draft
from clinical.models import ClinicalEncounter,ClinicalDraft,ClinicalRecordVersion
from scheduling.models import Visit
from workspaces.context import require_active


def clinical_worklist(actor):
    require_active(actor,('DENTIST',))
    return readable_assigned_visits(actor,actor.dentist_id,strict=True).select_related('patient','clinic','dentist').annotate(
        clinical_started=Exists(ClinicalEncounter.objects.filter(visit_id=OuterRef('pk'))),
        clinical_draft=Exists(ClinicalDraft.objects.filter(encounter__visit_id=OuterRef('pk'))),
        clinical_revision=Subquery(ClinicalRecordVersion.objects.filter(encounter__visit_id=OuterRef('pk')).order_by('-revision').values('revision')[:1]),
    ).order_by('-scheduled_start','-pk')


def encounter_details(actor,visit_id,*,revision=None):
    with reporting_snapshot():
        require_active(actor,('DENTIST',))
        visit=get_object_or_404(Visit.objects.select_related('patient','clinic','dentist'),pk=visit_id,dentist_id=actor.dentist_id)
        require_visit_authority(actor,visit,'READ',always=True)
        can_record=True
        try:require_visit_authority(actor,visit,'RECORD',always=True)
        except PermissionDenied:can_record=False
        head=ClinicalEncounter.objects.filter(visit=visit).first()
        draft=ClinicalDraft.objects.filter(encounter=head).first() if head else None
        current=current_record(head) if head else None
        displayed=current
        if revision is not None:
            try:
                number=int(revision)
                if number<1:raise ValueError
                displayed=ClinicalRecordVersion.objects.filter(encounter=head,revision=number).first() if head else None
                if displayed is None:raise ValueError
            except (TypeError,ValueError):raise Http404('未找到本次检查的指定版本。')
        working_draft=draft if revision is None else None
        payload=normalize_draft(working_draft.payload) if working_draft else record_payload(displayed) if displayed else normalize_draft({})
        can_edit=can_record and visit.patient.is_active and head is not None and (draft is not None or (current is None and visit.status=='CHECKED_IN')) and revision is None
        return dict(visit=visit,encounter=head,draft=working_draft,clinical_record=displayed,current_record=current,payload=payload,
            can_record=can_record,can_edit=can_edit,can_start=can_record and visit.patient.is_active and head is None and visit.status=='CHECKED_IN',
            can_amend=can_record and visit.patient.is_active and current is not None and draft is None and revision is None,
            history_rows=list(visible_history(visit.patient_id,visit.clinic_id).select_related('scope_clinic')[:50]),
            selected_history=visible_history(visit.patient_id,visit.clinic_id).filter(pk=payload['history_id']).first() if payload.get('history_id') else None,
            versions=list(ClinicalRecordVersion.objects.filter(encounter=head).order_by('-revision')) if head else [],
            newer_history=bool(current and current.history_cursor!=history_cursor(visit.patient_id,visit.clinic_id)),
            findings=payload['findings'] if draft and revision is None else list(displayed.findings.values('tooth','surface','kind','detail')) if displayed else [])
