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


def _quarter_work_rows(quarters, now):
    """Caller authorizes and owns the read snapshot; reuse the profit policy."""
    quarters = tuple(quarters)
    costs = {q.pk: [] for q in quarters}
    from finance.models import DentistQuarterCost
    for row in DentistQuarterCost.objects.filter(quarter_id__in=costs).values(
            'quarter_id', 'dentist_id', 'cost_status', 'supply_cost', 'operating_expense'):
        costs[row['quarter_id']].append(CostInput(row['dentist_id'], row['cost_status'],
                                                row['supply_cost'], row['operating_expense']))
    rows = []
    for quarter in quarters:
        start, end = quarter_bounds(quarter.year, quarter.quarter_no)
        income = {r.dentist_id: r.amount for r in income_by_dentist(start, end, now)}
        result = calculate_profit(income, costs[quarter.pk], quarter.roster_status == 'CONFIRMED')
        rows.append({'id': quarter.pk, 'year': quarter.year, 'number': quarter.quarter_no,
                     'roster_confirmed': quarter.roster_status == 'CONFIRMED',
                     'ready': result.ready, 'reasons': result.reasons,
                     'unconfirmed_costs': len(result.missing_ids),
                     'unlisted_dentists': len(result.off_roster_ids), 'in_progress': now < end})
    return tuple(rows)


def quarter_worklist(actor, page='1'):
    from django.core.paginator import Paginator
    with reporting_snapshot():
        require_finance_read(actor)
        now = timezone.now()
        result = Paginator(Quarter.objects.order_by('-year', '-quarter_no', '-pk'), 20).get_page(page)
        rows = _quarter_work_rows(result, now)
        return {'quarters': rows, 'page': result, 'as_of': now}

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
