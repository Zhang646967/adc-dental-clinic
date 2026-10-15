"""Source-event reconciliation, including known fees without any cash request."""
from urllib.parse import urlencode
from decimal import Decimal
from django.core.paginator import Paginator
from django.db.models import Q,F,Value,Case,When,Sum,Count,OuterRef,Subquery,Exists,DecimalField,CharField,IntegerField
from django.db.models.functions import Coalesce
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from equipment.models import EquipmentEvent,EquipmentCostAmendment
from equipment.policies import equipment_scope
from finance.cash_models import CashEntry

ZERO=Decimal('0.00')
FEE_STATES={'COST_PENDING':'费用依据待审核','UNREQUESTED':'尚未提交','PENDING':'有待审核申请','POSTED':'已核对记账','REVERSED':'已冲回，待重新核对','ATTENTION':'金额需要核对','UNKNOWN':'费用未登记','ZERO':'明确零费用'}

def source_id(value):
    if type(value) is not str or not 1<=len(value)<=19 or not value.isascii() or not value.isdecimal() or not 0<int(value)<2**63:
        raise RuleError('核对来源编号无效。')
    return int(value)

def annotate_fees(qs):
    approved=EquipmentCostAmendment.objects.filter(event_id=OuterRef('pk'),state='APPROVED').order_by('-pk')
    qs=qs.annotate(pending_cost_amendment=Exists(EquipmentCostAmendment.objects.filter(event_id=OuterRef('pk'),state='PENDING')),cost_amendment_id=Subquery(approved.values('pk')[:1]),
        effective_cost=Coalesce(Subquery(approved.values('proposed_cost')[:1]),F('cost')))
    cash=CashEntry.objects.filter(equipment_event_id=OuterRef('pk')).order_by().values('equipment_event_id')
    signed=Case(When(kind='EQUIPMENT_EXPENSE',then=F('amount')),When(kind='EXPENSE_REVERSAL',then=-F('amount')),
                default=Value(ZERO),output_field=DecimalField(max_digits=20,decimal_places=2))
    posted=cash.filter(state='POSTED')
    pending=cash.filter(state='PENDING')
    qs=qs.annotate(net_expense=Coalesce(Subquery(posted.annotate(total=Sum(signed)).values('total'),
            output_field=DecimalField(max_digits=20,decimal_places=2)),Value(ZERO)),
        pending_requests=Coalesce(Subquery(pending.annotate(total=Count('pk')).values('total'),output_field=IntegerField()),Value(0)),
        posted_requests=Coalesce(Subquery(posted.annotate(total=Count('pk')).values('total'),output_field=IntegerField()),Value(0)))
    mismatch=Q(net_expense__lt=0)|(Q(net_expense__gt=0)&~Q(net_expense=F('effective_cost')))
    return qs.annotate(fee_state=Case(
        When(~Q(kind__in=['REGISTER','SERVICE']),then=Value('NOT_FEE')),
        When(effective_cost__isnull=True,then=Value('UNKNOWN')),When(effective_cost=0,then=Value('ZERO')),
        When(mismatch,then=Value('ATTENTION')),When(pending_cost_amendment=True,then=Value('COST_PENDING')),When(pending_requests__gt=0,then=Value('PENDING')),
        When(net_expense=F('effective_cost'),then=Value('POSTED')),When(posted_requests__gt=0,then=Value('REVERSED')),
        default=Value('UNREQUESTED'),output_field=CharField()))

def fee_worklist(actor,state='',page='1',asset=''):
    if state not in ('',*FEE_STATES):raise RuleError('设备费用筛选无效。')
    asset_id=source_id(asset) if asset else None
    with reporting_snapshot():
        clinic=equipment_scope(actor)
        qs=EquipmentEvent.objects.filter(kind__in=['REGISTER','SERVICE'])
        if clinic is not None:qs=qs.filter(asset__clinic_id=clinic)
        if asset_id is not None:qs=qs.filter(asset_id=asset_id)
        qs=annotate_fees(qs)
        unknown=qs.filter(effective_cost__isnull=True).count();zero=qs.filter(effective_cost=0).count()
        known=qs.filter(effective_cost__gt=0)
        totals=known.aggregate(events=Count('pk'),recorded_cost=Sum('effective_cost'),net_total=Sum('net_expense'),
            pending_sources=Count('pk',filter=Q(pending_requests__gt=0)),
            unrequested=Count('pk',filter=Q(fee_state='UNREQUESTED')),reversed=Count('pk',filter=Q(fee_state='REVERSED')))
        totals.update(recorded_cost=totals['recorded_cost'] or ZERO,net_expense=totals.pop('net_total') or ZERO,
                      unknown_cost=unknown,zero_cost=zero)
        if state in ('UNKNOWN','ZERO'):known=qs.filter(fee_state=state)
        elif state:known=known.filter(fee_state=state)
        page_obj=Paginator(known.select_related('asset__clinic','recorded_by').order_by('-performed_on','-pk'),20).get_page(page)
        rows=list(page_obj.object_list)
        for row in rows:row.fee_label=FEE_STATES[row.fee_state]
        return dict(rows=rows,page_obj=page_obj,totals=totals,state_filter=state,asset_filter=asset,
                    can_request=actor._adc_workspace.role=='MANAGER',can_read_requests=actor._adc_workspace.role in ('MANAGER','FINANCE'),
                    fee_states=FEE_STATES.items(),page_query=urlencode(dict(state=state,asset=asset)))
