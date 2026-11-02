"""Patient-safe posted cash projection; caller authorizes the invoice and snapshot."""
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from finance.cash_models import CashEntry
from finance.cash_selectors import ZERO


def invoice_activity(invoice, *, page=1):
    rows = CashEntry.objects.filter(invoice_id=invoice.pk, state='POSTED',
                                  kind__in=('RECEIPT', 'REFUND'))
    totals = rows.aggregate(receipts=Sum('amount', filter=Q(kind='RECEIPT')),
                            refunds=Sum('amount', filter=Q(kind='REFUND')))
    page_obj = Paginator(rows.order_by('-pk').values(
        'id', 'kind', 'amount', 'occurred_on', 'reviewed_at'), 20).get_page(page)
    entries = [dict(id=row['id'], kind=row['kind'],
                    label='收款' if row['kind'] == 'RECEIPT' else '退款',
                    amount=row['amount'], currency='CNY', occurred_on=row['occurred_on'],
                    posted_at=row['reviewed_at'], state='POSTED', status='已记账')
               for row in page_obj.object_list]
    return dict(receipts=totals['receipts'] or ZERO, refunds=totals['refunds'] or ZERO,
                entries=entries, count=page_obj.paginator.count,
                page=page_obj.number, pages=page_obj.paginator.num_pages,
                previous=page_obj.previous_page_number() if page_obj.has_previous() else None,
                next=page_obj.next_page_number() if page_obj.has_next() else None)
