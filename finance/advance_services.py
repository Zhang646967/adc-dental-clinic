"""Front-desk allocation requests and independent, atomic finance decisions."""
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from accounts.finance_access import lock_finance_write
from accounts.models import RoleAssignment
from accounts.policies import lock_clinic_grant
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal, workspace_binding
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from care.audit import emit
from care.models import Invoice
from finance.advance_models import AdvanceAllocation, AdvanceAllocationLine
from finance.advance_projection import receipt_applied
from finance.cash_models import CashEntry
from finance.cash_selectors import cash_scope, invoice_balance
from finance.cash_services import _reason, _require_advance_patient
from finance.evidence_policies import lock_people, preparer_current
from finance.policies import money
from patients.models import Patient
from scheduling.coordination import lock_slots
from scheduling.models import Visit

REQUEST = 'adc.advance.allocation.v1'
REVIEW = 'adc.advance.allocation.review.v1'
FRONT = ('FRONT_DESK',)
FINANCE = ('FINANCE',)
MAX_LINES = 5


def advance_receipts(actor):
    workspace_binding(actor, FRONT + FINANCE)
    return cash_scope(actor, detail=True).filter(advance_patient__isnull=False)


def allocations(actor):
    return AdvanceAllocation.objects.filter(receipt__in=advance_receipts(actor))


def available_amount(receipt):
    return receipt.amount - receipt_applied(CashEntry.objects.filter(pk=receipt.pk)) if receipt.state == 'POSTED' else Decimal('0.00')


def receipt_invoices(receipt):
    return Invoice.objects.filter(visit__clinic_id=receipt.clinic_id, visit__patient_id=receipt.advance_patient_id)


def _amounts(items):
    if not 1 <= len(items) <= MAX_LINES:
        raise RuleError(f'请选择 1 至 {MAX_LINES} 张账单。')
    result = {}
    for invoice_id, value in items:
        if type(invoice_id) is not int or invoice_id <= 0 or invoice_id in result:
            raise RuleError('同一张账单只能填写一次，请核对账单选择。')
        amount = money(value)
        if amount <= 0:
            raise RuleError('每张账单的抵扣金额须大于零。')
        result[invoice_id] = amount
    return result


def _receipt(actor, receipt_id, *, lock=False):
    rows = advance_receipts(actor).select_related('clinic', 'advance_patient')
    if lock:
        rows = rows.select_for_update(of=('self',))
    return rows.get(pk=receipt_id)


def _bills(receipt, amounts, *, lock=False):
    query = receipt_invoices(receipt).filter(pk__in=amounts).select_related('visit', 'current_record_version').order_by('pk')
    bills = list(query)
    if len(bills) != len(amounts):
        raise RuleError('请选择本店同一患者的账单。')
    if lock:
        # Shared order with clinical correction and insurance. The receipt follows the invoices.
        lock_slots([bill.visit.availability_slot_id for bill in bills])
        Patient.objects.select_for_update().get(pk=receipt.advance_patient_id)
        list(Visit.objects.select_for_update().filter(pk__in=[bill.visit_id for bill in bills]).order_by('pk'))
        bills = list(query.select_for_update(of=('self',)))
    return bills


def _facts(receipt, bills, amounts):
    if receipt.state != 'POSTED':
        raise RuleError('请先完成原预收款的独立记账。')
    if not receipt.clinic.is_active:
        raise RuleError('门店已停用，请保留原申请并核对。')
    _require_advance_patient(receipt.advance_patient, receipt.clinic_id)
    available = available_amount(receipt)
    total = sum(amounts.values())
    if total > available:
        raise RuleError('本次抵扣超过原预收款的可用余额。')
    lines = []
    for bill in bills:
        record = bill.current_record_version
        if record.state != 'PUBLISHED':
            raise RuleError('请使用当前已发布的账单。')
        balance = invoice_balance(bill)
        if balance['insurance_pending']:
            raise RuleError('账单的医保办理尚未明确，请先核对原请求。')
        amount = amounts[bill.pk]
        if amount > balance['remaining']:
            raise RuleError('本次抵扣超过账单当前待付金额。')
        lines.append(dict(invoice=bill.pk, number=bill.invoice_no, version=record.pk, revision=record.revision_no,
                          responsibility=str(balance['patient_responsibility']), due=str(balance['remaining']),
                          amount=str(amount), after=str(balance['remaining']-amount)))
    return dict(available=str(available), total=str(total), after=str(available-total), lines=lines)


def prepare_allocation(*, actor, receipt_id, items, basis):
    amounts = _amounts(items)
    with reporting_snapshot():
        workspace_binding(actor, FRONT)
        receipt = _receipt(actor, receipt_id)
        facts = _facts(receipt, _bills(receipt, amounts), amounts)
        data = dict(receipt=receipt.pk, facts=facts, basis=_reason(basis))
        return dict(receipt=receipt, facts=facts, basis=data['basis'],
                    proposal_token=proposal(actor, REQUEST, FRONT, data))


@business_errors
@transaction.atomic
def confirm_allocation(*, actor, receipt_id, proposal_token, confirmed):
    if confirmed is not True:
        raise RuleError('请明确确认本次抵扣申请。')
    payload = read_proposal(actor, REQUEST, FRONT, proposal_token)
    data = payload['data']
    if data['receipt'] != receipt_id:
        raise RuleError('确认内容与当前预收款不同，请重新核对。')
    receipt = _receipt(actor, receipt_id)
    lock_clinic_grant(actor, receipt.clinic_id)
    prior = AdvanceAllocation.objects.filter(receipt=receipt, operation_id=payload['operation'], prepared_by=actor).first()
    if prior:
        return prior, True
    amounts = _amounts([(item['invoice'], item['amount']) for item in data['facts']['lines']])
    bills = _bills(receipt, amounts, lock=True)
    receipt = _receipt(actor, receipt_id, lock=True)
    facts = _facts(receipt, bills, amounts)
    if facts != data['facts']:
        raise RuleError('账单或预收余额已变化，请重新预览。')
    row = AdvanceAllocation.objects.create(receipt=receipt, operation_id=payload['operation'], prepared_by=actor,
        total=facts['total'], available_at_request=facts['available'], basis=data['basis'])
    AdvanceAllocationLine.objects.bulk_create([
        AdvanceAllocationLine(allocation=row, invoice_id=item['invoice'], record_version_id=item['version'],
                              amount=item['amount'], responsibility=item['responsibility'], due_at_request=item['due'])
        for item in facts['lines']
    ])
    emit(actor, 'ADVANCE_ALLOCATION_REQUESTED', row, summary={'receipt_id': receipt.pk, 'bill_count': len(bills)})
    return row, False


def _reviewable(actor, row, decision):
    if row.prepared_by_id == actor.pk:
        raise PermissionDenied('申请人与审核人必须为不同账号。')
    if row.state != 'PENDING' or decision not in ('approve', 'reject'):
        raise RuleError('请选择待复核分配的明确决定。')


def _require_preparer(row, *, lock=False):
    clinic_id = row.receipt.clinic_id
    if lock:
        list(RoleAssignment.objects.select_for_update().filter(
            user_id=row.prepared_by_id, role='FRONT_DESK', scope_kind='CLINIC', clinic_id=clinic_id).order_by('pk'))
    if not preparer_current(row.prepared_by_id, clinic_id, 'FRONT_DESK'):
        raise RuleError('原申请人的本店前台授权已失效，请拒绝该申请。')


def _approval_facts(actor, row, *, lock=False):
    _require_preparer(row, lock=lock)
    originals = list(row.lines.order_by('invoice_id'))
    amounts = {line.invoice_id: line.amount for line in originals}
    bills = _bills(row.receipt, amounts, lock=lock)
    if any(line.record_version_id != bill.current_record_version_id for line, bill in zip(originals, bills)):
        raise RuleError('账单已发布新版本，请拒绝旧申请并重新核对。')
    receipt = _receipt(actor, row.receipt_id, lock=True) if lock else row.receipt
    facts = _facts(receipt, bills, amounts)
    if any(line.responsibility != Decimal(item['responsibility']) for line, item in zip(originals, facts['lines'])):
        raise RuleError('患者责任已变化，请拒绝旧申请并重新核对。')
    return facts


def prepare_allocation_review(*, actor, allocation_id, decision, reason):
    with reporting_snapshot():
        workspace_binding(actor, FINANCE)
        row = allocations(actor).select_related('receipt__clinic', 'receipt__advance_patient').get(pk=allocation_id)
        _reviewable(actor, row, decision)
        data = dict(allocation=row.pk, decision=decision, reason=_reason(reason),
                    facts=_approval_facts(actor, row) if decision == 'approve' else None)
        return dict(row=row, **data, proposal_token=proposal(actor, REVIEW, FINANCE, data))


@business_errors
@transaction.atomic
def confirm_allocation_review(*, actor, allocation_id, proposal_token, confirmed):
    if confirmed is not True:
        raise RuleError('请明确确认分配复核结果。')
    payload = read_proposal(actor, REVIEW, FINANCE, proposal_token)
    data = payload['data']
    if data['allocation'] != allocation_id:
        raise RuleError('确认内容与当前分配不同。')
    initial = allocations(actor).select_related('receipt__clinic', 'receipt__advance_patient').get(pk=allocation_id)
    lock_people(actor.pk, initial.prepared_by_id)
    lock_finance_write(actor)
    row = (AdvanceAllocation.objects.select_related('receipt__clinic', 'receipt__advance_patient')
           .select_for_update(of=('self',)).get(pk=initial.pk))
    operation = UUID(payload['operation'])
    if row.review_operation_id == operation:
        return row, True
    _reviewable(actor, row, data['decision'])
    if data['decision'] == 'approve':
        if _approval_facts(actor, row, lock=True) != data['facts']:
            raise RuleError('待付或预收余额已变化，请重新核对后复核。')
    row.state = 'POSTED' if data['decision'] == 'approve' else 'REJECTED'
    row.reviewed_by = actor
    row.reviewed_at = timezone.now()
    row.review_reason = data['reason']
    row.review_operation_id = operation
    row.save(update_fields=['state', 'reviewed_by', 'reviewed_at', 'review_reason', 'review_operation_id'])
    emit(actor, 'ADVANCE_ALLOCATION_' + row.state, row, summary={'receipt_id': row.receipt_id})
    return row, False
