"""Internal read contract for authorized management services.
Call ONLY after role authorization, inside the caller's reporting snapshot.
Changing invoice version storage should not change finance callers.
"""
from dataclasses import dataclass
from decimal import Decimal
from django.db.models import Sum, Count
from care.models import Invoice

@dataclass(frozen=True)
class IncomeRow:
    dentist_id:int
    amount:Decimal
    invoice_count:int

def income_by_dentist(start,end,as_of):
    qs=Invoice.objects.filter(visit__completed_at__gte=start,visit__completed_at__lt=end,visit__completed_at__lte=as_of)
    rows=qs.values('visit__dentist_id').annotate(amount=Sum('current_record_version__total_amount'),n=Count('id')).order_by()
    return tuple(IncomeRow(r['visit__dentist_id'],r['amount'],r['n']) for r in rows)
