"""Patient-visible facts from the existing visit, settlement and recall records."""
from adc_core.rules import CLOSED_STATUSES
from adc_core.snapshots import reporting_snapshot
from care.medication_charges import charge_projection
from care.models import Invoice
from clinical.next_visits import instruction_booking_projection
from clinical.plan_models import NextVisitInstruction, PerformedProcedure
from finance.cash_selectors import invoice_balance
from portal.patient_dashboard import needs_outcome_review


def _followup(row, now):
    booking = instruction_booking_projection(row)
    promises = [promise['current'] for promise in booking['promises']]
    active = next((visit for visit in promises if visit.status in ('SCHEDULED', 'CHECKED_IN')), None)
    appointment = active or (promises[0] if promises else None)
    recall = getattr(row, 'recall', None)

    if row.state == 'WITHDRAWN':
        status, label = 'WITHDRAWN', '已撤回复诊指示'
    elif recall and recall.state == 'COMPLETED':
        status, label = 'COMPLETED', '复诊目标已核对'
    elif booking['report_review'] or (recall and recall.state == 'REVIEW') or (active and needs_outcome_review(active, now)):
        status, label = 'REVIEW', '待门店核对'
    elif active:
        status, label = 'BOOKED', '已安排复诊'
    elif booking['needs_booking']:
        status, label = 'WAITING', '待重新安排' if appointment else '待安排'
    else:
        status, label = 'REVIEW', '已有复诊记录，待门店核对'

    return dict(id=row.pk, service=row.service.name, earliest_on=row.earliest_on, latest_on=row.latest_on,
        status=status, label=label, overdue=booking['overdue'] and status == 'WAITING',
        appointment=dict(id=appointment.pk, visit_no=appointment.visit_no, start=appointment.scheduled_start,
            status=appointment.status, status_label=appointment.get_status_display()) if appointment else None)


def _published_result(invoice):
    record = invoice.current_record_version
    actual = list(PerformedProcedure.objects.filter(encounter__visit_id=invoice.visit_id, state='ACTIVE')
        .order_by('pk').values('charge_line__line_no', 'charge_snapshot', 'quantity', 'charge_mode'))
    source_lines = {row['charge_line__line_no'] for row in actual}
    # Line numbers retain the structured execution link through invoice revisions.
    treatments = [dict(name=row['charge_snapshot']['name'], unit=row['charge_snapshot']['unit'],
        quantity=row['quantity'], kind='NO_CHARGE_STAGE' if row['charge_mode'] == 'NO_CHARGE' else 'CHARGED')
        for row in actual]
    treatments.extend(dict(name=row['name_snapshot'], unit=row['unit_snapshot'], quantity=row['quantity'], kind='CHARGED')
        for row in record.treatment_lines.values('line_no', 'name_snapshot', 'unit_snapshot', 'quantity')
        if row['line_no'] not in source_lines)
    medications = [
        dict(name=row['name_snapshot'], unit=row['unit_snapshot'], net_quantity=row['quantity'],
            amount=row['line_amount'])
        for row in charge_projection(record)
    ]
    balance = invoice_balance(invoice)
    return (
        dict(outcome=record.outcome, outcome_label=record.get_outcome_display(), treatments=treatments,
            medications=medications),
        dict(invoice_id=invoice.pk, invoice_no=invoice.invoice_no, revision=record.revision_no,
            total=record.total_amount, remaining=balance['remaining'], refund_due=balance['refund_due'],
            review_pending=bool(balance['pending'] or balance['insurance_pending'])),
    )


def visit_review(visit, *, access, now):
    """The caller has already scoped this visit to the selected patient."""
    summary = dict(attended_at=visit.attended_at, completed_at=None if access.delegated else visit.completed_at,
        care=None, settlement=None, followups=[])
    if access.delegated or visit.status not in CLOSED_STATUSES:
        return summary

    with reporting_snapshot():
        invoice = Invoice.objects.select_related('current_record_version').filter(
            visit_id=visit.pk, current_record_version__state='PUBLISHED').first()
        if invoice:
            summary['care'], summary['settlement'] = _published_result(invoice)
        instructions = NextVisitInstruction.objects.filter(
            source_record__encounter__visit_id=visit.pk).select_related(
                'service', 'recall', 'source_record__encounter__visit').order_by('earliest_on', 'pk')
        summary['followups'] = [_followup(row, now) for row in instructions]
    return summary
