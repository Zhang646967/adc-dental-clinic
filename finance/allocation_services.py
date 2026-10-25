"""Bank allocations reserve capacity, then require a different finance reviewer."""
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from accounts.models import RoleAssignment
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal, workspace_binding
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from care.audit import emit
from finance.policies import money
from finance.cash_services import _reason
from finance.evidence_policies import lock_people
from finance.fund_services import _write_scope
from finance.fund_models import FundTransfer
from finance.reconciliation_models import StatementLine
from finance.allocation_models import FundAllocation, FundAllocationLine
from finance.allocation_projection import claim_funds, transfer_funds
from insurance.fund_contract import claims, allocation_source
from insurance.settlement_source import digest

REQUEST = 'adc.fund.allocation.v1'
REVIEW = 'adc.fund.allocation.review.v1'


def _items(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 100:
        raise RuleError('每批请选择 1—100 笔申报，逐笔填写本次分配金额。')
    result = {}
    for item in values:
        if not isinstance(item, dict) or set(item) != {'claim', 'amount'} or type(item['claim']) is not int or item['claim'] in result:
            raise RuleError('申报编号无效或重复，请重新核对。')
        amount = money(item['amount'])
        if amount <= 0:
            raise RuleError('每笔分配金额须大于零。')
        result[item['claim']] = amount
    return result


def _transfer(pk, *, lock=False):
    initial = FundTransfer.objects.select_related('line__account').get(pk=pk)
    if lock:
        StatementLine.objects.select_for_update().get(pk=initial.line_id)
        initial = FundTransfer.objects.select_for_update(of=('self',)).select_related('line__account').get(pk=pk)
    if initial.state != 'CONFIRMED':
        raise RuleError('请先由另一财务账号核对原银行证据。')
    return initial


def _source(transfer, rows, amounts, *, exclude=None):
    tf = transfer_funds(transfer, exclude=exclude)
    total = sum(amounts.values())
    if total > tf['available']:
        raise RuleError('本次分配超过该银行凭据尚未分配或预留的金额。')
    sources = []
    for pk, amount in sorted(amounts.items()):
        row = rows[pk]
        source = allocation_source(row, kind=transfer.kind, clinic_id=transfer.line.account.clinic_id,
            currency=transfer.line.currency)
        cf = claim_funds(pk, exclude=exclude)
        available = (row.fund_amount - cf['net_received'] - cf['reserved_in'] if transfer.kind == 'RECEIPT'
            else cf['net_received'] - cf['reserved_out'])
        if amount > available:
            raise RuleError('分配超过该申报尚未核销的基金应收，或超过原已收到且尚未退回的金额。')
        sources.append(dict(**source, amount=str(amount), fund_cursor=cf['cursor']))
    return dict(transfer=transfer.pk, kind=transfer.kind, bank_date=transfer.line.booked_on.isoformat(),
        currency=transfer.line.currency, transfer_cursor=tf['cursor'], lines=sources)


def prepare_allocation(*, actor, transfer_id, allocations, basis):
    workspace_binding(actor, ('FINANCE',))
    amounts = _items(allocations)
    with reporting_snapshot():
        rows = claims(actor, amounts)
        transfer = _transfer(transfer_id)
        source = _source(transfer, rows, amounts)
        d = dict(transfer=transfer.pk, allocations=[dict(claim=k, amount=str(v)) for k, v in sorted(amounts.items())],
            digest=digest(source), basis=_reason(basis))
        return dict(transfer=transfer, source=source, data=d, proposal_token=proposal(actor, REQUEST, ('FINANCE',), d))


@business_errors
@transaction.atomic
def confirm_allocation(*, actor, proposal_token, confirmed, expected_transfer_id=None):
    if confirmed is not True:
        raise RuleError('请明确确认本次逐笔分配，提交后仍待独立复核。')
    p = read_proposal(actor, REQUEST, ('FINANCE',), proposal_token); d = p['data']
    if expected_transfer_id is not None and d['transfer'] != expected_transfer_id:
        raise RuleError('本次分配与当前银行凭据不同。')
    lock_people(actor.pk); _write_scope(actor)
    prior = FundAllocation.objects.filter(operation_id=p['operation'], prepared_by=actor).first()
    if prior:
        return prior, True
    amounts = _items(d['allocations'])
    rows = claims(actor, amounts, lock=True)
    transfer = _transfer(d['transfer'], lock=True)
    source = _source(transfer, rows, amounts)
    if digest(source) != d['digest']:
        raise RuleError('银行凭据或申报分配进度已变化，请查看原进度后重新预览。')
    row = FundAllocation.objects.create(transfer=transfer, operation_id=p['operation'], prepared_by=actor,
        total=sum(amounts.values()), source_snapshot=source, source_digest=d['digest'], basis=d['basis'])
    for pk, amount in sorted(amounts.items()):
        FundAllocationLine.objects.create(allocation=row, claim_id=pk, amount=amount)
    emit(actor, 'FUND_ALLOCATION_REQUESTED', row, summary=dict(transfer_id=transfer.pk, count=len(amounts)))
    return row, False


def _preparer(row, *, lock=False):
    q = RoleAssignment.objects.filter(user_id=row.prepared_by_id, role='FINANCE', scope_kind='CHAIN',
        is_active=True, user__is_active=True)
    if lock:
        q = q.select_for_update(of=('self',)).order_by('pk')
    if not list(q):
        raise RuleError('原分配人的财务授权已失效，请退回原分配并保留历史。')


def _reviewable(actor, row, decision):
    if row.prepared_by_id == actor.pk:
        raise PermissionDenied('分配必须由另一财务账号独立复核。')
    if row.state != 'PENDING' or decision not in ('approve', 'reject'):
        raise RuleError('请选择待核对分配的明确决定。')


def prepare_allocation_review(*, actor, allocation_id, decision, reason):
    workspace_binding(actor, ('FINANCE',))
    with reporting_snapshot():
        row = FundAllocation.objects.get(pk=allocation_id)
        _reviewable(actor, row, decision)
        amounts = dict(row.lines.values_list('claim_id', 'amount'))
        source = None
        if decision == 'approve':
            _preparer(row)
            source = _source(_transfer(row.transfer_id), claims(actor, amounts), amounts, exclude=row.pk)
        d = dict(allocation=row.pk, decision=decision, reason=_reason(reason), digest=digest(source))
        return dict(row=row, data=d, source=source, proposal_token=proposal(actor, REVIEW, ('FINANCE',), d))


@business_errors
@transaction.atomic
def confirm_allocation_review(*, actor, proposal_token, confirmed, expected_allocation_id=None):
    if confirmed is not True:
        raise RuleError('请明确确认本次分配的独立核对结果。')
    p = read_proposal(actor, REVIEW, ('FINANCE',), proposal_token); d = p['data']
    if expected_allocation_id is not None and d['allocation'] != expected_allocation_id:
        raise RuleError('核对目标与当前分配不同。')
    initial = FundAllocation.objects.get(pk=d['allocation'])
    lock_people(actor.pk, initial.prepared_by_id); _write_scope(actor)
    if initial.state == 'PENDING' and d['decision'] == 'approve':
        _preparer(initial, lock=True)
    amounts = dict(initial.lines.values_list('claim_id', 'amount'))
    rows = claims(actor, amounts, lock=True)
    transfer = _transfer(initial.transfer_id, lock=True)
    row = FundAllocation.objects.select_for_update().get(pk=initial.pk)
    target = 'CONFIRMED' if d['decision'] == 'approve' else 'REJECTED'
    if row.state != 'PENDING':
        if row.state == target and row.reviewed_by_id == actor.pk and row.review_reason == d['reason']:
            return row, True
        raise RuleError('该分配已有其他核对结果，请查看保留记录。')
    _reviewable(actor, row, d['decision'])
    if d['decision'] == 'approve':
        source = _source(transfer, rows, amounts, exclude=row.pk)
        if digest(source) != d['digest']:
            raise RuleError('申报或银行分配进度已变化，请重新核对本次复核。')
    row.state = target; row.reviewed_by = actor; row.reviewed_at = timezone.now(); row.review_reason = d['reason']
    row.save(update_fields=['state', 'reviewed_by', 'reviewed_at', 'review_reason'])
    emit(actor, 'FUND_ALLOCATION_REVIEWED', row, summary=dict(state=target))
    return row, False
