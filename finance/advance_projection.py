"""Amounts applied to invoices. These records do not represent cash movement."""
from decimal import Decimal

from django.db.models import Count, Exists, Max, OuterRef, Q, Sum

from finance.advance_models import AdvanceAllocationLine, AdvanceAllocationReversal
from finance.cash_models import CashEntry

ZERO = Decimal('0.00')


def receipt_applied(receipt_rows):
    return (applied_lines().filter(allocation__receipt__in=receipt_rows)
            .aggregate(total=Sum('amount'))['total'] or ZERO)


def posted_lines():
    return AdvanceAllocationLine.objects.filter(allocation__state='POSTED')


def _reversed():
    return Exists(AdvanceAllocationReversal.objects.filter(line_id=OuterRef('pk'), state='POSTED'))


def applied_lines():
    return posted_lines().filter(~_reversed())


def _application_facts(lines):
    values = lines.aggregate(total=Sum('amount', filter=Q(~_reversed())),
        last=Max('pk'), count=Count('pk'), reversed=Count('pk', filter=Q(_reversed())))
    stamp = [values['last'], values['count']] if values['count'] else []
    if values['reversed']:
        stamp.append(values['reversed'])
    return values['total'] or ZERO, stamp


def invoice_advance_facts(invoice_id):
    return _application_facts(posted_lines().filter(invoice_id=invoice_id))


def receipt_application_cursor(receipt_id):
    return _application_facts(posted_lines().filter(allocation__receipt_id=receipt_id))[1]


def receipt_available(receipt):
    refunds = CashEntry.objects.filter(reversal_of=receipt, state='POSTED', kind='REFUND',
                                       advance_patient__isnull=False).aggregate(total=Sum('amount'))['total']
    return receipt.amount - (refunds or ZERO) - receipt_applied(CashEntry.objects.filter(pk=receipt.pk))


def applied_invoice_amounts():
    return (applied_lines().filter(invoice_id=OuterRef('pk')).order_by().values('invoice_id')
            .annotate(total=Sum('amount')).values('total'))
