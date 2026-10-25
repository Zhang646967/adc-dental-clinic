"""Finance-owned facts. Pending reservations are not confirmed bank clearance."""
from decimal import Decimal
from django.db.models import Sum, Q, Count, Max
from adc_core.rules import RuleError
from finance.allocation_models import FundAllocation, FundAllocationLine

ZERO = Decimal('0.00')


def claim_funds(claim_id, *, exclude=None):
    q = FundAllocationLine.objects.filter(claim_id=claim_id)
    if exclude is not None:
        q = q.exclude(allocation_id=exclude)
    r = q.aggregate(last=Max('pk'), count=Count('pk'),
        decided=Count('pk', filter=~Q(allocation__state='PENDING')),
        received=Sum('amount', filter=Q(allocation__state='CONFIRMED', allocation__transfer__kind='RECEIPT')),
        returned=Sum('amount', filter=Q(allocation__state='CONFIRMED', allocation__transfer__kind='RETURN')),
        reserved_in=Sum('amount', filter=Q(allocation__state='PENDING', allocation__transfer__kind='RECEIPT')),
        reserved_out=Sum('amount', filter=Q(allocation__state='PENDING', allocation__transfer__kind='RETURN')))
    result = {k: r[k] or ZERO for k in ('received', 'returned', 'reserved_in', 'reserved_out')}
    result['net_received'] = result['received'] - result['returned']
    result['cursor'] = [r['last'] or 0, r['count'], r['decided']]
    return result


def transfer_funds(transfer, *, exclude=None):
    q = FundAllocation.objects.filter(transfer=transfer)
    if exclude is not None:
        q = q.exclude(pk=exclude)
    r = q.aggregate(last=Max('pk'), count=Count('pk'), decided=Count('pk', filter=~Q(state='PENDING')),
        confirmed=Sum('total', filter=Q(state='CONFIRMED')), pending=Sum('total', filter=Q(state='PENDING')))
    result = {k: r[k] or ZERO for k in ('confirmed', 'pending')}
    result['available'] = transfer.line.amount - result['confirmed'] - result['pending']
    result['cursor'] = [r['last'] or 0, r['count'], r['decided']]
    return result


def require_no_pending(claim_id):
    facts = claim_funds(claim_id)
    if facts['reserved_in'] or facts['reserved_out']:
        raise RuleError('本申报仍有待复核的基金分配，请先核对或退回原分配。')
    return facts


def require_returned(claim_id):
    facts = require_no_pending(claim_id)
    if facts['net_received'] != ZERO:
        raise RuleError('原申报仍有已到账未退回基金，请先用真实的合成出账凭据逐笔核对退回。')
    return facts


def daily_fund_summary(clinic_id, business_date):
    """Aggregates only: service day, bank day and cash handover are distinct."""
    from django.db.models import OuterRef, Subquery
    from insurance.settlement_models import SettlementRequest
    from finance.fund_models import FundTransfer
    from finance.allocation_models import FundIssue, FundIssueEvent
    claims = SettlementRequest.objects.filter(arrangement__clinic_id=clinic_id, service_on=business_date,
        state__in=['CONFIRMED', 'CANCEL_PENDING'], review__decision='APPROVE')
    totals = claims.aggregate(count=Count('pk'), receivable=Sum('fund_amount'))
    allocated = FundAllocationLine.objects.filter(claim_id__in=claims.values('pk')).aggregate(
        received=Sum('amount', filter=Q(allocation__state='CONFIRMED', allocation__transfer__kind='RECEIPT')),
        returned=Sum('amount', filter=Q(allocation__state='CONFIRMED', allocation__transfer__kind='RETURN')),
        pending=Count('pk', filter=Q(allocation__state='PENDING')))
    bank = FundTransfer.objects.filter(line__account__clinic_id=clinic_id, line__booked_on=business_date,
        state='CONFIRMED').aggregate(incoming=Sum('line__amount', filter=Q(kind='RECEIPT')),
            outgoing=Sum('line__amount', filter=Q(kind='RETURN')))
    last = FundIssueEvent.objects.filter(issue_id=OuterRef('pk')).order_by('-sequence')
    open_issues = FundIssue.objects.filter(claim__arrangement__clinic_id=clinic_id, claim__service_on=business_date
        ).annotate(current=Subquery(last.values('state')[:1])).filter(current='OPEN').count()
    receivable = totals['receivable'] or ZERO
    received = (allocated['received'] or ZERO) - (allocated['returned'] or ZERO)
    return dict(claim_count=totals['count'], receivable=receivable, net_received=received,
        unreceived=receivable-received, pending=allocated['pending'], open_issues=open_issues,
        bank_in=bank['incoming'] or ZERO, bank_out=bank['outgoing'] or ZERO)
