"""Scoped archive work, frozen details and content-only amendment comparison."""
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db.models import Q,Exists,OuterRef,Subquery,Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from accounts.policies import clinic_ids
from clinical.authority import require_visit_authority,require_reviewer,professional_scope,visit_service_id,readable_assigned_visits
from clinical.archive_models import ClinicalArchive,ArchiveSubmission,ArchivePackage,ArchiveAmendment
from clinical.archive_sources import capture,plain
from clinical import archives,archive_policies as policy
from clinical.document_models import ClinicalDocument,ClinicalDocumentDraft,ClinicalDocumentVersion
from clinical.documents import normalize,source_projection
from clinical.encounter_models import ClinicalEncounter,ClinicalDraft
from clinical.encounters import history_cursor
from clinical.clinical_payload import normalize_draft,draft_digest
from scheduling.models import Visit
from workspaces.context import require_active


def candidate_without_actor(visit,target):
    """Fingerprint comparison only, after reviewer authorization. Never confirms a clinical fact."""
    encounter=ClinicalEncounter.objects.get(visit=visit)
    if target=='DOCUMENT':
        head=ClinicalDocument.objects.get(encounter=encounter);draft=ClinicalDocumentDraft.objects.get(document=head)
        payload=normalize(draft.payload,complete=True)
        snapshot,cursor,_,_=source_projection(None,visit,encounter,check_plan_authority=False)
        data=dict(visit=visit.pk,document=head.pk,revision=head.revision,base=draft.base_version_id,
            digest=draft_digest(payload),source_cursor=cursor,snapshot_digest=draft_digest(snapshot))
        before=ClinicalDocumentVersion.objects.filter(document=head).order_by('-revision').first().content
        return plain(dict(target=target,payload=payload,context=data,source=snapshot,before=before))
    draft=ClinicalDraft.objects.get(encounter=encounter);payload=normalize_draft(draft.payload,complete=True)
    data=dict(visit=visit.pk,encounter=encounter.pk,revision=encounter.revision,digest=draft_digest(payload),
        base_record=draft.base_record_id,history_cursor=history_cursor(visit.patient_id,visit.clinic_id))
    from clinical.encounters import current_record,record_payload
    return plain(dict(target=target,payload=payload,context=data,before=record_payload(current_record(encounter))))


def authorize_read(actor,visit):
    require_active(actor,('DENTIST',))
    if actor.dentist_id==visit.dentist_id:
        require_visit_authority(actor,visit,'READ',always=True)
    else:
        duty=require_reviewer(actor,visit.clinic_id)
        if not duty.can_review_archives:raise PermissionDenied('没有本店医务归档查阅职责。')
        professional_scope(actor.pk,visit.clinic_id,visit_service_id(visit),'READ')
        snapshot=capture(visit)
        policy.reviewer(actor,visit,snapshot,author_id=visit.dentist.useraccount.pk)


def details(actor,visit_id):
    visit=get_object_or_404(Visit.objects.select_related('patient','clinic','dentist'),pk=visit_id)
    authorize_read(actor,visit)
    head=ClinicalArchive.objects.filter(encounter__visit=visit).first()
    can_submit=False
    try:policy.owner(actor,visit);can_submit=not settings.ADC_READ_ONLY
    except PermissionDenied:pass
    snapshot=capture(visit)
    latest=archives.latest_package(head)
    return dict(visit=visit,archive=head,can_submit=can_submit,snapshot=snapshot,
        reviewer_options=policy.reviewer_options(visit,snapshot,author_id=visit.dentist.useraccount.pk) if can_submit else [],
        submissions=ArchiveSubmission.objects.filter(archive=head).select_related('assigned_reviewer__user','reviewed_by').order_by('-number'),
        packages=ArchivePackage.objects.filter(archive=head).defer('pdf').select_related('submission__reviewed_by','submission__document_version').order_by('-number'),
        amendments=ArchiveAmendment.objects.filter(archive=head).select_related('assigned_reviewer__user','reviewed_by').order_by('-pk'),
        current_package=latest,
        amendment_needed=bool(latest and snapshot['document'] and latest.submission.document_version_id!=snapshot['document']['id']),
        now=timezone.now())


def worklist(actor):
    require_active(actor,('DENTIST',))
    now=timezone.now();assigned=readable_assigned_visits(actor,actor.dentist_id,strict=True)
    owned=ClinicalDocument.objects.filter(encounter__visit__in=assigned,encounter__visit__status__in=['COMPLETED','CLOSED_NO_TREATMENT']).select_related('encounter__visit__clinic').annotate(
        archive_id_value=Subquery(ClinicalArchive.objects.filter(encounter_id=OuterRef('encounter_id')).values('pk')[:1]),
        archived=Exists(ArchivePackage.objects.filter(archive__encounter_id=OuterRef('encounter_id'),submission__kind='ARCHIVE')))
    scope=dict(assigned_reviewer__user=actor,assigned_reviewer__is_active=True,assigned_reviewer__can_review_archives=True,
        assigned_reviewer__valid_from__lte=now,assigned_reviewer__valid_until__gt=now,
        archive__encounter__visit__in=readable_assigned_visits(actor,None,strict=True))
    return dict(owned=owned.order_by('due_at','pk'),
        reviews=ArchiveSubmission.objects.filter(state='PENDING',**scope).select_related('archive__encounter__visit__clinic','submitted_by').order_by('due_at','pk'),
        correction_reviews=ArchiveAmendment.objects.filter(state='PENDING',**scope).select_related('archive__encounter__visit__clinic','requested_by').order_by('due_at','pk'),now=now)


def summary(actor):
    ctx=require_active(actor,('FRONT_DESK','MANAGER','HQ'))
    heads=ClinicalArchive.objects.all()
    if actor._adc_workspace.role!='HQ':heads=heads.filter(encounter__visit__clinic_id__in=clinic_ids(actor,roles=('FRONT_DESK','MANAGER')))
    counts=heads.values('encounter__visit__clinic__name').annotate(total=Count('pk',distinct=True),
        archived_total=Count('pk',filter=Q(packages__submission__kind='ARCHIVE'),distinct=True),
        pending_total=Count('pk',filter=Q(submissions__state='PENDING'),distinct=True),
        failed_total=Count('pk',filter=Q(submissions__state='FAILED'),distinct=True)).order_by('encounter__visit__clinic__name')
    heads=heads.annotate(archived=Exists(ArchivePackage.objects.filter(archive_id=OuterRef('pk'),submission__kind='ARCHIVE')),
        materials=Exists(ArchivePackage.objects.filter(archive_id=OuterRef('pk'),submission__kind='MATERIALS')),
        pending=Exists(ArchiveSubmission.objects.filter(archive_id=OuterRef('pk'),state='PENDING')),
        generation_failed=Exists(ArchiveSubmission.objects.filter(archive_id=OuterRef('pk'),state='FAILED')),
        review_owner=Subquery(ArchiveSubmission.objects.filter(archive_id=OuterRef('pk'),state__in=['PENDING','APPROVED','FAILED']).order_by('-number').values('assigned_reviewer__user__username')[:1]))
    return dict(counts=counts,front_rows=heads.select_related('encounter__visit','responsible').order_by('due_at','pk') if actor._adc_workspace.role=='FRONT_DESK' else [],now=timezone.now())
