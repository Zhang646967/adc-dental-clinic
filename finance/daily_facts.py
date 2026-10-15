"""Per-clinic/date lock protocol shared with cash commands; aggregate-only reads."""
from decimal import Decimal
from datetime import date
from itertools import islice
from django.db import connection
from django.db.models import Count, Max, Sum, Q
from finance.cash_models import CashEntry

KINDS = ('RECEIPT','REFUND','EQUIPMENT_EXPENSE','EXPENSE_REVERSAL')
LABELS = ('收款','退款','设备付款','设备费用冲回')

def lock_day(clinic_id, day):
    if not connection.in_atomic_block:
        raise RuntimeError('Daily reconciliation lock requires a transaction')
    with connection.cursor() as c:
        c.execute("SELECT pg_advisory_xact_lock(hashtextextended('adc.daily-close:' || %s || ':' || %s, 0))", [str(clinic_id), day.isoformat()])

def _aggregates():
    return dict(
        count=Count('pk'), last=Max('pk'), versions=Sum('lock_version'),
        pending=Count('pk',filter=Q(state='PENDING')),
        posted_count=Count('pk',filter=Q(state='POSTED')),
        **{k:Sum('amount',filter=Q(state='POSTED',kind=k)) for k in KINDS})
def _snapshot(values):
    return dict(cursor=[values.get('count',0),values.get('last') or 0,values.get('versions') or 0],
        pending=values.get('pending',0),posted_count=values.get('posted_count',0),
        totals={k:format(values.get(k) or Decimal('0'),'.2f') for k in KINDS})

def day_facts(clinic_id, day):
    return _snapshot(CashEntry.objects.filter(clinic_id=clinic_id,occurred_on=day).aggregate(**_aggregates()))

def page_day_facts(pairs):
    """One bounded aggregate for an already authorized page, inside its snapshot.

    Exact clinic/date pairs avoid widening the read to a Cartesian product.
    This helper is not an authorization boundary; callers must scope the page.
    """
    pairs=list(islice(pairs,21))
    if len(pairs)>20 or any(not isinstance(p,tuple) or len(p)!=2 or
            type(p[0]) is not int or p[0]<=0 or type(p[1]) is not date for p in pairs):
        raise ValueError('Expected at most 20 exact clinic/date pairs')
    result={p:_snapshot({}) for p in pairs}
    if not result:return result
    scope=Q(pk__in=[])
    for clinic,day in result:scope|=Q(clinic_id=clinic,occurred_on=day)
    for row in CashEntry.objects.filter(scope).order_by().values('clinic_id','occurred_on').annotate(**_aggregates()):
        result[(row['clinic_id'],row['occurred_on'])]=_snapshot(row)
    return result

def comparison(snapshot,declared):
    return [dict(kind=k,label=label,ledger=snapshot['totals'][k],declared=declared[k],
        difference=Decimal(declared[k])-Decimal(snapshot['totals'][k])) for k,label in zip(KINDS,LABELS)]
