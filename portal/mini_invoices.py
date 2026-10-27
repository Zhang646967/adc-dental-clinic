"""Self-only published invoices; appointment delegation never grants this read."""
from django.shortcuts import get_object_or_404
from adc_core.snapshots import reporting_snapshot
from care.models import Invoice
from care.invoice_queries import published_invoice
from portal.mini_api import endpoint,result
from portal.policies import patient_access


@endpoint()
def detail(request,pk):
    access=patient_access(request.user,self_only=True)
    with reporting_snapshot():
        invoice=get_object_or_404(Invoice.objects.select_related('current_record_version'),pk=pk,
            visit__patient_id=access.patient_id)
        data=published_invoice(invoice,revision=request.GET.get('revision'))
    return result(request,data)
