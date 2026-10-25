"""Shared statement ownership; both cash matching and fund evidence use this."""
from django.db.models import Count, Max
from adc_core.rules import RuleError
from finance.fund_models import StatementUse


def usage_cursor(line_id):
    rows=StatementUse.objects.filter(line_id=line_id)
    r=rows.aggregate(last=Max('pk'),count=Count('pk'))
    return [r['last'] or 0,r['count'],rows.filter(state='RELEASED').count()]


def require_available(line_id, *, cash_match_id=None, fund_transfer_id=None):
    rows=StatementUse.objects.filter(line_id=line_id,state='ACTIVE')
    if cash_match_id is not None: rows=rows.exclude(cash_match_id=cash_match_id)
    if fund_transfer_id is not None: rows=rows.exclude(fund_transfer_id=fund_transfer_id)
    if rows.exists():
        raise RuleError('这条银行流水已用于现金对账或基金办理，请先核对原用途，不能重复使用。')
