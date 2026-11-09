"""A posted-only advance statement for an already authorized patient."""
from django.core.paginator import Paginator
from django.db.models import CharField, F, Q, Sum, Value
from django.db.models.functions import TruncDate
from django.http import Http404

from finance.advance_models import AdvanceAllocationReversal
from finance.advance_projection import ZERO, applied_lines, posted_lines
from finance.cash_models import CashEntry

LABELS = {
    'RECEIPT': '预收到账', 'ALLOCATION': '账单抵扣',
    'REVERSAL': '抵扣撤销', 'REFUND': '原渠道退款',
}
EVENT_FIELDS = ('id', 'event', 'amount', 'business_date', 'posted_at', 'invoice_id', 'invoice_number')


def _cash_events(rows):
    return rows.order_by().annotate(
        event=F('kind'), business_date=F('occurred_on'), posted_at=F('reviewed_at'),
        invoice_number=Value('', output_field=CharField()),
    ).values(*EVENT_FIELDS)


def _application_events(lines, reversals=False):
    prefix = 'line__' if reversals else ''
    reviewed_at = 'reviewed_at' if reversals else 'allocation__reviewed_at'
    annotations = dict(
        event=Value('REVERSAL' if reversals else 'ALLOCATION', output_field=CharField()),
        business_date=TruncDate(reviewed_at), posted_at=F(reviewed_at),
        invoice_number=F(prefix + 'invoice__invoice_no'),
    )
    if reversals:
        annotations.update(amount=F('line__amount'), invoice_id=F('line__invoice_id'))
    return lines.order_by().annotate(**annotations).values(*EVENT_FIELDS)


def statement(patient_id, *, clinic='', page=1):
    """Clinic balances are separate. Pending and rejected events are private staff data."""
    cash = CashEntry.objects.filter(advance_patient_id=patient_id, state='POSTED')
    posted = posted_lines().filter(allocation__receipt__advance_patient_id=patient_id)
    used = dict(applied_lines().filter(allocation__receipt__advance_patient_id=patient_id).order_by()
        .values('allocation__receipt__clinic_id').annotate(total=Sum('amount'))
        .values_list('allocation__receipt__clinic_id', 'total'))
    summaries = []
    for row in cash.order_by().values('clinic_id', 'clinic__name').annotate(
            received=Sum('amount', filter=Q(kind='RECEIPT')),
            refunded=Sum('amount', filter=Q(kind='REFUND'))).order_by('clinic__name', 'clinic_id'):
        received, refunded = row['received'] or ZERO, row['refunded'] or ZERO
        applied = used.get(row['clinic_id'], ZERO)
        summaries.append(dict(id=row['clinic_id'], name=row['clinic__name'], received=received,
                              refunded=refunded, applied=applied, available=received-refunded-applied))
    if clinic:
        selected = next((row for row in summaries if str(row['id']) == clinic), None)
        if selected is None:
            raise Http404('当前患者暂无该门店的预收记录。')
    else:
        selected = summaries[0] if summaries else None
    rows = []
    if selected:
        clinic_id = selected['id']
        scoped = posted.filter(allocation__receipt__clinic_id=clinic_id)
        reversed_rows = AdvanceAllocationReversal.objects.filter(state='POSTED', line__in=scoped)
        rows = _cash_events(cash.filter(clinic_id=clinic_id)).union(
            _application_events(scoped), _application_events(reversed_rows, reversals=True), all=True,
        ).order_by('-posted_at', 'event', '-id')
    page_obj = Paginator(rows, 20).get_page(page)
    entries = [dict(row, key=f"{row['event']}:{row['id']}", label=LABELS[row['event']])
               for row in page_obj.object_list]
    return dict(clinics=summaries, selected=selected, entries=entries, count=page_obj.paginator.count,
                page=page_obj.number, pages=page_obj.paginator.num_pages,
                previous=page_obj.previous_page_number() if page_obj.has_previous() else None,
                next=page_obj.next_page_number() if page_obj.has_next() else None)
