"""Explicit management definitions, not statutory accounts or salary rules."""
from datetime import date, datetime, time
from decimal import Decimal, ROUND_DOWN
from hashlib import sha256
import json
from adc_core.rules import BUSINESS_TZ, RuleError

POLICY = 'ADC-MANAGEMENT-P1'
ZERO = Decimal('0.00')
CENT = Decimal('0.01')


def month_bounds(year, month):
    try:
        first=date(int(year),int(month),1)
        last=date(first.year+1,1,1) if first.month==12 else date(first.year,first.month+1,1)
        if not 1900<=first.year<=9998: raise ValueError
    except (ValueError,TypeError,OverflowError) as exc: raise RuleError('请选择有效月份。') from exc
    return datetime.combine(first,time.min,BUSINESS_TZ),datetime.combine(last,time.min,BUSINESS_TZ)


def digest(value):
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()


def allocate_cost(amount, minutes):
    """Floor to cents, then stable employee-code order gets each remaining cent."""
    amount=Decimal(amount).quantize(CENT)
    if amount<0 or any(type(v) is not int or v<0 for v in minutes.values()): raise RuleError('分摊基础无效。')
    denominator=sum(minutes.values())
    if not denominator:return {key:ZERO for key in minutes},amount
    result={key:(amount*value/denominator).quantize(CENT,rounding=ROUND_DOWN) for key,value in minutes.items()}
    left=int((amount-sum(result.values(),ZERO))/CENT)
    for key in sorted(key for key,value in minutes.items() if value>0)[:left]:result[key]+=CENT
    if sum(result.values(),ZERO)!=amount:raise RuleError('分摊金额未守恒。')
    return result,ZERO
