"""Original-result reversal, independent clearance and retained unknown states."""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from insurance.policies import scope
from insurance.services import _people, _text
from insurance.settlement_source import digest
from insurance.settlement_services import settlements, _lock_request, _advance, _record, _replay, ROLES
from insurance.cancellation_models import CancellationRequest, ReversalOutcome, CancellationReview, CANCEL_MODES
from finance.allocation_projection import require_no_pending, require_returned, claim_funds
from finance.cash_selectors import invoice_cash_facts

REQUEST = 'adc.insurance.cancellation.v1'
QUERY = 'adc.insurance.cancellation.query.v1'
REVIEW = 'adc.insurance.cancellation.review.v1'


def _cash(row):
    facts = invoice_cash_facts(row.invoice_id)
    if facts['pending']:
        raise RuleError('本账单仍有收退款待审，请先核对或退回原申请，再办理结算撤销。')
    return facts


def _original(row):
    if row.state not in ('AWAITING_REVIEW', 'CONFIRMED', 'REVIEW_REJECTED'):
        raise RuleError('请先查询原唯一结算请求，取得明确受理结果；已在撤销中的请求继续按原编号办理。')
    outcome = row.simulation_outcome
    if outcome.result != 'ACCEPTED':
        raise RuleError('原模拟结果未受理，无需发起撤销。')
    require_no_pending(row.pk)
    cash = _cash(row)
    return dict(request=row.pk, request_id=str(row.request_id), revision=row.lock_version,
        source_digest=row.source_digest, original_reference=outcome.reference, original_result=outcome.result,
        personal_account=str(row.personal_account), fund_amount=str(row.fund_amount),
        fund_cursor=claim_funds(row.pk)['cursor'], cash_cursor=cash['cursor'])


def prepare_cancellation(*, actor, request_id, simulation_mode, reason):
    with reporting_snapshot():
        row = settlements(actor).get(pk=request_id)
        source = _original(row)
        if simulation_mode not in dict(CANCEL_MODES):
            raise RuleError('请选择明确的本地撤销模拟方式。')
        d = dict(request=row.pk, source_digest=digest(source), simulation_mode=simulation_mode, reason=_text(reason, '撤销依据'))
        return dict(row=row, source=source, data=d, proposal_token=proposal(actor, REQUEST, ROLES, d))


def _change(cancel, state):
    cancel.state = state; cancel.revision += 1
    cancel.save(update_fields=['state', 'revision'])


@business_errors
@transaction.atomic
def confirm_cancellation(*, actor, proposal_token, confirmed, expected_request_id=None):
    if confirmed is not True:
        raise RuleError('请明确确认撤销原结算，提交不代表撤销或患者退款已完成。')
    p = read_proposal(actor, REQUEST, ROLES, proposal_token); d = p['data']
    if expected_request_id is not None and d['request'] != expected_request_id:
        raise RuleError('撤销目标与当前原请求不同。')
    _people(actor.pk); scope(actor, ROLES, lock=True)
    prior = _replay(actor, p['operation'])
    if prior:
        return prior, True
    row = _lock_request(actor, d['request'])
    source = _original(row)
    if digest(source) != d['source_digest']:
        raise RuleError('原结算或资金进度已变化，请重新核对撤销依据。')
    cancel = CancellationRequest.objects.create(request=row, operation_id=p['operation'], simulation_mode=d['simulation_mode'],
        source_snapshot=source, source_digest=d['source_digest'], prepared_by=actor, reason=d['reason'])
    ReversalOutcome.objects.create(cancellation=cancel, reference='SIM-REVERSE-' + cancel.cancellation_id.hex,
        payload=dict(source='LOCAL_SIMULATION', cancellation_id=str(cancel.cancellation_id), request_id=str(row.request_id),
            original_reference=row.simulation_outcome.reference, personal_account=str(row.personal_account), fund_amount=str(row.fund_amount)))
    target = {'ACCEPT': 'AWAITING_REVIEW', 'LOST_SUCCESS': 'UNKNOWN', 'PROCESSING': 'PROCESSING'}[d['simulation_mode']]
    if target != 'PROCESSING':
        _change(cancel, target)
    _advance(row, 'CANCEL_PENDING')
    _record(actor, row, p['operation'], 'CANCEL_START', d['reason'], cancellation=cancel)
    return row, False


def prepare_cancellation_query(*, actor, request_id):
    row = settlements(actor).get(pk=request_id)
    if not hasattr(row, 'cancellation') or row.cancellation.state not in ('PROCESSING', 'UNKNOWN'):
        raise RuleError('原撤销已有明确结果，请查看独立核对进度。')
    d = dict(request=row.pk, revision=row.cancellation.revision)
    return dict(row=row, proposal_token=proposal(actor, QUERY, ROLES, d))


@business_errors
@transaction.atomic
def confirm_cancellation_query(*, actor, proposal_token, confirmed, expected_request_id=None):
    if confirmed is not True:
        raise RuleError('请明确确认查询原撤销编号。')
    p = read_proposal(actor, QUERY, ROLES, proposal_token); d = p['data']
    if expected_request_id is not None and d['request'] != expected_request_id:
        raise RuleError('查询目标与原请求不同。')
    _people(actor.pk); scope(actor, ROLES, lock=True)
    prior = _replay(actor, p['operation'])
    if prior:
        return prior, True
    row = _lock_request(actor, d['request'])
    cancel = CancellationRequest.objects.select_for_update().get(request=row)
    if cancel.state not in ('PROCESSING', 'UNKNOWN') or cancel.revision != d['revision']:
        raise RuleError('原撤销已有新的办理进度，请查看当前结果。')
    if cancel.outcome.result != 'REVERSED':
        raise RuleError('原撤销结果尚未明确，不能视为完成。')
    _change(cancel, 'AWAITING_REVIEW')
    _advance(row, 'CANCEL_PENDING')
    _record(actor, row, p['operation'], 'CANCEL_QUERY', '按原撤销编号取得保留的模拟结果', cancellation=cancel)
    return row, False


def _clearance(row, cancel):
    if cancel.outcome.result != 'REVERSED':
        raise RuleError('请先查询原撤销取得明确结果。')
    fund = require_returned(row.pk)
    cash = _cash(row)
    return dict(reversal_reference=cancel.outcome.reference, original_request=str(row.request_id),
        fund={k: str(v) if k != 'cursor' else v for k, v in fund.items()},
        cash_cursor=cash['cursor'])


def _reviewable(actor, row, cancel):
    if cancel.prepared_by_id == actor.pk:
        raise PermissionDenied('原撤销须由另一账号独立核对，切换岗位不能自行通过。')
    if row.state != 'CANCEL_PENDING' or cancel.state not in ('AWAITING_REVIEW', 'REVIEW_REJECTED'):
        raise RuleError('请先查询原撤销取得结果，再独立核对退回依据。')


def prepare_cancellation_review(*, actor, request_id, decision, reason):
    scope(actor, ('FINANCE',))
    with reporting_snapshot():
        row = settlements(actor).get(pk=request_id)
        if not hasattr(row, 'cancellation'):
            raise RuleError('原请求尚未办理撤销。')
        cancel = row.cancellation
        _reviewable(actor, row, cancel)
        if decision not in ('APPROVE', 'REJECT'):
            raise RuleError('请选择明确的撤销核对决定。')
        source = _clearance(row, cancel) if decision == 'APPROVE' else None
        d = dict(request=row.pk, revision=cancel.revision, decision=decision, reason=_text(reason, '撤销核对依据'),
            clearance_digest=digest(source))
        return dict(row=row, data=d, source=source, proposal_token=proposal(actor, REVIEW, ('FINANCE',), d))


@business_errors
@transaction.atomic
def confirm_cancellation_review(*, actor, proposal_token, confirmed, expected_request_id=None):
    if confirmed is not True:
        raise RuleError('请明确确认原撤销与基金退回；患者现金仍按原收退款流程办理。')
    p = read_proposal(actor, REVIEW, ('FINANCE',), proposal_token); d = p['data']
    if expected_request_id is not None and d['request'] != expected_request_id:
        raise RuleError('核对目标与原结算不同。')
    _people(actor.pk); scope(actor, ('FINANCE',), lock=True)
    prior = _replay(actor, p['operation'])
    if prior:
        return prior, True
    row = _lock_request(actor, d['request'])
    cancel = CancellationRequest.objects.select_for_update().get(request=row)
    _reviewable(actor, row, cancel)
    if cancel.revision != d['revision']:
        raise RuleError('已有新的撤销核对记录，请重新打开原进度。')
    source = _clearance(row, cancel) if d['decision'] == 'APPROVE' else None
    if digest(source) != d['clearance_digest']:
        raise RuleError('原退回或现金核对进度已变化，请重新预览。')
    CancellationReview.objects.create(cancellation=cancel, operation_id=p['operation'],
        sequence=cancel.reviews.count() + 1, decision=d['decision'], reviewed_by=actor,
        reason=d['reason'], clearance_snapshot=source or {})
    _change(cancel, 'CONFIRMED' if d['decision'] == 'APPROVE' else 'REVIEW_REJECTED')
    _advance(row, 'CANCELLED' if d['decision'] == 'APPROVE' else 'CANCEL_PENDING')
    _record(actor, row, p['operation'], 'CANCEL_REVIEW', d['reason'], cancellation=cancel)
    return row, False
