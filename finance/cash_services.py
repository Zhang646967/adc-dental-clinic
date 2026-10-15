"""Two-person synthetic cash ledger. No payment gateway or automatic settlement."""
from datetime import date
from decimal import Decimal
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from accounts.policies import lock_clinic_grant
from accounts.finance_access import lock_finance_write
from adc_core.commands import business_errors
from adc_core.proposals import proposal,read_proposal,workspace_binding
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from care.audit import emit
from care.models import Invoice
from scheduling.models import Visit
from scheduling.coordination import lock_slots
from equipment.models import EquipmentAsset,EquipmentEvent
from equipment.policies import manager_clinic
from finance.cash_models import CashEntry
from finance.cash_selectors import cash_scope,cursor,invoice_balance,event_net
from finance.policies import money

REQUEST='adc.cash.request.v1'
REVIEW='adc.cash.review.v1'
ROLES=('FRONT_DESK','MANAGER')

def _date(value):
    if type(value) is str:
        try:value=date.fromisoformat(value)
        except ValueError as exc:raise RuleError('日期无效。') from exc
    if type(value) is not date or value>timezone.localdate():raise RuleError('事实日期不能在未来。')
    return value

def _reason(value):
    if type(value) is not str or not 1<=len(value.strip())<=500:raise RuleError('请填写1至500字的核对说明。')
    return value.strip()

def _request_payload(data):
    keys={'source_type','source','clinic','version','cursor','kind','amount','occurred_on','reason','reversal'}
    if set(data)!=keys or data['source_type'] not in ('invoice','equipment'):
        raise RuleError('申请确认内容无效。')
    if any(type(data[k]) is not int or not 0<data[k]<2**63 for k in ('source','clinic')):
        raise RuleError('申请来源无效。')
    if data['source_type']=='invoice' and (type(data['version']) is not int or data['version']<=0):
        raise RuleError('账单版本无效。')
    if data['source_type']=='equipment' and data['version'] is not None:raise RuleError('设备来源版本无效。')
    if (type(data['cursor']) is not list or len(data['cursor'])!=3 or
        any(type(v) is not int or v<0 for v in data['cursor'])):raise RuleError('历史校验无效。')
    if data['kind'] not in ('RECEIPT','REFUND','EQUIPMENT_EXPENSE','EXPENSE_REVERSAL'):
        raise RuleError('申请类型无效。')
    if type(data['amount']) is not str or len(data['amount'])>20:raise RuleError('金额无效。')
    if data['reversal'] is not None and (type(data['reversal']) is not int or data['reversal']<=0):
        raise RuleError('冲回来源无效。')

def _request_scope(actor,source_type,clinic_id,lock=False):
    role='FRONT_DESK' if source_type=='invoice' else 'MANAGER'
    b=workspace_binding(actor,(role,))
    if b['clinic']!=clinic_id:raise PermissionDenied('来源不属于当前诊所。')
    if role=='MANAGER':manager_clinic(actor,lock=lock)
    elif lock:lock_clinic_grant(actor,clinic_id)
    else:
        from accounts.policies import require_clinic
        require_clinic(actor,clinic_id)

def _source(source_type,source_id,lock=False):
    if source_type=='invoice':
        initial=Invoice.objects.select_related('visit').get(pk=source_id)
        if lock:
            lock_slots([initial.visit.availability_slot_id])
            Visit.objects.select_for_update().get(pk=initial.visit_id)
            source=Invoice.objects.select_for_update().get(pk=source_id)
        else:source=initial
        rows=CashEntry.objects.filter(invoice_id=source.pk)
        return source,source.visit.clinic_id,rows,source.current_record_version_id
    if source_type=='equipment':
        initial=EquipmentEvent.objects.select_related('asset').get(pk=source_id)
        if lock:
            EquipmentAsset.objects.select_for_update().get(pk=initial.asset_id)
            source=EquipmentEvent.objects.select_for_update().get(pk=source_id)
        else:source=initial
        rows=CashEntry.objects.filter(equipment_event_id=source.pk)
        return source,source.asset.clinic_id,rows,None
    raise RuleError('来源类型无效。')

def _validate(source_type,source,rows,kind,amount,occurred_on,reversal=None,request_id=None):
    if amount<=0:raise RuleError('记账金额必须大于零。')
    if source_type=='invoice':
        if source.current_record_version.state!='PUBLISHED':raise RuleError('只能针对已发布结算单核对。')
        first=timezone.localtime(source.first_issued_at).date()
        if occurred_on<first:raise RuleError('事实日期不能早于开单日期。')
        b=invoice_balance(source)
        if kind not in ('RECEIPT','REFUND'):raise RuleError('结算单类型无效。')
        if kind=='REFUND' and amount>b['net_received']:raise RuleError('退款或冲回不能超过已核实净收款。')
        if kind=='RECEIPT' and reversal is None and amount>b['remaining']:raise RuleError('收款不能超过当前待收金额。')
    else:
        if source.kind not in ('REGISTER','SERVICE') or source.cost is None or source.cost<=0:
            raise RuleError('该设备事件尚无大于零的已登记费用。')
        if occurred_on<source.performed_on:raise RuleError('费用事实日期不能早于设备事件。')
        if kind not in ('EQUIPMENT_EXPENSE','EXPENSE_REVERSAL'):raise RuleError('设备费用类型无效。')
        net=event_net(source.pk)
        if kind=='EQUIPMENT_EXPENSE' and (amount!=source.cost or net!=0):
            raise RuleError('本次应核对整笔事件费用，且尚未有效记账。')
        if kind=='EXPENSE_REVERSAL' and amount>net:raise RuleError('冲回不能超过已记账设备费用。')
    if reversal is not None:
        opposite={'RECEIPT':'REFUND','REFUND':'RECEIPT','EQUIPMENT_EXPENSE':'EXPENSE_REVERSAL'}
        if (reversal.state!='POSTED' or reversal.reversal_of_id is not None or
                kind!=opposite.get(reversal.kind) or amount!=reversal.amount):
            raise RuleError('仅可对正常已记账条目按原金额申请一次冲回。')
        if reversal.reversal_requests.exclude(pk=request_id).filter(state__in=['PENDING','POSTED']).exists():
            raise RuleError('该条目已有待审核或已记账冲回。')
        if occurred_on<reversal.occurred_on:raise RuleError('冲回日期不能早于原条目。')

def prepare_cash(*,actor,source_type,source_id,kind,amount=None,occurred_on,reason,reversal_id=None):
    with reporting_snapshot():
        source,clinic,rows,version=_source(source_type,source_id)
        _request_scope(actor,source_type,clinic)
        reversal=None
        if reversal_id is not None:
            reversal=cash_scope(actor,detail=True).get(pk=reversal_id)
            if (reversal.invoice_id if source_type=='invoice' else reversal.equipment_event_id)!=source_id:
                raise RuleError('冲回来源不匹配。')
            kind={'RECEIPT':'REFUND','REFUND':'RECEIPT','EQUIPMENT_EXPENSE':'EXPENSE_REVERSAL'}.get(reversal.kind)
            amount=reversal.amount
        amount=money(source.cost if source_type=='equipment' and reversal is None else amount)
        day=_date(occurred_on);reason=_reason(reason)
        _validate(source_type,source,rows,kind,amount,day,reversal)
        if source_type=='equipment' and reversal is None and rows.filter(state='PENDING',kind=kind).exists():
            raise RuleError('该设备费用已有待审核申请。')
        data=dict(source_type=source_type,source=source_id,clinic=clinic,version=version,cursor=cursor(rows),
            kind=kind,amount=str(amount),occurred_on=day.isoformat(),reason=reason,reversal=reversal_id)
        return dict(source=source,source_type=source_type,kind=kind,amount=amount,occurred_on=day,reason=reason,
            proposal_token=proposal(actor,REQUEST,ROLES,data))

@business_errors
@transaction.atomic
def confirm_cash_request(*,actor,proposal_token,confirmed,expected_source_type=None,expected_source_id=None,expected_reversal_id=None):
    if confirmed is not True:raise RuleError('请明确确认这份待审核申请。')
    payload=read_proposal(actor,REQUEST,ROLES,proposal_token);data=payload['data']
    _request_payload(data)
    if expected_source_type is not None and (data.get('source_type')!=expected_source_type or data.get('source')!=expected_source_id or data.get('reversal')!=expected_reversal_id):
        raise RuleError('确认内容不属于当前来源，请重新预览。')
    _request_scope(actor,data['source_type'],data['clinic'],lock=True)
    prior=CashEntry.objects.filter(operation_id=payload['operation'],prepared_by_id=actor.pk,clinic_id=data['clinic']).first()
    if prior:return prior,True
    source,clinic,rows,version=_source(data['source_type'],data['source'],lock=True)
    if clinic!=data['clinic'] or version!=data['version'] or cursor(rows)!=data['cursor']:
        raise RuleError('来源账单或记账申请已变化，请重新预览。')
    reversal=rows.get(pk=data['reversal']) if data['reversal'] else None
    amount=money(data['amount']);day=_date(data['occurred_on'])
    _validate(data['source_type'],source,rows,data['kind'],amount,day,reversal)
    if data['source_type']=='equipment' and not reversal and rows.filter(state='PENDING',kind=data['kind']).exists():
        raise RuleError('该设备费用已有待审核申请。')
    fields=dict(invoice=source,based_record_version_id=version) if data['source_type']=='invoice' else dict(equipment_event=source)
    entry=CashEntry.objects.create(operation_id=payload['operation'],clinic_id=clinic,kind=data['kind'],amount=amount,
        occurred_on=day,reason=_reason(data['reason']),reversal_of=reversal,prepared_by=actor,**fields)
    emit(actor,'CASH_REQUESTED',entry,summary={'kind':entry.kind,'source_type':data['source_type']})
    return entry,False

def prepare_review(*,actor,entry_id,decision,reason):
    with reporting_snapshot():
        workspace_binding(actor,('FINANCE',))
        entry=cash_scope(actor,detail=True).get(pk=entry_id)
        if entry.prepared_by_id==actor.pk:raise RuleError('申请人与审核人必须为不同账号。')
        if entry.state!='PENDING':raise RuleError('该条目已经处理。')
        if decision not in ('approve','reject'):raise RuleError('审核决定无效。')
        source_type='invoice' if entry.invoice_id else 'equipment'
        source_id=entry.invoice_id or entry.equipment_event_id
        source,clinic,rows,version=_source(source_type,source_id)
        if decision=='approve':
            if version!=entry.based_record_version_id:raise RuleError('账单已更正，请拒绝旧申请并重新核对。')
            _validate_review(entry,source_type,source,rows)
        data=dict(entry=entry.pk,entry_version=entry.lock_version,source_type=source_type,source=source_id,
            version=version,cursor=cursor(rows),decision=decision,reason=_reason(reason))
        balance=invoice_balance(source) if source_type=='invoice' else dict(known_cost=source.cost,net_equipment_expense=event_net(source.pk))
        return dict(entry=entry,source=source,source_type=source_type,balance=balance,decision=decision,reason=reason,
            proposal_token=proposal(actor,REVIEW,('FINANCE',),data))

def _validate_review(entry,source_type,source,rows):
    _validate(source_type,source,rows,entry.kind,entry.amount,entry.occurred_on,entry.reversal_of,entry.pk)

@business_errors
@transaction.atomic
def confirm_cash_review(*,actor,proposal_token,confirmed,expected_entry_id=None):
    if confirmed is not True:raise RuleError('请明确确认独立审核决定。')
    payload=read_proposal(actor,REVIEW,('FINANCE',),proposal_token);data=payload['data']
    if (set(data)!={'entry','entry_version','source_type','source','version','cursor','decision','reason'} or
        data.get('decision') not in ('approve','reject') or
        type(data.get('entry')) is not int or data['entry']<=0 or
        type(data.get('entry_version')) is not int or data['entry_version']<0 or
        data.get('source_type') not in ('invoice','equipment') or
        type(data.get('source')) is not int or data['source']<=0):
        raise RuleError('审核确认内容无效。')
    if expected_entry_id is not None and data.get('entry')!=expected_entry_id:
        raise RuleError('确认内容不属于当前申请。')
    preview=CashEntry.objects.get(pk=data['entry'])
    users={u.pk:u for u in UserAccount.objects.select_for_update().filter(pk__in=[actor.pk,preview.prepared_by_id]).order_by('pk')}
    lock_finance_write(actor)
    source,clinic,rows,version=_source(data['source_type'],data['source'],lock=True)
    entry=CashEntry.objects.select_for_update().get(pk=data['entry'],clinic_id=clinic)
    if ('invoice' if entry.invoice_id else 'equipment')!=data['source_type'] or (entry.invoice_id or entry.equipment_event_id)!=data['source']:
        raise RuleError('审核来源不匹配。')
    if entry.prepared_by_id==actor.pk:raise RuleError('申请人与审核人必须为不同账号。')
    target='POSTED' if data['decision']=='approve' else 'REJECTED'
    if entry.state!='PENDING':
        if entry.state==target and entry.reviewed_by_id==actor.pk and entry.review_reason==data['reason']:
            return entry,True
        raise RuleError('该条目已有其他审核结果。')
    if entry.lock_version!=data['entry_version']:raise RuleError('申请状态已变化。')
    if target=='POSTED':
        grant=RoleAssignment.objects.select_for_update().filter(user_id=entry.prepared_by_id,is_active=True,
            role='FRONT_DESK' if entry.invoice_id else 'MANAGER',scope_kind='CLINIC',clinic_id=clinic).first()
        if not users[entry.prepared_by_id].is_active or not grant:raise RuleError('原申请人授权已失效，请拒绝申请。')
        if version!=entry.based_record_version_id or version!=data['version'] or cursor(rows)!=data['cursor']:
            raise RuleError('来源账单或记账状态已变化，请重新核对。')
        _validate_review(entry,data['source_type'],source,rows)
    entry.state=target;entry.lock_version=1;entry.reviewed_by=actor;entry.reviewed_at=timezone.now();entry.review_reason=_reason(data['reason'])
    entry.save(update_fields=['state','lock_version','reviewed_by','reviewed_at','review_reason'])
    emit(actor,'CASH_POSTED' if target=='POSTED' else 'CASH_REJECTED',entry,
        summary={'kind':entry.kind,'request_id':entry.pk})
    return entry,False
