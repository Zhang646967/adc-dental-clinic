"""Retryable bounded archive generation; files are never served before atomic publication."""
import hashlib,uuid
from django.conf import settings
from django.db import transaction
from accounts.models import UserAccount
from clinical.archive_models import ClinicalArchive,ArchiveSubmission,ArchivePackage
from clinical.archive_sources import capture,digest,plain
from clinical import archives,archive_policies as policy
from clinical.archive_pdf import render,RENDERER
from adc_core.operational_logging import emit_event


def _finish(submission_id,pdf,render_info,error=''):
    peek=ArchiveSubmission.objects.select_related('archive__encounter__visit').get(pk=submission_id)
    with transaction.atomic():
        list(UserAccount.objects.select_for_update().filter(pk__in=[peek.submitted_by_id,peek.reviewed_by_id]).order_by('pk'))
        visit,_=archives.lock_source(peek.archive.encounter.visit_id)
        head=ClinicalArchive.objects.select_for_update().get(pk=peek.archive_id)
        row=ArchiveSubmission.objects.select_for_update().get(pk=peek.pk)
        if row.state!='APPROVED':return dict(id=row.pk,state=row.state,published=False)
        if error:
            row.state='FAILED';row.generation_error=error
        else:
            current=capture(visit,fee_version_id=row.snapshot['fee']['id'] if row.snapshot['fee'] else None)
            previous=archives.latest_package(head)
            if not policy.approval_valid(visit,row.reviewed_by_id,row.approval_scope) or digest(current)!=row.source_digest or (previous.pk if previous else None)!=row.previous_package_id:
                row.state='STALE';row.generation_error='SOURCE_OR_AUTHORITY_CHANGED'
            else:
                number=previous.number+1 if previous else 1
                manifest=plain(dict(contract='adc.archive-manifest.c33a.v1',archive=head.pk,package_number=number,
                    previous=previous.pk if previous else None,kind=row.kind,source_digest=row.source_digest,
                    document_version=row.document_version_id,source_snapshot=row.snapshot,
                    review=dict(account=row.reviewed_by_id,reviewer=row.reviewer_id,at=row.reviewed_at,note=row.review_note,scope=row.approval_scope),
                    file_sha256=hashlib.sha256(pdf).hexdigest(),**render_info))
                package=ArchivePackage.objects.create(archive=head,submission=row,number=number,previous=previous,
                    pdf=pdf,pdf_sha256=manifest['file_sha256'],manifest=manifest,renderer=RENDERER)
                row.state='PUBLISHED';row.generation_error=''
        row.attempts+=1;row.revision+=1
        row.save(update_fields=['state','attempts','revision','generation_error'])
        head.revision+=1;head.save(update_fields=['revision'])
        archives.event(None,head,'GENERATION_'+row.state,uuid.uuid5(uuid.NAMESPACE_OID,'archive:'+str(row.pk)+':'+str(row.attempts)),
            submission=row,package=package if row.state=='PUBLISHED' else None,
            snapshot={'state':row.state,'attempt':row.attempts,'error':row.generation_error})
        return dict(id=row.pk,state=row.state,published=row.state=='PUBLISHED')


def generate(submission_id):
    if settings.ADC_READ_ONLY:return dict(id=submission_id,state='READ_ONLY',published=False)
    row=ArchiveSubmission.objects.select_related('previous_package').get(pk=submission_id)
    if row.state!='APPROVED':return dict(id=row.pk,state=row.state,published=False)
    try:
        pdf,info=render(row.snapshot,number=row.previous_package.number+1 if row.previous_package_id else 1,
            kind=row.kind,review=row.approval_scope)
    except Exception:
        # PDF exceptions may include clinical text. Retain only a bounded category in operational logs.
        emit_event('command.failed')
        return _finish(row.pk,None,{},error='PDF_RENDER_FAILED')
    return _finish(row.pk,pdf,info)


def generate_batch(limit=1):
    if settings.ADC_READ_ONLY:return []
    ids=list(ArchiveSubmission.objects.filter(state='APPROVED').order_by('reviewed_at','pk').values_list('pk',flat=True)[:limit])
    return [generate(pk) for pk in ids]
