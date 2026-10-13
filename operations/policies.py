"""Operational metrics [D], not industry norms or clinical quality ratings."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime, time, timedelta
from adc_core.rules import RuleError, BUSINESS_TZ
POLICY_VERSION='ADC-OPS-0.5'
ATTENDED=('CHECKED_IN','COMPLETED','CLOSED_NO_TREATMENT')

def period_bounds(start,end):
    if type(start) is not date or type(end) is not date or start>end or (end-start).days>365:
        raise RuleError('请选择不超过366天的有效日期区间。')
    if end>=date(9999,12,31): raise RuleError('结束日期超出范围。')
    return datetime.combine(start,time.min,BUSINESS_TZ),datetime.combine(end+timedelta(days=1),time.min,BUSINESS_TZ)

def percent(n,d):
    if type(n) is not int or type(d) is not int or n<0 or d<0 or n>d:
        raise RuleError('比例计数无效。')
    return None if d==0 else (Decimal(n)*100/Decimal(d)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)

@dataclass(frozen=True)
class Metrics:
    arrived:int
    patient_cancel:int
    clinic_cancel:int
    no_show:int
    pending:int
    denominator:int
    cancel_rate:Decimal|None
    no_show_rate:Decimal|None
    completeness:Decimal|None

def summarize(groups):
    """groups contains (status, cancellation_party, count) for MATURE visits only.
    No treatment rows or patient identities allowed in this contract.
    """
    a=cp=cc=n=u=0
    for status,party,count in groups:
        if type(count) is not int or count<0: raise RuleError('记录计数必须是非负整数。')
        if status=='RESCHEDULED': continue
        if status in ATTENDED:a+=count
        elif status=='CANCELLED' and party=='PATIENT':cp+=count
        elif status=='CANCELLED' and party=='CLINIC':cc+=count
        elif status=='NO_SHOW':n+=count
        else:u+=count
    d=a+cp+n;total=d+cc+u
    return Metrics(a,cp,cc,n,u,d,percent(cp,d),percent(n,d),percent(total-u,total))
