"""Insurance-owned read contract for finance and care, without patient identity."""
from decimal import Decimal
from django.db.models import Count, Max, Sum, Q, OuterRef, Subquery, DecimalField, Value
from django.db.models.functions import Coalesce
from adc_core.rules import RuleError
from insurance.settlement_models import SettlementRequest, ACTIVE_SETTLEMENT_STATES, CREDIT_STATES

ZERO = Decimal('0.00')
UNRESOLVED = ('PROCESSING', 'UNKNOWN', 'AWAITING_REVIEW', 'REVIEW_REJECTED', 'CANCEL_PENDING')


def invoice_insurance_facts(invoice_id):
    rows = SettlementRequest.objects.filter(invoice_id=invoice_id)
    approved = Q(state__in=CREDIT_STATES, review__decision='APPROVE')
    r = rows.aggregate(last=Max('pk'), count=Count('pk'), versions=Sum('lock_version'),
        personal=Sum('personal_account', filter=approved), fund=Sum('fund_amount', filter=approved),
        unresolved=Count('pk', filter=Q(state__in=UNRESOLVED)),
        active=Count('pk', filter=Q(state__in=ACTIVE_SETTLEMENT_STATES)))
    return dict(cursor=[r['last'] or 0, r['count'], r['versions'] or 0],
        personal_account=r['personal'] or ZERO, fund_amount=r['fund'] or ZERO,
        unresolved=r['unresolved'], active=r['active'])


def require_cash_ready(invoice_id):
    facts = invoice_insurance_facts(invoice_id)
    if facts['unresolved']:
        raise RuleError('本账单的医保请求仍待处理、结果未知或待复核；请先查询并处理原请求，再办理收退款。')
    return facts


def require_correction_ready(invoice_id):
    if invoice_insurance_facts(invoice_id)['active']:
        raise RuleError('本账单已有未终结医保请求；请先处理并完成原结算撤销，再更正实际收费。')


def credit_expressions():
    """Bounded subqueries for finance's authorized invoice list (no N+1)."""
    field = DecimalField(max_digits=20, decimal_places=2)
    rows = SettlementRequest.objects.filter(invoice_id=OuterRef('pk'), state__in=CREDIT_STATES,
        review__decision='APPROVE').order_by().values('invoice_id')
    return {label: Coalesce(Subquery(rows.annotate(value=Sum(source)).values('value'), output_field=field),
            Value(ZERO), output_field=field)
        for label, source in [('insurance_personal_account', 'personal_account'), ('insurance_fund', 'fund_amount')]}
