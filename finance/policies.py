"""Financial policy [D]. Not statutory profit, cash receipts or payroll."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from adc_core.rules import RuleError, decimal_value, CENT
POLICY_VERSION="ADC-FIN-0.5"
FUND_RATE=Decimal("0.10")
MAX_MONEY=Decimal("99999999999999.99")

def money(value):
    return decimal_value(value,2,MAX_MONEY).quantize(CENT)

@dataclass(frozen=True)
class CostInput:
    dentist_id:int
    status:str
    supply:Decimal|None
    operating:Decimal|None

@dataclass(frozen=True)
class ProfitResult:
    ready:bool
    income:Decimal
    supply:Decimal|None
    operating:Decimal|None
    profit:Decimal|None
    fund:Decimal|None
    missing_ids:tuple
    off_roster_ids:tuple
    reasons:tuple

def calculate_profit(income_by_dentist, costs, roster_confirmed):
    """Pure computation. Inputs already authorized and from the same DB snapshot.
    Both streams have dentist-quarter grain; zero-revenue costs are retained.
    """
    costs=tuple(costs)
    ids=[c.dentist_id for c in costs]
    if len(ids)!=len(set(ids)): raise RuleError("季度纳入清单存在重复牙医。")
    income={i:money(v) for i,v in income_by_dentist.items()}
    missing=[];supply=Decimal('0.00');operating=Decimal('0.00')
    for c in costs:
        if c.status!='CONFIRMED' or c.supply is None or c.operating is None:
            missing.append(c.dentist_id)
        else:
            supply+=money(c.supply);operating+=money(c.operating)
    off=tuple(sorted(set(income)-set(ids)))
    reasons=[]
    if not roster_confirmed: reasons.append('季度纳入清单尚未确认')
    if not costs: reasons.append('纳入清单为空，不能推断为全链零成本')
    if missing: reasons.append('部分纳入牙医的成本尚未确认')
    if off: reasons.append('有开单记录的牙医未纳入清单')
    total=sum(income.values(),Decimal('0.00'))
    if reasons: return ProfitResult(False,total,None,None,None,None,tuple(missing),off,tuple(reasons))
    profit=total-supply-operating
    fund=(profit*FUND_RATE).quantize(CENT,rounding=ROUND_HALF_UP) if profit>0 else None
    return ProfitResult(True,total,supply,operating,profit,fund,(),(),())

def safe_csv_cell(value):
    text=str(value)
    if text.lstrip().startswith(('=','+','-','@')) or text.startswith(('\t','\r','\n')):
        return "'"+text
    return text
