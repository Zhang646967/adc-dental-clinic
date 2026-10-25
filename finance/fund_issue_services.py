"""Follow-up is an accountable history, never a write-off or patient charge."""
from django.db import transaction
from django.utils import timezone
from accounts.models import RoleAssignment
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal, workspace_binding
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from care.audit import emit
from finance.evidence_policies import lock_people
from finance.fund_services import _write_scope
from finance.cash_services import _reason
from finance.policies import money
from finance.allocation_models import FundIssue, FundIssueEvent
from insurance.fund_contract import claims

REQUEST = 'adc.fund.issue.v1'
FOLLOWUP = 'adc.fund.followup.v1'


def _owner(owner, *, lock=False):
    q = RoleAssignment.objects.filter(user_id=owner, user__is_active=True, role='FINANCE', scope_kind='CHAIN', is_active=True)
    if lock:
        q = q.select_for_update(of=('self',))
    if not list(q):
        raise RuleError('请选择仍有财务授权的跟进责任人。')


def _details(owner, due_at, basis, *, lock=False):
    _owner(owner, lock=lock)
    if due_at is None or timezone.is_naive(due_at) or due_at <= timezone.now():
        raise RuleError('请设置明确的未来联系期限。')
    return dict(owner=owner, due_at=due_at.isoformat(), basis=_reason(basis))


def prepare_issue(*, actor, claim_id, kind, amount, owner_id, due_at, basis):
    workspace_binding(actor, ('FINANCE',))
    with reporting_snapshot():
        claims(actor, [claim_id])
        if kind not in dict(FundIssue._meta.get_field('kind').choices):
            raise RuleError('请选择待核对事项类型。')
        d = dict(claim=claim_id, kind=kind, amount=None if amount in (None, '') else str(money(amount)),
            **_details(owner_id, due_at, basis))
        return dict(data=d, proposal_token=proposal(actor, REQUEST, ('FINANCE',), d))


@business_errors
@transaction.atomic
def confirm_issue(*, actor, proposal_token, confirmed, expected_claim_id=None):
    if confirmed is not True:
        raise RuleError('请明确确认新增基金跟进事项。')
    p = read_proposal(actor, REQUEST, ('FINANCE',), proposal_token); d = p['data']
    if expected_claim_id is not None and d['claim'] != expected_claim_id:
        raise RuleError('跟进事项与当前申报不同。')
    lock_people(actor.pk, d['owner']); _write_scope(actor)
    prior = FundIssue.objects.filter(operation_id=p['operation'], opened_by=actor).first()
    if prior:
        return prior, True
    from datetime import datetime
    due = datetime.fromisoformat(d['due_at'])
    _details(d['owner'], due, d['basis'], lock=True)
    claims(actor, [d['claim']], lock=True)
    row = FundIssue.objects.create(claim_id=d['claim'], operation_id=p['operation'],
        kind=d['kind'], amount=d['amount'], opened_by=actor)
    FundIssueEvent.objects.create(issue=row, sequence=1, operation_id=p['operation'], state='OPEN',
        owner_id=d['owner'], due_at=due, actor=actor, basis=d['basis'])
    emit(actor, 'FUND_ISSUE_OPENED', row, summary=dict(kind=row.kind))
    return row, False


def prepare_followup(*, actor, issue_id, state, owner_id, due_at, basis):
    workspace_binding(actor, ('FINANCE',))
    with reporting_snapshot():
        row = FundIssue.objects.get(pk=issue_id)
        last = row.events.latest('sequence')
        if last.state == 'CLOSED' or state not in ('OPEN', 'CLOSED'):
            raise RuleError('已结束的事项保留原结论；需要再次跟进时请新建事项。')
        if state == 'CLOSED':
            _owner(owner_id)
            values = dict(owner=owner_id, due_at=last.due_at.isoformat(), basis=_reason(basis))
        else:
            values = _details(owner_id, due_at, basis)
        d = dict(issue=row.pk, sequence=last.sequence, state=state, **values)
        return dict(row=row, data=d, proposal_token=proposal(actor, FOLLOWUP, ('FINANCE',), d))


@business_errors
@transaction.atomic
def confirm_followup(*, actor, proposal_token, confirmed, expected_issue_id=None):
    if confirmed is not True:
        raise RuleError('请明确确认本次跟进；结束事项不会核销资金或转嫁患者。')
    p = read_proposal(actor, FOLLOWUP, ('FINANCE',), proposal_token); d = p['data']
    if expected_issue_id is not None and d['issue'] != expected_issue_id:
        raise RuleError('跟进目标与当前事项不同。')
    lock_people(actor.pk, d['owner']); _write_scope(actor)
    prior = FundIssueEvent.objects.filter(operation_id=p['operation'], actor=actor).first()
    if prior:
        return prior.issue, True
    _owner(d['owner'], lock=True)
    row = FundIssue.objects.select_for_update().get(pk=d['issue'])
    last = row.events.latest('sequence')
    if last.sequence != d['sequence'] or last.state != 'OPEN':
        raise RuleError('已有新的跟进记录，请重新核对责任与期限。')
    from datetime import datetime
    due = datetime.fromisoformat(d['due_at'])
    if d['state'] == 'OPEN':
        _details(d['owner'], due, d['basis'])
    FundIssueEvent.objects.create(issue=row, sequence=last.sequence + 1, operation_id=p['operation'],
        state=d['state'], owner_id=d['owner'], due_at=due, actor=actor, basis=d['basis'])
    emit(actor, 'FUND_ISSUE_FOLLOWED', row, summary=dict(state=d['state']))
    return row, False
