"""Read models expose financial facts, never clinical notes or patient identifiers."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from django.db.models import Sum, Count
from django.utils import timezone
from adc_core.snapshots import reporting_snapshot
from adc_core.rules import quarter_bounds
from care.ledger import income_by_dentist
from finance.models import Quarter
from finance.policies import CostInput, calculate_profit, POLICY_VERSION
from accounts.finance_access import require_finance_read
from registry.models import Dentist

@dataclass(frozen=True)
class FinancialRow:
    id:int
    dentist_id:int
    employee_no:str
    dentist_name:str
    status:str
    supply:Decimal|None
    operating:Decimal|None
    income:Decimal
    invoice_count:int
    notes:str

@dataclass(frozen=True)
class QuarterReport:
    id:int
    year:int
    number:int
    lock_version:int
    roster_status:str
    rows:tuple
    unlisted:tuple
    result:object
    as_of:datetime
    in_progress:bool
    policy_version:str=POLICY_VERSION

def quarter_report(actor,quarter_id):
    with reporting_snapshot():
        require_finance_read(actor)
        q=Quarter.objects.get(pk=quarter_id);now=timezone.now();start,end=quarter_bounds(q.year,q.quarter_no)
        invoices=income_by_dentist(start,end,now)
        income={r.dentist_id:r.amount for r in invoices};counts={r.dentist_id:r.invoice_count for r in invoices}
        costs=list(q.dentist_costs.select_related('dentist').order_by('dentist__employee_no'))
        result=calculate_profit(income,[CostInput(c.dentist_id,c.cost_status,c.supply_cost,c.operating_expense) for c in costs],q.roster_status=='CONFIRMED')
        rows=tuple(FinancialRow(c.pk,c.dentist_id,c.dentist.employee_no,c.dentist.name,c.cost_status,c.supply_cost,c.operating_expense,income.get(c.dentist_id,Decimal('0.00')),counts.get(c.dentist_id,0),c.notes) for c in costs)
        unlisted=tuple(Dentist.objects.filter(pk__in=result.off_roster_ids).values('id','employee_no','name'))
        return QuarterReport(q.pk,q.year,q.quarter_no,q.lock_version,q.roster_status,rows,unlisted,result,now,now<end)
