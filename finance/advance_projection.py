"""Amounts applied to invoices. These records do not represent cash movement."""
from decimal import Decimal

from django.db.models import Count, Max, OuterRef, Sum

from finance.advance_models import AdvanceAllocation, AdvanceAllocationLine

ZERO = Decimal('0.00')


def receipt_applied(receipt_rows):
    return (AdvanceAllocation.objects.filter(receipt__in=receipt_rows, state='POSTED')
            .aggregate(total=Sum('total'))['total'] or ZERO)


def applied_lines():
    return AdvanceAllocationLine.objects.filter(allocation__state='POSTED')


def invoice_advance_facts(invoice_id):
    values = applied_lines().filter(invoice_id=invoice_id).aggregate(
        total=Sum('amount'), last=Max('pk'), count=Count('pk'))
    return values['total'] or ZERO, [values['last'], values['count']] if values['count'] else []


def applied_invoice_amounts():
    return (applied_lines().filter(invoice_id=OuterRef('pk')).order_by().values('invoice_id')
            .annotate(total=Sum('amount')).values('total'))
