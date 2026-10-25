"""Insurance-owned claim facts and lock order for finance's fund operations."""
from django.core.exceptions import ObjectDoesNotExist
from adc_core.rules import RuleError
from insurance.policies import scope
from insurance.settlement_models import SettlementRequest


def claims(actor, ids, *, lock=False):
    scope(actor, ('FINANCE',))
    ids = sorted(set(ids))
    rows = list(SettlementRequest.objects.filter(pk__in=ids).select_related(
        'invoice__visit', 'arrangement', 'review').order_by('pk'))
    if len(rows) != len(ids):
        raise ObjectDoesNotExist('申报不存在。')
    if lock:
        # Lock the whole set in the same layer order as every clinical command.
        # Iterating per invoice would invert patient/slot order for a batch.
        from scheduling.coordination import lock_slots
        from patients.models import Patient
        from scheduling.models import Visit
        from care.models import Invoice
        lock_slots(sorted({r.invoice.visit.availability_slot_id for r in rows}))
        list(Patient.objects.select_for_update().filter(
            pk__in={r.invoice.visit.patient_id for r in rows}).order_by('pk'))
        list(Visit.objects.select_for_update().filter(
            pk__in={r.invoice.visit_id for r in rows}).order_by('pk'))
        list(Invoice.objects.select_for_update().filter(
            pk__in={r.invoice_id for r in rows}).order_by('pk'))
        rows = list(SettlementRequest.objects.select_for_update(of=('self',)).filter(
            pk__in=ids).select_related('invoice', 'arrangement', 'review').order_by('pk'))
    return {row.pk: row for row in rows}


def allocation_source(row, *, kind, clinic_id, currency):
    allowed = ('CONFIRMED',) if kind == 'RECEIPT' else ('CONFIRMED', 'CANCEL_PENDING')
    if row.state not in allowed or not hasattr(row, 'review') or row.review.decision != 'APPROVE':
        raise RuleError('到账分配须为已独立通过的有效申报；撤销处理中仅可核对原已到账资金的退回。')
    if row.arrangement.clinic_id != clinic_id or row.currency != currency:
        raise RuleError('基金分配只能关联同一诊所、同一币种的申报。')
    return dict(claim=row.pk, request_id=str(row.request_id), revision=row.lock_version,
        source_digest=row.source_digest, clinic=clinic_id, currency=row.currency,
        fund_amount=str(row.fund_amount), service_on=row.service_on.isoformat())
