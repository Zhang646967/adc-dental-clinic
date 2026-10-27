"""Published invoice facts shared by staff, patient web and native readers."""
from django.http import Http404
from django.shortcuts import get_object_or_404
from care.models import VisitRecordVersion
from finance.cash_selectors import invoice_balance
from clinical.actual_summary import actual_care_summary


def published_invoice(invoice,*,revision=None):
    """Caller authorizes the invoice and supplies a reporting snapshot."""
    record=invoice.current_record_version
    if revision is not None:
        try:
            number=int(revision)
            if number<1:raise ValueError
        except (TypeError,ValueError):raise Http404('无效版本。')
        record=get_object_or_404(VisitRecordVersion,visit_id=invoice.visit_id,revision_no=number,state='PUBLISHED')
    actual=actual_care_summary(invoice.visit_id)
    return dict(invoice_no=invoice.invoice_no,invoice_id=invoice.pk,visit_id=invoice.visit_id,
        revision=record.revision_no,header=record.billing_header_snapshot,issued_at=invoice.first_issued_at,
        total=record.total_amount,outcome=record.outcome,
        lines=list(record.treatment_lines.values('name_snapshot','unit_snapshot','quantity','unit_price','line_amount')),
        no_charge_stages=actual['no_charge_stages'],is_current=record.pk==invoice.current_record_version_id,
        published_at=record.published_at,
        revisions=list(VisitRecordVersion.objects.filter(visit_id=invoice.visit_id,state='PUBLISHED')
            .order_by('-revision_no').values('revision_no','published_at')),
        cash_balance=invoice_balance(invoice))
