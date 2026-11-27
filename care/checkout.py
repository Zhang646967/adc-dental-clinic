"""Minimal departure facts shared by front desk and patient projections."""
from django.shortcuts import get_object_or_404

from accounts.policies import require_clinic
from adc_core.rules import CLOSED_STATUSES
from adc_core.snapshots import reporting_snapshot
from care.models import Invoice
from clinical.examination_followup import current_plan_step
from clinical.next_visits import instruction_booking_projection, promise_ids
from clinical.plan_models import NextVisitInstruction, PlanAppointment
from finance.cash_selectors import invoice_balance
from portal.patient_dashboard import needs_outcome_review
from scheduling.models import Visit
from scheduling.service_content import positive_id


def settlement_summary(invoice):
    balance = invoice_balance(invoice)
    fields = ('receipts', 'refunds', 'net_received', 'advance_applied', 'insurance_fund',
        'insurance_personal_account', 'remaining', 'refund_due', 'pending_refunds', 'advance_excess', 'insurance_pending')
    return dict(invoice_id=invoice.pk, invoice_no=invoice.invoice_no,
        revision=balance['current_revision'], total=balance['billed'],
        review_pending=bool(balance['pending'] or balance['insurance_pending']),
        **{key: balance[key] for key in fields})


def _appointment(visit, clinic):
    if visit is None:
        return None
    return dict(id=visit.pk, visit_no=visit.visit_no, start=visit.scheduled_start,
        status=visit.status, status_label=visit.get_status_display(), clinic=clinic)


def _followup(row, source, clinic, now, patient_actor):
    booking = instruction_booking_projection(row)
    linked = {}
    for promise in booking['promises']:
        for visit in (promise['current'], promise['original']):
            if (visit.patient_id, visit.clinic_id) == (source.patient_id, source.clinic_id):
                linked.setdefault(visit.pk, visit)
    active = next((v for v in linked.values() if v.status in ('SCHEDULED', 'CHECKED_IN')), None)
    historical = next((v for v in linked.values() if v.status not in ('SCHEDULED', 'CHECKED_IN')), None)
    recall_state = getattr(getattr(row, 'recall', None), 'state', None)
    booking_source = None
    if row.state == 'WITHDRAWN' or recall_state == 'WITHDRAWN':
        status, label, action = 'WITHDRAWN', '已撤回复诊指示', 'NONE'
    elif recall_state == 'COMPLETED':
        status, label, action = 'COMPLETED', '复诊目标已核对', 'NONE'
    elif recall_state == 'REVIEW':
        status, label, action = 'REVIEW', '复诊安排已暂缓', 'CONTACT'
    elif (booking['report_review'] or not current_plan_step(row)
            or (active and needs_outcome_review(active, now))):
        status, label, action = 'REVIEW', '待门店核对', 'CONTACT'
    elif active:
        status, label, action = 'BOOKED', '已安排复诊', 'VIEW_APPOINTMENT'
    elif booking['needs_booking']:
        status = 'WAITING'
        label = '待重新安排' if historical else '尚未预约'
        action = 'CONTACT'
        if patient_actor and not booking['overdue']:
            from portal.report_followup import checkout_booking_source
            booking_source = checkout_booking_source(source, row, patient_actor)
            if booking_source:
                action = 'BOOK'
    else:
        status, label, action = 'REVIEW', '已有复诊记录，待门店核对', 'CONTACT'

    active_info, history_info = _appointment(active, clinic), _appointment(historical, clinic)
    result = dict(id=row.pk, clinic_id=source.clinic_id, clinic=clinic, service=row.service.name,
        earliest_on=row.earliest_on, latest_on=row.latest_on, status=status, label=label,
        overdue=booking['overdue'] and status == 'WAITING', action=action,
        active_appointment=active_info, historical_appointment=history_info,
        appointment=active_info or history_info)
    if patient_actor:
        result['booking_source'] = booking_source
    if recall_state == 'REVIEW' and status == 'REVIEW':
        result['message'] = '需要继续安排时，可联系原门店。'
    return result


def checkout_facts(visit, now, *, patient_actor=None):
    """Caller owns the authorized snapshot. Keep the invoice internal for the care projection."""
    invoice = None
    state = None
    followups = []
    if visit.status in CLOSED_STATUSES:
        invoice = Invoice.objects.select_related('current_record_version').filter(
            visit_id=visit.pk, current_record_version__state='PUBLISHED').first()
        state = 'PUBLISHED' if invoice else 'AWAITING_PUBLICATION'
        rows = NextVisitInstruction.objects.filter(source_record__encounter__visit_id=visit.pk).select_related(
            'service', 'recall', 'step_version__version__plan', 'source_record__encounter__visit'
        ).order_by('earliest_on', 'pk')
        clinic = visit.public_contact['name']
        followups = [_followup(row, visit, clinic, now, patient_actor) for row in rows]
    elif visit.status == 'CHECKED_IN':
        state = 'AWAITING_PUBLICATION'
    return dict(settlement_state=state, settlement=settlement_summary(invoice) if invoice else None,
        followups=followups), invoice


def checkout_origin(visit, requested):
    """Accept only an actual instruction link from the same patient's same-clinic visit."""
    origin_id = positive_id(requested)
    if not origin_id:
        return None
    origins = PlanAppointment.objects.filter(visit_id__in=promise_ids(visit),
        instruction__source_record__encounter__visit_id=origin_id,
        instruction__source_record__encounter__visit__patient_id=visit.patient_id,
        instruction__source_record__encounter__visit__clinic_id=visit.clinic_id,
        instruction__source_record__encounter__visit__status__in=CLOSED_STATUSES)
    return origin_id if origins.exists() else None


def front_checkout(actor, visit_id, now):
    with reporting_snapshot():
        ctx = actor._adc_workspace
        require_clinic(actor, ctx.clinic_id, roles=('FRONT_DESK',))
        visit = get_object_or_404(Visit.objects.select_related('clinic__public_directory'),
            pk=visit_id, clinic_id=ctx.clinic_id)
        facts, _ = checkout_facts(visit, now)
        return facts
