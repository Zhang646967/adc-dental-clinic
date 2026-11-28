"""Original dentist's internal response to a patient's decision to pause follow-up."""
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from care.audit import emit
from clinical.authority import professional_scope, readable_assigned_visits, require_visit_authority
from clinical.continuity_models import RecallEpisode, RecallEvent
from clinical.examination_followup import instruction_project_revision, visible_instructions
from clinical.locking import lock_clinical_visit
from clinical.models import ProfessionalAuthorization
from clinical.plan_models import NextVisitInstruction
from clinical.plan_payload import text
from clinical.recall_worklist import DECISIONS, review_facts, review_label
from patients.models import Patient
from workspaces.context import require_active

CONTRACT = 'adc.recall-dentist-review.v1'
ROLES = ('DENTIST',)


def authorized_instructions(actor):
    require_active(actor, ROLES)
    if not actor.dentist_id:
        raise PermissionDenied('请使用原接诊医师身份。')
    visits = readable_assigned_visits(actor, actor.dentist_id, strict=True)
    now = timezone.now()
    scopes = ProfessionalAuthorization.objects.filter(user=actor, clinic_id=OuterRef('source_record__encounter__visit__clinic_id'),
        service_id=OuterRef('service_id'), state='APPROVED', can_read=True, valid_from__lte=now, valid_until__gt=now)
    if not settings.ADC_CLINICAL_SYNTHETIC:
        scopes = scopes.exclude(source_kind='SYNTHETIC')
    rows = NextVisitInstruction.objects.filter(Exists(scopes), source_record__encounter__visit_id__in=visits.values('pk'),
        recall__isnull=False).select_related('recall', 'source_record__encounter__visit__patient',
        'source_record__encounter__visit__clinic', 'service')
    return review_facts(visible_instructions(rows))


def queue(actor, reviewed=False):
    rows = authorized_instructions(actor).filter(state='OPEN', recall__state='REVIEW', decline_id__isnull=False)
    if reviewed:
        rows = rows.filter(review_event_id__gt=F('decline_id'))
    else:
        rows = rows.filter(Q(review_event_id__isnull=True) | Q(review_event_id__lt=F('decline_id')))
    return rows.order_by('recall__followup_due_at', 'pk')


def authorize_record(actor, row, *, lock=False):
    source = row.source_record.encounter.visit
    require_visit_authority(actor, source, 'RECORD', always=True, lock=lock)
    professional_scope(actor.pk, source.clinic_id, row.service_id, 'RECORD', lock=lock)


def check_pending(row):
    if row.state != 'OPEN' or row.recall.state != 'REVIEW' or not row.decline_id:
        raise RuleError('这项复诊已有变化，请返回清单查看当前安排。')
    if review_label(row):
        raise RuleError('本次暂缓已有医师意见，请查看已核对记录。')


def prepare(*, actor, instruction_id, decision, note):
    row = get_object_or_404(authorized_instructions(actor), pk=instruction_id)
    authorize_record(actor, row)
    check_pending(row)
    if decision not in DECISIONS:
        raise RuleError('请选择对本次暂缓的处理意见。')
    values = dict(decision=decision, decision_label=DECISIONS[decision], note=text(note, 500, '核对依据', True))
    data = dict(instruction=row.pk, visit=row.source_record.encounter.visit_id, episode=row.recall.pk,
        instruction_revision=row.revision, revision=row.recall.revision, decline=row.decline_id, values=values,
        report_project_revision=instruction_project_revision(row.pk))
    return dict(proposal_token=proposal(actor, CONTRACT, ROLES, data), values=values)


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm(*, actor, proposal_token, confirmed):
    if confirmed is not True:
        raise RuleError('请核对患者和本次暂缓情况后明确确认。')
    signed = read_proposal(actor, CONTRACT, ROLES, proposal_token)
    data = signed['data']
    source = lock_clinical_visit(actor, data['visit'])
    Patient.objects.select_for_update().get(pk=source.patient_id, is_active=True)
    project_revision = instruction_project_revision(data['instruction'], lock=True)
    row = NextVisitInstruction.objects.select_for_update(of=('self',)).get(pk=data['instruction'], source_record__encounter__visit=source)
    professional_scope(actor.pk, source.clinic_id, row.service_id, 'RECORD', lock=True)
    episode = RecallEpisode.objects.select_for_update().get(pk=data['episode'], instruction=row)
    read_proposal(actor, CONTRACT, ROLES, proposal_token)
    prior = RecallEvent.objects.filter(operation_id=signed['operation']).first()
    if prior:
        if (prior.actor_id, prior.episode_id, prior.action) != (actor.pk, episode.pk, 'DENTIST_REVIEW'):
            raise RuleError('该操作已有其他处理记录。')
        return episode, True
    current = get_object_or_404(authorized_instructions(actor), pk=row.pk)
    if project_revision != data.get('report_project_revision'):
        raise RuleError('检查项目的开通状态已变化，请重新核对复诊指示。')
    check_pending(current)
    if (row.revision, episode.revision, current.decline_id) != (data['instruction_revision'], data['revision'], data['decline']):
        raise RuleError('随访情况已有变化，请重新核对本次暂缓。')
    episode.revision += 1
    episode.save(update_fields=['revision'])
    values = data['values']
    event = RecallEvent.objects.create(episode=episode, actor=actor, action='DENTIST_REVIEW', note=values['note'],
        operation_id=signed['operation'], snapshot=dict(revision=episode.revision, state=episode.state,
            decision=values['decision'], instruction_revision=row.revision, decline=current.decline_id))
    emit(actor, 'CLINICAL_RECALL_DENTIST_REVIEW', episode, visit=source,
        summary={'recall': episode.pk, 'event': event.pk, 'revision': episode.revision})
    return episode, False
