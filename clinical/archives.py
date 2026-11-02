"""Preview/confirm archive operations. No clinical, scheduling or financial facts are created here."""
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
from accounts.models import UserAccount,RoleAssignment
from accounts.policies import require_writable
from care.audit import emit
from clinical.authority import professional_scope,visit_service_id
from clinical.authority_services import lock_people,text
from clinical.archive_models import ClinicalArchive,ArchiveSubmission,ArchivePackage,ArchiveEvent
from clinical.archive_sources import capture,digest
from clinical import archive_policies as policy
from clinical.document_models import ClinicalDocument
from clinical.models import ClinicalEncounter
from patients.models import Patient
from scheduling.models import Visit
from scheduling.coordination import lock_slots
from workspaces.context import require_active

SUBMIT='adc.archive-submit.c33a.v1'
REVIEW='adc.archive-review.c33a.v1'
ACTION='adc.archive-action.c33a.v1'


def latest_package(head,*,formal=False):
    rows=ArchivePackage.objects.filter(archive=head)
    if formal:rows=rows.filter(submission__kind='ARCHIVE')
    return rows.order_by('-number').first()


def open_archive(encounter,actor):
    """Only new confirmations or explicit requests create work, never a data backfill."""
    return ClinicalArchive.objects.get_or_create(encounter=encounter,defaults=dict(responsible=actor,
        due_at=timezone.now()+timedelta(hours=getattr(settings,'ADC_ARCHIVE_DUE_HOURS',24))))[0]


def lock_source(visit_id):
    preview=Visit.objects.only('availability_slot_id').get(pk=visit_id)
    lock_slots([preview.availability_slot_id])
    visit=Visit.objects.select_for_update(of=('self',)).select_related('patient','clinic','dentist').get(pk=visit_id)
    Patient.objects.select_for_update().get(pk=visit.patient_id)
    encounter=ClinicalEncounter.objects.select_for_update().get(visit=visit)
    list(ClinicalDocument.objects.select_for_update().filter(encounter=encounter))
    return visit,encounter


def lock_owner(actor,visit_id):
    lock_people(actor)
    preview=Visit.objects.select_related('dentist').get(pk=visit_id)
    policy.owner(actor,preview,lock=True)
    visit,encounter=lock_source(visit_id)
    return visit,encounter


def event(actor,head,action,op,*,submission=None,amendment=None,package=None,note='',snapshot=None):
    return ArchiveEvent.objects.create(archive=head,submission=submission,amendment=amendment,package=package,
        actor=actor,action=action,operation_id=op,note=note,snapshot=snapshot or {})


def replay(actor,op,action,head):
    old=ArchiveEvent.objects.filter(operation_id=op).first()
    if old and (old.actor_id!=actor.pk or old.action!=action or old.archive_id!=head.pk):
        raise RuleError('此操作编号已用于其他归档事项，请重新打开。')
    return old


def prepare_submit(*,actor,visit_id,kind='ARCHIVE',reason,fee_version_id=None,reviewer_id=None):
    with reporting_snapshot():
        visit=Visit.objects.select_related('patient','clinic','dentist').get(pk=visit_id)
        policy.owner(actor,visit)
        if kind not in ('ARCHIVE','MATERIALS'):raise RuleError('请选择完整归档或缺项资料保全。')
        snapshot=capture(visit,fee_version_id=fee_version_id)
        if kind=='ARCHIVE' and snapshot['issues']:raise RuleError('归档缺项：'+snapshot['issues'][0]['message'])
        if visit.status not in ('COMPLETED','CLOSED_NO_TREATMENT'):raise RuleError('请先完成本次接诊，再办理归档或缺项资料保全。')
        appointed=policy.choose_reviewer(visit,snapshot,author_id=actor.pk,appointment_id=reviewer_id)
        head=ClinicalArchive.objects.filter(encounter__visit=visit).first()
        previous=latest_package(head) if head else None
        data=dict(visit=visit.pk,revision=head.revision if head else 0,kind=kind,reason=text(reason,'归档办理依据',1000),
            digest=digest(snapshot),document=snapshot['document']['id'] if snapshot['document'] else None,
            fee= snapshot['fee']['id'] if snapshot['fee'] else None,previous=previous.pk if previous else None,
            reviewer=appointed.pk,reviewer_revision=appointed.revision)
        return dict(visit=visit,snapshot=snapshot,selected_reviewer=appointed,kind_label=dict(ArchiveSubmission.KINDS)[kind],reason=data['reason'],
            proposal_token=proposal(actor,SUBMIT,('DENTIST',),data))


@business_errors
@transaction.atomic
def confirm_submit(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请明确核对就诊人、完整性、准确版本和审核责任人。')
    p=read_proposal(actor,SUBMIT,('DENTIST',),proposal_token);d=p['data']
    visit,encounter=lock_owner(actor,d['visit']);read_proposal(actor,SUBMIT,('DENTIST',),proposal_token)
    head=open_archive(encounter,actor);head=ClinicalArchive.objects.select_for_update().get(pk=head.pk)
    old=replay(actor,p['operation'],'SUBMIT',head)
    if old:return old.submission,True
    if head.revision!=d['revision']:raise RuleError('归档工作台已变化，请重新核对当前进度。')
    snapshot=capture(visit,fee_version_id=d['fee'])
    if visit.status not in ('COMPLETED','CLOSED_NO_TREATMENT'):raise RuleError('本次接诊状态已变化，请先完成实际接诊。')
    if d['kind']=='ARCHIVE' and snapshot['issues']:raise RuleError('归档缺项：'+snapshot['issues'][0]['message'])
    appointed=policy.choose_reviewer(visit,snapshot,author_id=actor.pk,appointment_id=d['reviewer'])
    if digest(snapshot)!=d['digest'] or appointed.revision!=d['reviewer_revision']:raise RuleError('文书、医疗事实或审核职责已变化，请重新预览。')
    previous=latest_package(head)
    if (previous.pk if previous else None)!=d['previous']:raise RuleError('已有新归档包，请核对最新版本。')
    if ArchiveSubmission.objects.filter(archive=head,state__in=['PENDING','APPROVED','FAILED']).exists():
        raise RuleError('已有待审核或生成的申请，请继续原申请；需要更换内容时先撤回原申请。')
    if previous and previous.submission.kind==d['kind'] and previous.submission.source_digest==d['digest']:
        raise RuleError('此准确版本已有固定文件，无需重复归档。')
    number=(ArchiveSubmission.objects.filter(archive=head).order_by('-number').values_list('number',flat=True).first() or 0)+1
    row=ArchiveSubmission.objects.create(archive=head,number=number,kind=d['kind'],document_version_id=d['document'],
        previous_package=previous,snapshot=snapshot,source_digest=d['digest'],reason=d['reason'],submitted_by=actor,
        assigned_reviewer=appointed,due_at=timezone.now()+timedelta(hours=getattr(settings,'ADC_ARCHIVE_REVIEW_DUE_HOURS',24)),operation_id=p['operation'])
    head.revision+=1;head.save(update_fields=['revision'])
    event(actor,head,'SUBMIT',p['operation'],submission=row,snapshot={'number':number,'kind':row.kind,'digest':row.source_digest})
    emit(actor,'ARCHIVE_SUBMITTED',row,visit=visit,summary={'archive':head.pk,'kind':row.kind,'number':row.number})
    return row,False


def prepare_review(*,actor,submission_id,decision,note):
    with reporting_snapshot():
        row=ArchiveSubmission.objects.select_related('archive__encounter__visit__dentist').get(pk=submission_id)
        visit=row.archive.encounter.visit
        appointed=policy.reviewer(actor,visit,row.snapshot,author_id=row.submitted_by_id)
        if appointed.pk!=row.assigned_reviewer_id:raise PermissionDenied('本申请已指定另一名独立审核医师。')
        if decision not in ('APPROVE','RETURN','REJECT'):raise RuleError('请选择通过、退回或不通过。')
        if row.state!='PENDING':raise RuleError('此申请已有办理结果，请查看保留历史。')
        return dict(submission=row,snapshot=row.snapshot,decision=decision,note=note,proposal_token=proposal(actor,REVIEW,('DENTIST',),dict(
            submission=row.pk,revision=row.revision,decision=decision,note=text(note,'医务审核意见',1000),
            reviewer=appointed.pk,reviewer_revision=appointed.revision)))


@business_errors
@transaction.atomic
def confirm_review(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请以本人独立医务审核身份确认此准确清单。')
    p=read_proposal(actor,REVIEW,('DENTIST',),proposal_token);d=p['data']
    peek=ArchiveSubmission.objects.select_related('archive__encounter__visit').get(pk=d['submission'])
    lock_people(actor,peek.submitted_by_id)
    appointed=policy.reviewer(actor,peek.archive.encounter.visit,peek.snapshot,author_id=peek.submitted_by_id,lock=True)
    visit,_=lock_source(peek.archive.encounter.visit_id)
    head=ClinicalArchive.objects.select_for_update().get(pk=peek.archive_id)
    row=ArchiveSubmission.objects.select_for_update().get(pk=peek.pk)
    read_proposal(actor,REVIEW,('DENTIST',),proposal_token)
    old=replay(actor,p['operation'],'REVIEW',head)
    if old:return old.submission,True
    if row.state!='PENDING' or row.revision!=d['revision']:raise RuleError('另一页面已处理此申请，请查看当前结果。')
    if appointed.pk!=row.assigned_reviewer_id or appointed.pk!=d['reviewer'] or appointed.revision!=d['reviewer_revision']:
        raise PermissionDenied('指定审核人或职责已变化，请重新核对。')
    if d['decision']=='APPROVE':
        current=capture(visit,fee_version_id=row.snapshot['fee']['id'] if row.snapshot['fee'] else None)
        if digest(current)!=row.source_digest:raise RuleError('提交后来源已变化，不能审核旧内容；请退回后重新提交。')
        if row.kind=='ARCHIVE' and current['issues']:raise RuleError('仍有必要材料缺项，不能正常完整归档。')
        previous=latest_package(head)
        if (previous.pk if previous else None)!=row.previous_package_id:raise RuleError('最新归档包已变化，请重新提交准确补充版本。')
        row.approval_scope=policy.stamp(actor,visit,current,appointed)
    row.state={'APPROVE':'APPROVED','RETURN':'RETURNED','REJECT':'REJECTED'}[d['decision']]
    row.reviewed_by=actor;row.reviewer=appointed;row.review_note=d['note'];row.reviewed_at=timezone.now();row.revision+=1
    if d['decision']=='APPROVE':
        row.approval_scope['signoff']=dict(name=actor.dentist.name,account=actor.pk,recorded_at=row.reviewed_at.isoformat(),reference=appointed.reference)
    row.save(update_fields=['state','reviewed_by','reviewer','review_note','reviewed_at','revision','approval_scope'])
    head.revision+=1;head.save(update_fields=['revision'])
    event(actor,head,'REVIEW',p['operation'],submission=row,note=d['note'],snapshot={'decision':d['decision'],'state':row.state})
    emit(actor,'ARCHIVE_REVIEWED',row,visit=visit,summary={'archive':head.pk,'decision':d['decision']})
    return row,False


def prepare_action(*,actor,submission_id,action,reason):
    row=ArchiveSubmission.objects.select_related('archive__encounter__visit').get(pk=submission_id)
    policy.owner(actor,row.archive.encounter.visit)
    if action not in ('WITHDRAW','RETRY'):raise RuleError('未知归档办理操作。')
    return dict(submission=row,action_label='明确重试生成' if action=='RETRY' else '撤回未完成的申请',reason=reason,proposal_token=proposal(actor,ACTION,('DENTIST',),dict(
        submission=row.pk,revision=row.revision,action=action,reason=text(reason,'办理依据',1000))))


@business_errors
@transaction.atomic
def confirm_action(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请明确确认本次归档办理操作。')
    p=read_proposal(actor,ACTION,('DENTIST',),proposal_token);d=p['data']
    peek=ArchiveSubmission.objects.select_related('archive__encounter__visit').get(pk=d['submission'])
    visit,_=lock_owner(actor,peek.archive.encounter.visit_id)
    head=ClinicalArchive.objects.select_for_update().get(pk=peek.archive_id)
    row=ArchiveSubmission.objects.select_for_update().get(pk=peek.pk)
    read_proposal(actor,ACTION,('DENTIST',),proposal_token)
    old=replay(actor,p['operation'],d['action'],head)
    if old:return row,True
    if row.revision!=d['revision']:raise RuleError('申请进度已变化，请重新核对。')
    if d['action']=='WITHDRAW':
        if row.state not in ('PENDING','APPROVED','FAILED'):raise RuleError('此申请已结束，不能撤回历史。')
        row.state='STALE'
    else:
        if row.state!='FAILED':raise RuleError('只对已记录的生成失败明确重试。')
        if not policy.approval_valid(visit,row.reviewed_by_id,row.approval_scope):raise RuleError('审核适用职责已变化，请撤回后重新提交。')
        current=capture(visit,fee_version_id=row.snapshot['fee']['id'] if row.snapshot['fee'] else None)
        if digest(current)!=row.source_digest:raise RuleError('资料已变化，请重新提交，不能重试旧清单。')
        row.state='APPROVED'
    row.revision+=1;row.save(update_fields=['state','revision'])
    head.revision+=1;head.save(update_fields=['revision'])
    event(actor,head,d['action'],p['operation'],submission=row,note=d['reason'],snapshot={'state':row.state})
    emit(actor,'ARCHIVE_'+d['action'],row,visit=visit,summary={'archive':head.pk})
    return row,False
