"""Retained local simulation; each action reuses one original request identifier."""
from decimal import Decimal
from django.core.exceptions import PermissionDenied
from django.db import transaction
from accounts.models import RoleAssignment
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from care.audit import emit
from care.insurance_facts import lock_insurance_invoice
from insurance.policies import scope, preparer_active
from insurance.services import _people, _text
from insurance.settlement_source import quote_source, authorized_invoice
from insurance.settlement_rules import checked_split
from insurance.settlement_projection import invoice_insurance_facts
from insurance.settlement_models import (SettlementRequest, SettlementLine, SimulationOutcome,
    SettlementReview, SettlementEvent, ACTIVE_SETTLEMENT_STATES, SIMULATION_MODES)

REQUEST = 'adc.insurance.settlement.request.v1'
QUERY = 'adc.insurance.settlement.query.v1'
REVIEW = 'adc.insurance.settlement.review.v1'
ROLES = ('FRONT_DESK', 'FINANCE')


def settlements(actor):
    b = scope(actor, ROLES)
    qs = SettlementRequest.objects.all()
    return qs.filter(invoice__visit__clinic_id=b['clinic']) if b['role'] == 'FRONT_DESK' else qs


def _splits(source, allocations):
    rows = source['snapshot']['lines']
    if not isinstance(allocations, list) or len(rows) != len(allocations):
        raise RuleError('请逐行核对原账单的全部收费分担，不能增减原实际费用。')
    by_id = {}
    for allocation in allocations:
        if not isinstance(allocation, dict) or set(allocation) != {'treatment_record', 'patient_cash', 'personal_account', 'fund_amount'}:
            raise RuleError('逐行模拟结果格式无效。')
        pk = allocation['treatment_record']
        if type(pk) is not int or pk in by_id:
            raise RuleError('收费行重复或无效，请重新核对原账单。')
        by_id[pk] = allocation
    if set(by_id) != {r['treatment_record'] for r in rows}:
        raise RuleError('模拟分担不属于当前账单的确切收费行。')
    result = []
    for r in rows:
        a = by_id[r['treatment_record']]
        values = checked_split(r['amount'], **{k: a[k] for k in ('patient_cash', 'personal_account', 'fund_amount')},
            fund_limit=r['fund_limit'], mapping_usable=r['mapping_usable'])
        result.append(dict(treatment_record=r['treatment_record'],
            **{k: str(values[k]) for k in ('patient_cash', 'personal_account', 'fund_amount')}))
    return result


def _no_active(invoice_id):
    if SettlementRequest.objects.filter(invoice_id=invoice_id, state__in=ACTIVE_SETTLEMENT_STATES).exists():
        raise RuleError('本账单已有原医保请求，请查询或处理原编号，不能重复发起。')


def prepare_settlement(*, actor, invoice_id, allocations, simulation_mode, reason):
    scope(actor, ('FRONT_DESK',))
    with reporting_snapshot():
        source = quote_source(actor, invoice_id)
        _no_active(invoice_id)
        if simulation_mode not in dict(SIMULATION_MODES):
            raise RuleError('请选择明确的本地模拟结果。')
        d = dict(invoice=invoice_id, source_digest=source['digest'], allocations=_splits(source, allocations),
            settlement_cursor=invoice_insurance_facts(invoice_id)['cursor'],
            simulation_mode=simulation_mode, reason=_text(reason, '模拟分担依据'))
        return dict(source=source['snapshot'], data=d, proposal_token=proposal(actor, REQUEST, ('FRONT_DESK',), d))


def _record(actor, row, operation, action, reason, *, cancellation=None):
    snapshot = dict(state=row.state, revision=row.lock_version, request_id=str(row.request_id), source_digest=row.source_digest)
    if cancellation is not None:
        snapshot.update(cancellation_id=str(cancellation.cancellation_id), cancellation_state=cancellation.state,
            cancellation_revision=cancellation.revision)
    SettlementEvent.objects.create(request=row, sequence=row.events.count() + 1, operation_id=operation,
        actor=actor, action=action, reason=reason, snapshot=snapshot)
    emit(actor, 'INSURANCE_SETTLEMENT_CHANGED', row,
        summary=dict(action=action, state=row.state))


def _replay(actor, operation):
    event = SettlementEvent.objects.filter(actor=actor, operation_id=operation).first()
    return settlements(actor).get(pk=event.request_id) if event else None


def _advance(row, state):
    row.state = state; row.lock_version += 1
    row.save(update_fields=['state', 'lock_version'])


@business_errors
@transaction.atomic
def confirm_settlement(*, actor, proposal_token, confirmed, expected_invoice_id=None):
    if confirmed is not True:
        raise RuleError('请明确确认本地模拟分担，不能据此宣称真实医保到账。')
    p = read_proposal(actor, REQUEST, ('FRONT_DESK',), proposal_token); d = p['data']
    if expected_invoice_id is not None and d['invoice'] != expected_invoice_id:
        raise RuleError('确认内容与当前账单不同，请回到原账单。')
    _people(actor.pk); scope(actor, ('FRONT_DESK',), lock=True)
    prior = _replay(actor, p['operation'])
    if prior:
        return prior, True
    source = quote_source(actor, d['invoice'], lock=True)
    _no_active(d['invoice'])
    if invoice_insurance_facts(d['invoice'])['cursor'] != d['settlement_cursor']:
        raise RuleError('本账单已有新的医保办理历史，请查看原结果后重新预览。')
    if source['digest'] != d['source_digest']:
        raise RuleError('账单、待遇、目录适配或收退款进度已变化，请重新预览。')
    allocations = _splits(source, d['allocations'])
    totals = {k: sum(Decimal(a[k]) for a in allocations) for k in ('patient_cash', 'personal_account', 'fund_amount')}
    row = SettlementRequest.objects.create(operation_id=p['operation'], invoice=source['invoice'],
        record_version_id=source['snapshot']['record_version'], arrangement=source['arrangement'],
        eligibility=source['eligibility'], service_on=source['snapshot']['service_on'],
        gross_amount=source['snapshot']['total'], **totals, source_snapshot=source['snapshot'],
        source_digest=source['digest'], simulation_mode=d['simulation_mode'], state='PROCESSING',
        created_by=actor, reason=d['reason'])
    for s, a in zip(source['snapshot']['lines'], allocations):
        SettlementLine.objects.create(request=row, treatment_record_id=s['treatment_record'], line_no=s['line_no'],
            mapping_id=s['mapping'], source_snapshot=s, policy_quantity=s['policy_quantity'],
            fund_limit=s['fund_limit'], gross_amount=s['amount'], exception=s['exception'],
            **{k: a[k] for k in ('patient_cash', 'personal_account', 'fund_amount')})
    # The local adapter's retained truth survives a simulated lost reply. Query
    # reads this same row; it never allocates a replacement request UUID.
    result = 'DECLINED' if d['simulation_mode'] == 'DECLINE' else 'ACCEPTED'
    SimulationOutcome.objects.create(request=row, reference='SIM-SETTLE-' + row.request_id.hex,
        request_digest=row.source_digest, result=result, payload=dict(source='LOCAL_SIMULATION',
            request_id=str(row.request_id), gross_amount=str(row.gross_amount),
            **{k: str(v) for k, v in totals.items()}, lines=allocations))
    target = {'ACCEPT': 'AWAITING_REVIEW', 'LOST_SUCCESS': 'UNKNOWN', 'DECLINE': 'DECLINED', 'PROCESSING': 'PROCESSING'}[d['simulation_mode']]
    # A newly created request has one retained event, including its first reply.
    if target != 'PROCESSING':
        _advance(row, target)
    _record(actor, row, p['operation'], 'SUBMIT', d['reason'])
    return row, False


def prepare_query(*, actor, request_id):
    row = settlements(actor).get(pk=request_id)
    if row.state not in ('PROCESSING', 'UNKNOWN'):
        raise RuleError('原请求已有明确结果，请查看保留结果和复核进度。')
    d = dict(request=row.pk, revision=row.lock_version)
    return dict(row=row, proposal_token=proposal(actor, QUERY, ROLES, d))


def _lock_request(actor, pk):
    initial = settlements(actor).get(pk=pk)
    lock_insurance_invoice(authorized_invoice(actor, initial.invoice_id))
    return SettlementRequest.objects.select_for_update().get(pk=pk)


@business_errors
@transaction.atomic
def confirm_query(*, actor, proposal_token, confirmed, expected_request_id=None):
    if confirmed is not True:
        raise RuleError('请确认查询原请求编号。')
    p = read_proposal(actor, QUERY, ROLES, proposal_token); d = p['data']
    if expected_request_id is not None and d['request'] != expected_request_id:
        raise RuleError('查询目标与当前请求不同。')
    _people(actor.pk); scope(actor, ROLES, lock=True)
    prior = _replay(actor, p['operation'])
    if prior:
        return prior, True
    row = _lock_request(actor, d['request'])
    if row.state not in ('PROCESSING', 'UNKNOWN') or row.lock_version != d['revision']:
        raise RuleError('原请求已有新的查询进度，请打开当前结果。')
    result = row.simulation_outcome
    _advance(row, 'AWAITING_REVIEW' if result.result == 'ACCEPTED' else 'DECLINED')
    _record(actor, row, p['operation'], 'QUERY', '按原唯一请求编号取回本地模拟结果')
    return row, False


def _review_source(actor, row, *, lock=False):
    clinic_id = row.arrangement.clinic_id
    if lock:
        list(RoleAssignment.objects.select_for_update().filter(user_id=row.created_by_id,
            role='FRONT_DESK', scope_kind='CLINIC', clinic_id=clinic_id).order_by('pk'))
    if not preparer_active(row.created_by_id, 'FRONT_DESK', clinic_id):
        raise RuleError('原办理人的前台授权已失效；请记录未通过并处置原请求。')
    source = quote_source(actor, row.invoice_id, lock=lock)
    if source['digest'] != row.source_digest:
        raise RuleError('原请求的账单或待遇依据已变化；请记录未通过并处置原请求，不能批准旧分担。')
    return source


def prepare_settlement_review(*, actor, request_id, decision, reason):
    scope(actor, ('FINANCE',))
    with reporting_snapshot():
        row = settlements(actor).get(pk=request_id)
        if row.created_by_id == actor.pk:
            raise PermissionDenied('模拟结算须由另一账号独立复核，切换岗位不能自行确认。')
        if row.state != 'AWAITING_REVIEW' or decision not in ('APPROVE', 'REJECT'):
            raise RuleError('请先查询原请求取得明确结果，再选择独立复核决定。')
        if decision == 'APPROVE':
            _review_source(actor, row)
        d = dict(request=row.pk, revision=row.lock_version, decision=decision, reason=_text(reason, '独立核对依据'))
        return dict(row=row, data=d, proposal_token=proposal(actor, REVIEW, ('FINANCE',), d))


@business_errors
@transaction.atomic
def confirm_settlement_review(*, actor, proposal_token, confirmed, expected_request_id=None):
    if confirmed is not True:
        raise RuleError('请明确确认独立核对结果。')
    p = read_proposal(actor, REVIEW, ('FINANCE',), proposal_token); d = p['data']
    if expected_request_id is not None and d['request'] != expected_request_id:
        raise RuleError('复核目标与当前请求不同。')
    initial = settlements(actor).get(pk=d['request'])
    _people(actor.pk, initial.created_by_id); scope(actor, ('FINANCE',), lock=True)
    prior = _replay(actor, p['operation'])
    if prior:
        return prior, True
    # Preparer grant precedes clinical/source locks, as in cash review.
    if d['decision'] == 'APPROVE':
        _review_source(actor, initial, lock=True)
    row = _lock_request(actor, d['request'])
    if row.created_by_id == actor.pk:
        raise PermissionDenied('不能自行复核模拟结算。')
    if row.state != 'AWAITING_REVIEW' or row.lock_version != d['revision']:
        raise RuleError('原请求已有其他办理结果，请打开当前进度。')
    SettlementReview.objects.create(request=row, operation_id=p['operation'], reviewed_by=actor,
        decision=d['decision'], reason=d['reason'], source_digest=row.source_digest)
    _advance(row, 'CONFIRMED' if d['decision'] == 'APPROVE' else 'REVIEW_REJECTED')
    _record(actor, row, p['operation'], 'REVIEW', d['reason'])
    return row, False
