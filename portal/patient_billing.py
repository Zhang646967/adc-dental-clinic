"""Published invoices in the selected patient's own finance scope."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from adc_core.snapshots import reporting_snapshot
from care.models import Invoice
from finance.cash_selectors import with_invoice_balances
from portal.mini_api import endpoint, result
from portal.policies import patient_access


def billing_page(actor, page_number):
    with reporting_snapshot():
        access = patient_access(actor, self_only=True)
        invoices = Invoice.objects.filter(
            visit__patient_id=access.patient_id, current_record_version__state='PUBLISHED',
        ).select_related('visit__clinic__public_directory', 'current_record_version')
        page = Paginator(with_invoice_balances(invoices).order_by('-first_issued_at', '-pk'), 10).get_page(page_number)
        rows = []
        for bill in page:
            record = bill.current_record_version
            rows.append(dict(
                id=bill.pk, invoice_no=bill.invoice_no, visit_id=bill.visit_id,
                clinic=record.billing_header_snapshot.get('clinic_name') or bill.visit.clinic.public_contact['name'],
                scheduled_start=bill.visit.scheduled_start, published_at=record.published_at,
                revision=record.revision_no, total=record.total_amount,
                remaining=bill.remaining, refund_due=bill.refund_due, review_pending=bool(bill.pending_count),
            ))
        return dict(
            rows=rows, page=page.number, pages=page.paginator.num_pages, count=page.paginator.count,
            previous=page.previous_page_number() if page.has_previous() else None,
            next=page.next_page_number() if page.has_next() else None,
        )


@login_required(login_url='portal_login')
@require_GET
@never_cache
def web(request):
    return render(request, 'portal/billing.html', billing_page(request.user, request.GET.get('page')))


@endpoint()
def mini(request):
    return result(request, billing_page(request.user, request.GET.get('page')))
