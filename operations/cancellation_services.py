"""B1.1 commands: retain cancelled facts; explicit work and reviewed measures."""
from datetime import date
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from accounts.models import UserAccount
from accounts.policies import lock_clinic_grant
from adc_core.commands import business_errors, assert_revision
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from care.audit import emit
from scheduling.models import Visit
from operations.models import CancellationFollowUp, AppointmentImprovement, AppointmentActionEvent
from operations.cancellation_policy import serialize_metrics, POLICY
from operations.cancellation_selectors import local_clinic, followup_visits, improvement_scope, cell_metrics, owners

FOLLOW_CONTRACT = 'adc.cancel.followup.v1'
IMPROVE_CONTRACT = 'adc.appointment.improve.v1'

def form_values(form):
    if not form.is_valid():
        raise RuleError('；'.join(str(e) for errors in form.errors.values() for e in errors))
    return form.cleaned_data

def serialize(data):
    return {k: v.isoformat() if isinstance(v, date) else v.pk if isinstance(v, UserAccount) else v for k, v in data.items()}

def follow_fields(actor, visit, data):
    from operations.forms import FollowUpForm
    clean = form_values(FollowUpForm(data, clinic=visit.clinic_id))
    replacement = None
    if clean['state'] == 'REBOOKED':
        replacement = Visit.objects.filter(visit_no=clean['replacement_no'], patient_id=visit.patient_id,
            clinic_id=visit.clinic_id, created_at__gte=visit.created_at).exclude(
            pk=visit.pk).exclude(status__in=['CANCELLED', 'RESCHEDULED', 'NO_SHOW']).first()
        if replacement is None:
            raise RuleError('未找到本店同一患者的有效另约记录，请先核对预约结果。')
    return clean, replacement

def follow_snapshot(row):
    return dict(reason_code=row.reason_code, state=row.state, owner=row.assigned_to_id,
        due_on=row.due_on.isoformat() if row.due_on else None, replacement=row.replacement_visit_id,
        note=row.note, version=row.lock_version)

def prepare_followup(*, actor, visit_id, data):
    with reporting_snapshot():
        visit = followup_visits(actor).get(pk=visit_id)
        clean, replacement = follow_fields(actor, visit, data)
        row = CancellationFollowUp.objects.filter(visit=visit).first()
        payload = dict(visit=visit.pk, visit_version=visit.lock_version, version=row.lock_version if row else None,
            fields=serialize(clean), replacement=replacement.pk if replacement else None)
        return clean, proposal(actor, FOLLOW_CONTRACT, ('FRONT_DESK',), payload)

@business_errors
@transaction.atomic
def confirm_followup(*, actor, visit_id, proposal_token, confirmed):
    if confirmed is not True: raise RuleError('请核对后明确确认联系结果。')
    p = read_proposal(actor, FOLLOW_CONTRACT, ('FRONT_DESK',), proposal_token); d = p['data']
    if d['visit'] != visit_id: raise RuleError('确认内容不属于此预约。')
    list(UserAccount.objects.select_for_update().filter(pk__in=[actor.pk, d['fields']['assigned_to']]).order_by('pk'))
    clinic = local_clinic(actor, ('FRONT_DESK',)); lock_clinic_grant(actor, clinic)
    visit = Visit.objects.select_for_update().get(pk=visit_id, clinic_id=clinic, status='CANCELLED')
    prior = AppointmentActionEvent.objects.filter(operation_id=p['operation'], actor=actor, followup__visit=visit).first()
    if prior: return CancellationFollowUp.objects.get(pk=prior.followup_id), True
    assert_revision(visit, d['visit_version'])
    row = CancellationFollowUp.objects.select_for_update().filter(visit=visit).first()
    if (row.lock_version if row else None) != d['version']:
        raise RuleError('跟进结果已变化，请重新核对，不能覆盖同事记录。')
    clean, replacement = follow_fields(actor, visit, d['fields'])
    if (replacement.pk if replacement else None) != d['replacement']:
        raise RuleError('另约依据已经变化，请重新核对。')
    values = dict(reason_code=clean['reason_code'], state=clean['state'], due_on=clean['due_on'],
        assigned_to=clean['assigned_to'], replacement_visit=replacement, note=clean['note'])
    if row:
        for k, v in values.items(): setattr(row, k, v)
        row.lock_version += 1
        row.save()
    else: row = CancellationFollowUp.objects.create(visit=visit, **values)
    event = AppointmentActionEvent.objects.create(followup=row, operation_id=p['operation'], actor=actor,
        action='FOLLOWUP', snapshot=follow_snapshot(row))
    emit(actor, 'CANCELLATION_FOLLOWUP', event, summary={'clinic':clinic, 'version':row.lock_version})
    return row, False

def improvement_snapshot(row):
    return dict(state=row.state, owner=row.assigned_to_id, due_on=row.due_on.isoformat(),
        execution=row.execution, review_note=row.review_note, assessment=row.assessment,
        baseline=row.baseline, comparison=row.comparison, version=row.lock_version)

def _clean_improvement(actor, row, action, fields, clinic):
    from operations.forms import ImprovementForm, ImprovementStepForm
    if action == 'CREATE':
        if actor._adc_workspace.role != 'MANAGER': raise PermissionDenied
        return form_values(ImprovementForm(fields, clinic=clinic))
    candidates = available_actions(actor, row)
    if action not in {k for k, _ in candidates}: raise RuleError('当前身份或措施状态不允许此操作。')
    if not owners(clinic).filter(pk=row.assigned_to_id).exists() and action not in ('ASSIGN', 'CANCEL'):
        raise RuleError('原负责人已失去授权，请主管先调整责任。')
    clean = form_values(ImprovementStepForm(fields, clinic=clinic, action=action, baseline_end=row.baseline_end))
    if action == 'REVIEW':
        started = row.history.filter(action='START').order_by('-pk').values_list('created_at', flat=True).first()
        if started is None or clean['review_start'] < timezone.localdate(started):
            raise RuleError('后续观察不得早于本次责任分配后的执行开始日。')
    return clean

def prepare_improvement(*, actor, action, fields, pk=None):
    with reporting_snapshot():
        clinic = local_clinic(actor)
        row = improvement_scope(actor).get(pk=pk) if pk else None
        if (row is None) != (action == 'CREATE'): raise RuleError('措施操作来源无效。')
        clean = _clean_improvement(actor, row, action, fields, clinic)
        payload = dict(clinic=clinic, pk=pk, action=action, version=row.lock_version if row else None,
            owner=row.assigned_to_id if row else None, fields=serialize(clean))
        baseline = None
        if action == 'CREATE':
            baseline = serialize_metrics(cell_metrics(clinic, clean['baseline_start'], clean['baseline_end'], clean['weekday'], clean['band']))
            payload['baseline'] = dict(metrics=baseline, as_of=timezone.now().isoformat(), policy=POLICY)
        if action == 'REVIEW':
            payload['comparison'] = dict(metrics=serialize_metrics(cell_metrics(clinic, clean['review_start'],
                clean['review_end'], row.weekday, row.band)), as_of=timezone.now().isoformat(), policy=POLICY)
        return clean, proposal(actor, IMPROVE_CONTRACT, ('MANAGER', 'FRONT_DESK'), payload), payload

@business_errors
@transaction.atomic
def confirm_improvement(*, actor, action, pk, proposal_token, confirmed):
    if confirmed is not True: raise RuleError('请核对后明确确认本次措施办理。')
    p = read_proposal(actor, IMPROVE_CONTRACT, ('MANAGER', 'FRONT_DESK'), proposal_token); d = p['data']
    if d['pk'] != pk or d['action'] != action: raise RuleError('确认内容不属于当前措施操作。')
    people = {actor.pk, d['owner'], d['fields'].get('assigned_to')} - {None}
    list(UserAccount.objects.select_for_update().filter(pk__in=people).order_by('pk'))
    clinic = local_clinic(actor); lock_clinic_grant(actor, clinic, roles=('MANAGER', 'FRONT_DESK'))
    if clinic != d['clinic']: raise PermissionDenied
    row = improvement_scope(actor).select_for_update(of=('self',)).get(pk=pk) if pk else None
    prior = AppointmentActionEvent.objects.filter(operation_id=p['operation'], actor=actor, improvement__clinic_id=clinic).first()
    if prior: return AppointmentImprovement.objects.get(pk=prior.improvement_id), True
    if row: assert_revision(row, d['version'])
    clean = _clean_improvement(actor, row, action, d['fields'], clinic)
    if action == 'CREATE':
        current = serialize_metrics(cell_metrics(clinic, clean['baseline_start'], clean['baseline_end'], clean['weekday'], clean['band']))
        if current != d['baseline']['metrics']:
            raise RuleError('原观察窗口结果已变化，请重新预览。')
        row = AppointmentImprovement.objects.create(clinic_id=clinic, baseline=d['baseline'], **clean)
    else:
        note = clean['note']
        if action == 'START': row.state = 'WORKING'; row.execution = note
        elif action == 'ASSIGN':
            row.assigned_to = clean['assigned_to']; row.due_on = clean['due_on']; row.state = 'OPEN'
            row.submitted_by = None; row.execution = ''
        elif action == 'SUBMIT':
            row.state = 'READY'; row.execution = note; row.submitted_by = actor
        elif action == 'RETURN': row.state = 'WORKING'; row.review_note = note
        elif action == 'CANCEL': row.state = 'CANCELLED'; row.review_note = note
        elif action == 'REVIEW':
            current = serialize_metrics(cell_metrics(clinic, clean['review_start'], clean['review_end'], row.weekday, row.band))
            if current != d['comparison']['metrics']:
                raise RuleError('后续观察结果已变化，请重新预览后复核。')
            if clean['assessment'] == 'OBSERVED' and (not row.baseline['metrics']['eligible'] or not current['eligible']):
                raise RuleError('原窗口或后续窗口样本／完整性不足，请选择如实结论。')
            row.state = 'CLOSED'; row.reviewed_by = actor
            row.review_start = clean['review_start']; row.review_end = clean['review_end']
            row.assessment = clean['assessment']; row.review_note = note; row.comparison = d['comparison']
        row.lock_version += 1; row.save()
    snapshot = improvement_snapshot(row); snapshot['operation_note'] = clean.get('note', row.plan)
    event = AppointmentActionEvent.objects.create(improvement=row, operation_id=p['operation'], actor=actor,
        action=action, snapshot=snapshot)
    emit(actor, 'APPOINTMENT_IMPROVEMENT', event, summary={'clinic':clinic, 'action':action, 'version':row.lock_version})
    return row, False

def available_actions(actor, row):
    if row is None: return []
    from operations.cancellation_policy import ACTION_NAMES
    role = actor._adc_workspace.role
    actions = []
    if row.assigned_to_id == actor.pk:
        actions += {'OPEN':['START'], 'WORKING':['SUBMIT']}.get(row.state, [])
    if role == 'MANAGER':
        if row.state in ('OPEN', 'WORKING', 'READY'): actions += ['ASSIGN', 'CANCEL']
        if row.state == 'READY' and actor.pk not in (row.assigned_to_id, row.submitted_by_id):
            actions += ['REVIEW', 'RETURN']
    return [(k, dict(ACTION_NAMES)[k]) for k in actions]
