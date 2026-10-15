"""Cash is a separate projection from billed revenue and dentist-quarter cost."""
from decimal import Decimal
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count,Sum,Max,Q,OuterRef,Subquery,F,Value,DecimalField,Case,When
from django.db.models.functions import Coalesce,Greatest
from accounts.policies import bindings
from adc_core.proposals import workspace_binding
from adc_core.snapshots import reporting_snapshot
from care.models import Invoice
from finance.cash_models import CashEntry

ZERO=Decimal('0.00')
def cash_scope(actor,detail=False):
    b=workspace_binding(actor,('FRONT_DESK','MANAGER','FINANCE','HQ'))
    qs=CashEntry.objects.all()
    if b['role'] in ('FRONT_DESK','MANAGER'):
        if b['clinic'] is None or not bindings(actor).filter(role=b['role'],scope_kind='CLINIC',clinic_id=b['clinic']).exists():
            raise PermissionDenied('请选择获授权的当前诊所。')
        qs=qs.filter(clinic_id=b['clinic'])
        return qs.filter(invoice__isnull=b['role']=='MANAGER')
    if not bindings(actor).filter(role=b['role'],scope_kind='CHAIN').exists() or (detail and b['role']=='HQ'):
        raise PermissionDenied('当前身份无该项明细权限。')
    return qs

def cursor(qs):
    r=qs.aggregate(last=Max('pk'),count=Count('pk'),versions=Sum('lock_version'))
    return [r['last'] or 0,r['count'],r['versions'] or 0]

def posted_amount(qs,plus,minus):
    values=qs.filter(state='POSTED').aggregate(
        incoming=Sum('amount',filter=Q(kind=plus)),outgoing=Sum('amount',filter=Q(kind=minus)))
    return (values['incoming'] or ZERO)-(values['outgoing'] or ZERO)

def invoice_balance(invoice):
    """Internal: caller authorizes this invoice and supplies a reporting snapshot."""
    rows=CashEntry.objects.filter(invoice_id=invoice.pk)
    net=posted_amount(rows,'RECEIPT','REFUND')
    total=invoice.current_record_version.total_amount
    return dict(billed=total,net_received=net,remaining=max(total-net,ZERO),
        refund_due=max(net-total,ZERO),pending=rows.filter(state='PENDING').count(),
        current_revision=invoice.current_record_version.revision_no)

def event_net(event_id):
    return posted_amount(CashEntry.objects.filter(equipment_event_id=event_id),'EQUIPMENT_EXPENSE','EXPENSE_REVERSAL')

def cash_listing(actor,state='',page='1'):
    from adc_core.rules import RuleError
    if state not in ('','PENDING','POSTED','REJECTED'):raise RuleError('记账筛选无效。')
    with reporting_snapshot():
        qs=cash_scope(actor)
        totals=qs.aggregate(pending=Count('pk',filter=Q(state='PENDING')),posted=Count('pk',filter=Q(state='POSTED')),
            receipts=Sum('amount',filter=Q(state='POSTED',kind='RECEIPT')),refunds=Sum('amount',filter=Q(state='POSTED',kind='REFUND')),
            expenses=Sum('amount',filter=Q(state='POSTED',kind='EQUIPMENT_EXPENSE')),expense_reversals=Sum('amount',filter=Q(state='POSTED',kind='EXPENSE_REVERSAL')))
        for k in ('receipts','refunds','expenses','expense_reversals'):totals[k]=totals[k] or ZERO
        totals['net_received']=totals['receipts']-totals['refunds']
        totals['net_equipment_expense']=totals['expenses']-totals['expense_reversals']
        if state:qs=qs.filter(state=state)
        qs=qs.select_related('clinic','invoice','equipment_event__asset','prepared_by','reviewed_by').order_by('-pk')
        page_obj=Paginator(qs,20).get_page(page)
        return dict(rows=list(page_obj.object_list),page_obj=page_obj,totals=totals,state_filter=state,
            detail_allowed=getattr(actor,'_adc_workspace').role!='HQ')

def cash_detail(actor,entry_id):
    with reporting_snapshot():
        row=cash_scope(actor,detail=True).select_related('clinic','invoice__current_record_version','equipment_event__asset','prepared_by','reviewed_by','reversal_of').get(pk=entry_id)
        balance=invoice_balance(row.invoice) if row.invoice_id else dict(known_cost=row.equipment_event.cost,net_equipment_expense=event_net(row.equipment_event_id))
        return dict(entry=row,balance=balance)

def receivables(actor,state='',page='1'):
    from adc_core.rules import RuleError
    if state not in ('','due','credit','settled'):raise RuleError('应收筛选无效。')
    b=workspace_binding(actor,('FRONT_DESK','FINANCE','HQ'))
    with reporting_snapshot():
        qs=Invoice.objects.select_related('visit__clinic','current_record_version')
        if b['role']=='FRONT_DESK':
            if b['clinic'] is None:raise PermissionDenied('请先选择当前诊所。')
            from accounts.policies import clinic_ids
            qs=qs.filter(visit__clinic_id__in=clinic_ids(actor))
        elif not bindings(actor).filter(role=b['role'],scope_kind='CHAIN').exists():
            raise PermissionDenied
        output=DecimalField(max_digits=20,decimal_places=2)
        signed=Case(When(kind='RECEIPT',then=F('amount')),When(kind='REFUND',then=-F('amount')),
                    default=Value(ZERO),output_field=output)
        cash=CashEntry.objects.filter(invoice_id=OuterRef('pk'),state='POSTED').order_by().values('invoice_id').annotate(value=Sum(signed)).values('value')
        qs=qs.annotate(net_received=Coalesce(Subquery(cash,output_field=output),Value(ZERO),output_field=output))
        qs=qs.annotate(remaining=Greatest(F('current_record_version__total_amount')-F('net_received'),Value(ZERO),output_field=output),
                       refund_due=Greatest(F('net_received')-F('current_record_version__total_amount'),Value(ZERO),output_field=output))
        totals=qs.aggregate(bills=Count('pk'),billed=Sum('current_record_version__total_amount'),
                            net_total=Sum('net_received'),remaining_total=Sum('remaining'),refund_total=Sum('refund_due'))
        for source,target in [('net_total','net_received'),('remaining_total','remaining'),('refund_total','refund_due')]:
            totals[target]=totals.pop(source)
        for key in ('billed','net_received','remaining','refund_due'):totals[key]=totals[key] or ZERO
        if state=='due':qs=qs.filter(remaining__gt=0)
        elif state=='credit':qs=qs.filter(refund_due__gt=0)
        elif state=='settled':qs=qs.filter(remaining=0,refund_due=0)
        page_obj=Paginator(qs.order_by('-first_issued_at','-pk'),20).get_page(page)
        return dict(rows=list(page_obj.object_list),page_obj=page_obj,totals=totals,state_filter=state,
                    detail_allowed=b['role']!='HQ',can_request=b['role']=='FRONT_DESK')
