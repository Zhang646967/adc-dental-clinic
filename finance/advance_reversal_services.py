"""One retained reversal per posted allocation line, with independent review."""
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from accounts.finance_access import lock_finance_write
from accounts.policies import lock_clinic_grant
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal, workspace_binding
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from care.audit import emit
from finance import advance_services as advance
from finance.advance_models import AdvanceAllocationLine, AdvanceAllocationReversal
from finance.cash_selectors import invoice_balance, invoice_cash_facts, with_advance_credit
from finance.cash_services import _reason
from finance.evidence_policies import lock_people

REQUEST = 'adc.advance.reverse-line.v1'
REVIEW = 'adc.advance.reverse-line.review.v1'


def lines(actor):
    return AdvanceAllocationLine.objects.filter(allocation__in=advance.allocations(actor)).select_related(
        'allocation__receipt__clinic', 'allocation__receipt__advance_patient', 'record_version', 'invoice')


def reversals(actor):
    return AdvanceAllocationReversal.objects.filter(line__in=lines(actor)).select_related(
        'line__allocation__receipt__clinic', 'line__allocation__receipt__advance_patient', 'line__invoice')


def _facts(actor, line, *, lock=False, own_request=None):
    original = line.allocation.receipt
    if line.allocation.state != 'POSTED' or not original.clinic.is_active:
        raise RuleError('请选择仍可办理的已抵扣明细。')
    bill, = advance._bills(original, [line.invoice_id], lock=lock)
    receipt = advance._receipt(actor, original.pk, lock=True) if lock else original
    if line.reversals.exclude(pk=own_request).filter(state__in=['PENDING', 'POSTED']).exists():
        raise RuleError('该明细已有待审或已记账的撤销，请查看原办理结果。')
    available = advance.available_amount(receipt)
    current = invoice_balance(bill)
    after = with_advance_credit(current, current['advance_applied'] - line.amount)
    return dict(amount=str(line.amount), available=str(available), after=str(available + line.amount),
                invoice=bill.invoice_no, original_revision=line.record_version.revision_no,
                current_revision=current['current_revision'], version=bill.current_record_version_id,
                current_due=str(current['remaining']), resulting_due=str(after['remaining']),
                resulting_excess=str(after['advance_excess']), cursor=invoice_cash_facts(bill.pk)['cursor'])


def prepare_reversal(*, actor, line_id, basis):
    with reporting_snapshot():
        workspace_binding(actor, advance.FRONT)
        line = lines(actor).get(pk=line_id)
        data = dict(line=line.pk, facts=_facts(actor, line), basis=_reason(basis))
        return dict(row=line, **data, proposal_token=proposal(actor, REQUEST, advance.FRONT, data))


@business_errors
@transaction.atomic
def confirm_reversal(*, actor, line_id, proposal_token, confirmed):
    if confirmed is not True:
        raise RuleError('请明确确认撤销申请。')
    payload = read_proposal(actor, REQUEST, advance.FRONT, proposal_token)
    data = payload['data']
    if data['line'] != line_id:
        raise RuleError('请核对本次撤销对应的抵扣明细。')
    line = lines(actor).get(pk=line_id)
    lock_clinic_grant(actor, line.allocation.receipt.clinic_id)
    prior = line.reversals.filter(operation_id=payload['operation'], prepared_by=actor).first()
    if prior:
        return prior, True
    if _facts(actor, line, lock=True) != data['facts']:
        raise RuleError('账单或预收可用额已变化，请重新预览。')
    row = line.reversals.create(operation_id=payload['operation'], basis=data['basis'], prepared_by=actor)
    emit(actor, 'ADVANCE_REVERSAL_REQUESTED', row, summary={'line_id': line.pk})
    return row, False


def _decision(actor, row, decision, *, lock=False):
    advance._reviewable(actor, row, decision)
    if decision == 'reject':
        return None
    advance.require_advance_preparer(row.prepared_by_id, row.line.allocation.receipt.clinic_id, lock=lock)
    return _facts(actor, row.line, lock=lock, own_request=row.pk)


def prepare_review(*, actor, reversal_id, decision, reason):
    with reporting_snapshot():
        workspace_binding(actor, advance.FINANCE)
        row = reversals(actor).get(pk=reversal_id)
        data = dict(reversal=row.pk, decision=decision, reason=_reason(reason), facts=_decision(actor, row, decision))
        return dict(row=row, **data, proposal_token=proposal(actor, REVIEW, advance.FINANCE, data))


@business_errors
@transaction.atomic
def confirm_review(*, actor, reversal_id, proposal_token, confirmed):
    if confirmed is not True:
        raise RuleError('请明确确认撤销复核。')
    payload = read_proposal(actor, REVIEW, advance.FINANCE, proposal_token)
    data = payload['data']
    if data['reversal'] != reversal_id:
        raise RuleError('请核对本次复核对应的撤销申请。')
    initial = reversals(actor).get(pk=reversal_id)
    lock_people(actor.pk, initial.prepared_by_id)
    lock_finance_write(actor)
    row = reversals(actor).select_for_update(of=('self',)).get(pk=initial.pk)
    operation = UUID(payload['operation'])
    if row.review_operation_id == operation:
        return row, True
    if _decision(actor, row, data['decision'], lock=True) != data['facts']:
        raise RuleError('账单或预收可用额已变化，请重新预览复核。')
    row.state = 'POSTED' if data['decision'] == 'approve' else 'REJECTED'
    row.reviewed_by = actor
    row.reviewed_at = timezone.now()
    row.review_reason = data['reason']
    row.review_operation_id = operation
    row.save(update_fields=['state', 'reviewed_by', 'reviewed_at', 'review_reason', 'review_operation_id'])
    emit(actor, 'ADVANCE_REVERSAL_' + row.state, row, summary={'line_id': row.line_id})
    return row, False
