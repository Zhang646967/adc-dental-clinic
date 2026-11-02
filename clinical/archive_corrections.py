"""Exact-content medical approval before appending to archived documents or examinations."""
from datetime import timedelta
import uuid
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from adc_core.commands import business_errors
from adc_core.proposals import proposal,read_proposal
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from care.audit import emit
from clinical.archive_models import ClinicalArchive,ArchiveAmendment
from clinical.archive_sources import capture,plain,digest
from clinical import archives,archive_policies as policy
from clinical.authority_services import lock_people,text
from scheduling.models import Visit

SUBMIT='adc.archive-amendment.c33a.v1'
REVIEW='adc.archive-amendment-review.c33a.v1'
CANCEL='adc.archive-amendment-cancel.c33a.v1'


def candidate(actor,visit_id,target):
    from clinical.document_models import ClinicalDocumentDraft
    from clinical.encounter_models import ClinicalDraft
    if target=='DOCUMENT' and not ClinicalDocumentDraft.objects.filter(document__encounter__visit_id=visit_id).exists():
        raise RuleError('请先在病历文书中保存准备补正的准确草稿，再提交独立审核。')
    if target=='RECORD' and not ClinicalDraft.objects.filter(encounter__visit_id=visit_id).exists():
        raise RuleError('请先在检查工作台保存准备补正的准确草稿，再提交独立审核。')
    if target=='DOCUMENT':
        from clinical import documents
        p=documents.prepare_document(actor=actor,visit_id=visit_id,archive_check=False)
        context=read_proposal(actor,documents.CONTRACT,('DENTIST',),p['proposal_token'])['data']
        from clinical.documents import latest_version
        from clinical.document_models import ClinicalDocument
        before=latest_version(ClinicalDocument.objects.get(encounter__visit_id=visit_id)).content
        return plain(dict(target=target,payload=p['payload'],context=context,source=p['source'],before=before))
    if target=='RECORD':
        from clinical import encounters
        p=encounters.prepare_record(actor=actor,visit_id=visit_id,archive_check=False)
        context=read_proposal(actor,encounters.CONTRACT,('DENTIST',),p['proposal_token'])['data']
        return plain(dict(target=target,payload=p['payload'],context=context,before=encounters.record_payload(encounters.current_record(p['encounter']))))
    raise RuleError('请选择完整文书或检查及牙位的准确更正草稿。')


def lock_participants(actor,visit_id,target):
    ids=list(ArchiveAmendment.objects.filter(archive__encounter__visit_id=visit_id,target=target,state='APPROVED').values_list('reviewed_by_id',flat=True))
    lock_people(actor,*[v for v in ids if v])


def required(actor,visit_id,target,*,lock=False):
    head=ClinicalArchive.objects.filter(encounter__visit_id=visit_id).first()
    package=archives.latest_package(head,formal=True) if head else None
    if package is None:return None
    qs=ArchiveAmendment.objects.filter(archive=head,target=target,state='APPROVED',base_package=package)
    if lock:qs=qs.select_for_update()
    row=qs.first()
    if row is None:raise RuleError('本次病历已归档；请在“病历归档与补正”提交准确草稿，先取得独立医务批准。')
    if row.requested_by_id!=actor.pk:raise PermissionDenied('不能使用另一名医师的补正批准。')
    current=candidate(actor,visit_id,target)
    if digest(current)!=row.candidate_digest:raise RuleError('草稿或来源与获准补正内容不一致，请重新提交准确版本。')
    visit=Visit.objects.select_related('dentist').get(pk=visit_id)
    if not policy.approval_valid(visit,row.reviewed_by_id,row.approval_scope):
        raise PermissionDenied('原补正审核职责或专业范围已失效，请重新核对。')
    return row


def consume(row,actor,version,operation_id):
    if row is None:return
    row.state='APPLIED';row.revision+=1
    if row.target=='DOCUMENT':row.result_document=version
    else:row.result_record=version
    row.save(update_fields=['state','revision','result_document','result_record'])
    head=ClinicalArchive.objects.select_for_update().get(pk=row.archive_id)
    head.revision+=1;head.save(update_fields=['revision'])
    archives.event(actor,head,'AMENDMENT_APPLIED',uuid.uuid5(uuid.NAMESPACE_OID,str(operation_id)+':archive-amendment'),
        amendment=row,snapshot={'target':row.target,'version':version.pk})
    emit(actor,'ARCHIVE_AMENDMENT_APPLIED',row,summary={'archive':head.pk,'target':row.target,'version':version.pk})


def document_confirmed(encounter,actor):
    head=archives.open_archive(encounter,actor)
    if archives.latest_package(head,formal=True):
        head.supplement_due_at=timezone.now()+timedelta(hours=getattr(settings,'ADC_ARCHIVE_DUE_HOURS',24))
        head.revision+=1;head.save(update_fields=['supplement_due_at','revision'])


def prepare_submit(*,actor,visit_id,target,reason,reviewer_id=None):
    with reporting_snapshot():
        visit=Visit.objects.select_related('patient','clinic','dentist').get(pk=visit_id);policy.owner(actor,visit)
        head=ClinicalArchive.objects.filter(encounter__visit=visit).first()
        package=archives.latest_package(head,formal=True) if head else None
        if package is None:raise RuleError('本次尚无完整归档包，请按原临床更正流程办理。')
        value=candidate(actor,visit_id,target)
        snapshot=capture(visit)
        appointed=policy.choose_reviewer(visit,snapshot,author_id=actor.pk,appointment_id=reviewer_id)
        data=dict(visit=visit.pk,archive=head.pk,base=package.pk,target=target,revision=head.revision,
            candidate_digest=digest(value),reason=text(reason,'补正原因与差异说明',1000),reviewer=appointed.pk,reviewer_revision=appointed.revision)
        return dict(visit=visit,candidate=value,selected_reviewer=appointed,proposal_token=proposal(actor,SUBMIT,('DENTIST',),data))


@business_errors
@transaction.atomic
def confirm_submit(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请核对准确差异、原因、来源和独立审核人。')
    p=read_proposal(actor,SUBMIT,('DENTIST',),proposal_token);d=p['data']
    visit,_=archives.lock_owner(actor,d['visit'])
    head=ClinicalArchive.objects.select_for_update().get(pk=d['archive'])
    read_proposal(actor,SUBMIT,('DENTIST',),proposal_token)
    old=archives.replay(actor,p['operation'],'AMENDMENT_SUBMIT',head)
    if old:return old.amendment,True
    value=candidate(actor,visit.pk,d['target'])
    appointed=policy.choose_reviewer(visit,capture(visit),author_id=actor.pk,appointment_id=d['reviewer'])
    package=archives.latest_package(head,formal=True)
    if package is None or package.pk!=d['base']:raise RuleError('完整归档基础包已变化，请重新核对。')
    if head.revision!=d['revision'] or digest(value)!=d['candidate_digest'] or appointed.revision!=d['reviewer_revision']:
        raise RuleError('补正草稿、来源或职责已变化，请重新预览。')
    if ArchiveAmendment.objects.filter(archive=head,target=d['target'],state__in=['PENDING','APPROVED']).exists():
        raise RuleError('此类补正已有待办，请继续原申请，或先明确撤回。')
    row=ArchiveAmendment.objects.create(archive=head,base_package_id=d['base'],target=d['target'],candidate=value,
        candidate_digest=d['candidate_digest'],reason=d['reason'],requested_by=actor,assigned_reviewer=appointed,
        due_at=timezone.now()+timedelta(hours=getattr(settings,'ADC_ARCHIVE_REVIEW_DUE_HOURS',24)),operation_id=p['operation'])
    head.revision+=1;head.save(update_fields=['revision'])
    archives.event(actor,head,'AMENDMENT_SUBMIT',p['operation'],amendment=row,note=d['reason'],snapshot={'target':row.target})
    emit(actor,'ARCHIVE_AMENDMENT_SUBMITTED',row,visit=visit,summary={'archive':head.pk,'target':row.target})
    return row,False


def prepare_review(*,actor,amendment_id,decision,note):
    row=ArchiveAmendment.objects.select_related('archive__encounter__visit__dentist').get(pk=amendment_id)
    visit=row.archive.encounter.visit
    appointed=policy.reviewer(actor,visit,row.base_package.submission.snapshot,author_id=row.requested_by_id)
    if appointed.pk!=row.assigned_reviewer_id:raise PermissionDenied('此补正已指定另一名独立审核医师。')
    if decision not in ('APPROVE','RETURN','REJECT'):raise RuleError('请选择通过、退回或不通过。')
    if row.state!='PENDING':raise RuleError('此补正申请已有办理结果，请查看保留历史。')
    return dict(amendment=row,candidate=row.candidate,decision=decision,note=note,proposal_token=proposal(actor,REVIEW,('DENTIST',),dict(
        amendment=row.pk,revision=row.revision,decision=decision,note=text(note,'补正审核意见',1000),
        reviewer=appointed.pk,reviewer_revision=appointed.revision)))


@business_errors
@transaction.atomic
def confirm_review(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请以独立医务审核身份确认准确补正内容。')
    p=read_proposal(actor,REVIEW,('DENTIST',),proposal_token);d=p['data']
    peek=ArchiveAmendment.objects.select_related('archive__encounter__visit').get(pk=d['amendment'])
    lock_people(actor,peek.requested_by_id)
    visit,_=archives.lock_source(peek.archive.encounter.visit_id)
    head=ClinicalArchive.objects.select_for_update().get(pk=peek.archive_id)
    row=ArchiveAmendment.objects.select_for_update().get(pk=peek.pk)
    snapshot=capture(visit);appointed=policy.reviewer(actor,visit,snapshot,author_id=row.requested_by_id,lock=True)
    read_proposal(actor,REVIEW,('DENTIST',),proposal_token)
    old=archives.replay(actor,p['operation'],'AMENDMENT_REVIEW',head)
    if old:return old.amendment,True
    if row.state!='PENDING' or row.revision!=d['revision']:raise RuleError('此补正已经变化或已有结果，请核对。')
    if appointed.pk!=row.assigned_reviewer_id or appointed.pk!=d['reviewer'] or appointed.revision!=d['reviewer_revision']:
        raise PermissionDenied('指定审核职责已变化。')
    if d['decision']=='APPROVE':
        # The responsible author owns clinical drafts; the reviewer never rewrites them.
        from clinical.archive_selectors import candidate_without_actor
        current=candidate_without_actor(visit,row.target)
        if digest(current)!=row.candidate_digest:raise RuleError('待确认内容或来源已有变化，请退回后重新提交准确草稿。')
        if archives.latest_package(head,formal=True).pk!=row.base_package_id:raise RuleError('完整归档基础包已变化，请重新提交。')
        row.approval_scope=policy.stamp(actor,visit,snapshot,appointed)
    row.state={'APPROVE':'APPROVED','RETURN':'RETURNED','REJECT':'REJECTED'}[d['decision']]
    row.reviewer=appointed;row.reviewed_by=actor;row.reviewed_at=timezone.now();row.review_note=d['note'];row.revision+=1
    if d['decision']=='APPROVE':
        row.approval_scope['signoff']=dict(name=actor.dentist.name,account=actor.pk,recorded_at=row.reviewed_at.isoformat(),reference=appointed.reference)
    row.save(update_fields=['state','reviewer','reviewed_by','reviewed_at','review_note','revision','approval_scope'])
    head.revision+=1;head.save(update_fields=['revision'])
    archives.event(actor,head,'AMENDMENT_REVIEW',p['operation'],amendment=row,note=d['note'],snapshot={'decision':d['decision']})
    emit(actor,'ARCHIVE_AMENDMENT_REVIEWED',row,visit=visit,summary={'archive':head.pk,'decision':d['decision']})
    return row,False


def prepare_cancel(*,actor,amendment_id,reason):
    row=ArchiveAmendment.objects.select_related('archive__encounter__visit').get(pk=amendment_id)
    policy.owner(actor,row.archive.encounter.visit)
    return dict(amendment=row,action_label='撤回未实施的补正',reason=reason,proposal_token=proposal(actor,CANCEL,('DENTIST',),dict(amendment=row.pk,revision=row.revision,reason=text(reason,'撤回依据',1000))))


@business_errors
@transaction.atomic
def confirm_cancel(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请明确撤回未实施的补正申请；已追加的临床版本不删除。')
    p=read_proposal(actor,CANCEL,('DENTIST',),proposal_token);d=p['data']
    peek=ArchiveAmendment.objects.select_related('archive__encounter__visit').get(pk=d['amendment'])
    visit,_=archives.lock_owner(actor,peek.archive.encounter.visit_id)
    head=ClinicalArchive.objects.select_for_update().get(pk=peek.archive_id)
    row=ArchiveAmendment.objects.select_for_update().get(pk=peek.pk)
    read_proposal(actor,CANCEL,('DENTIST',),proposal_token)
    old=archives.replay(actor,p['operation'],'AMENDMENT_CANCEL',head)
    if old:return row,True
    if row.state not in ('PENDING','APPROVED') or row.revision!=d['revision']:raise RuleError('补正已变化或已经实施，请核对当前结果。')
    row.state='CANCELLED';row.revision+=1;row.save(update_fields=['state','revision'])
    head.revision+=1;head.save(update_fields=['revision'])
    archives.event(actor,head,'AMENDMENT_CANCEL',p['operation'],amendment=row,note=d['reason'])
    return row,False
