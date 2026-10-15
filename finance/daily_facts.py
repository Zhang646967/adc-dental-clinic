"""Per-clinic/date lock protocol shared with cash commands; aggregate-only reads."""
from decimal import Decimal
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

def day_facts(clinic_id, day):
    values = CashEntry.objects.filter(clinic_id=clinic_id,occurred_on=day).aggregate(
        count=Count('pk'), last=Max('pk'), versions=Sum('lock_version'),
        pending=Count('pk',filter=Q(state='PENDING')),
        posted_count=Count('pk',filter=Q(state='POSTED')),
        **{k:Sum('amount',filter=Q(state='POSTED',kind=k)) for k in KINDS})
    return dict(cursor=[values['count'],values['last'] or 0,values['versions'] or 0],
        pending=values['pending'],posted_count=values['posted_count'],
        totals={k:format(values[k] or Decimal('0'),'.2f') for k in KINDS})

def comparison(snapshot,declared):
    return [dict(kind=k,label=label,ledger=snapshot['totals'][k],declared=declared[k],
        difference=Decimal(declared[k])-Decimal(snapshot['totals'][k])) for k,label in zip(KINDS,LABELS)]
