"""Append-only source-cost supplementation; independent from cash and lifecycle."""
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from accounts.finance_access import lock_finance_write
from adc_core.commands import business_errors
from adc_core.proposals import workspace_binding,proposal,read_proposal
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from care.audit import emit
from equipment.models import EquipmentAsset,EquipmentEvent,EquipmentCostAmendment
from equipment.policies import equipment_scope,manager_clinic
from finance.cash_models import CashEntry
from finance.cash_selectors import cursor,event_net
from finance.policies import money

REQUEST='adc.equipment.cost.request.v1'
REVIEW='adc.equipment.cost.review.v1'

def cost_id(value):
    if type(value) is not int or not 0<value<2**63:raise RuleError('费用来源编号无效。')
    return value

def effective_cost(event):
    current=event.cost_amendments.filter(state='APPROVED').order_by('-pk').first()
    return (current.proposed_cost,current.pk) if current else (event.cost,None)

def scoped_events(actor):
    clinic=equipment_scope(actor)
    qs=EquipmentEvent.objects.filter(kind__in=['REGISTER','SERVICE']).select_related('asset__clinic')
    return qs.filter(asset__clinic_id=clinic) if clinic is not None else qs

def _reason(value):
    if type(value) is not str or not 1<=len(value.strip())<=500:raise RuleError('请填写1至500字的原始凭据与更正依据；勿填患者资料。')
    return value.strip()

def _event(event_id,lock=False):
    initial=EquipmentEvent.objects.select_related('asset').get(pk=cost_id(event_id),kind__in=['REGISTER','SERVICE'])
    if lock:
        EquipmentAsset.objects.select_for_update().get(pk=initial.asset_id)
        return EquipmentEvent.objects.select_for_update().get(pk=cost_id(event_id))
    return initial

def _clear_cash(event):
    if CashEntry.objects.filter(equipment_event=event,state='PENDING').exists():
        raise RuleError('该事件仍有待审核记账申请，请先独立处理，不能以更正绕过审核。')
    if event_net(event.pk)!=0:
        raise RuleError('该事件仍有已记账净费用，请先申请原金额冲回并经独立审核。')

def _cursor(event):
    return dict(amendments=cursor(event.cost_amendments.all()),cash=cursor(event.cash_entries.all()))

def prepare_cost(*,actor,event_id,proposed_cost,reason):
    with reporting_snapshot():
        clinic=manager_clinic(actor)
        event=scoped_events(actor).get(pk=cost_id(event_id))
        old,based=effective_cost(event);new=money(proposed_cost)
        if new==old:raise RuleError('新费用与当前核对费用相同，无需重复申请。')
        _clear_cash(event)
        if event.cost_amendments.filter(state='PENDING').exists():raise RuleError('该事件已有待审核费用更正，请先核对历史。')
        data=dict(event=event.pk,clinic=clinic,based=based,previous=None if old is None else str(old),
            proposed=str(new),reason=_reason(reason),cursor=_cursor(event))
        return dict(event=event,previous_cost=old,proposed_cost=new,reason=data['reason'],
            proposal_token=proposal(actor,REQUEST,('MANAGER',),data))

def _payload(data):
    if (set(data)!={'event','clinic','based','previous','proposed','reason','cursor'} or
        any(type(data[k]) is not int or not 0<data[k]<2**63 for k in ('event','clinic')) or
        (data['based'] is not None and (type(data['based']) is not int or data['based']<=0)) or
        any(data[k] is not None and (type(data[k]) is not str or len(data[k])>20) for k in ('previous','proposed')) or
        data['proposed'] is None or type(data['cursor']) is not dict):raise RuleError('费用更正确认内容无效。')

@business_errors
@transaction.atomic
def confirm_cost(*,actor,proposal_token,confirmed,expected_event_id=None):
    if confirmed is not True:raise RuleError('请明确确认申请。')
    payload=read_proposal(actor,REQUEST,('MANAGER',),proposal_token);data=payload['data'];_payload(data)
    clinic=manager_clinic(actor,lock=True)
    if clinic!=data['clinic'] or (expected_event_id is not None and expected_event_id!=data['event']):raise RuleError('费用更正来源或诊所已变化。')
    prior=EquipmentCostAmendment.objects.filter(operation_id=payload['operation'],prepared_by=actor,event_id=data['event']).first()
    if prior:return prior,True
    event=_event(data['event'],lock=True)
    if event.asset.clinic_id!=clinic:raise PermissionDenied('来源不属于当前诊所。')
    old,based=effective_cost(event);new=money(data['proposed'])
    previous=None if data['previous'] is None else money(data['previous'])
    if based!=data['based'] or old!=previous or _cursor(event)!=data['cursor']:raise RuleError('费用依据或申请历史已变化，请重新核对。')
    _clear_cash(event)
    if old==new or event.cost_amendments.filter(state='PENDING').exists():raise RuleError('费用相同或已有待审核更正。')
    row=EquipmentCostAmendment.objects.create(event=event,operation_id=payload['operation'],based_amendment_id=based,
        previous_cost=old,proposed_cost=new,reason=_reason(data['reason']),prepared_by=actor)
    emit(actor,'EQUIPMENT_COST_REQUESTED',row,summary={'event_id':event.pk})
    return row,False

def cost_blocker(row,event=None):
    if row.state!='PENDING':return '该费用更正已经处理。'
    if not UserAccount.objects.filter(pk=row.prepared_by_id,is_active=True).exists() or not RoleAssignment.objects.filter(
        user_id=row.prepared_by_id,role='MANAGER',scope_kind='CLINIC',clinic_id=row.event.asset.clinic_id,is_active=True).exists():
        return '原申请人授权已失效，可拒绝并保留原申请。'
    event=event or row.event
    if not event.asset.clinic.is_active:return '来源诊所已停用，请拒绝并核对。'
    old,based=effective_cost(event)
    if old!=row.previous_cost or based!=row.based_amendment_id:return '当前费用依据已变化，请拒绝并重新核对。'
    try:_clear_cash(event)
    except RuleError as exc:return str(exc)
    return ''

def prepare_cost_review(*,actor,amendment_id,decision,reason):
    with reporting_snapshot():
        workspace_binding(actor,('FINANCE',));equipment_scope(actor)
        row=EquipmentCostAmendment.objects.select_related('event__asset__clinic','prepared_by').get(pk=cost_id(amendment_id))
        if row.prepared_by_id==actor.pk:raise RuleError('申请人与审核人必须为不同账号。')
        if row.state!='PENDING' or decision not in ('approve','reject'):raise RuleError('审核状态或决定无效。')
        if decision=='approve':
            blocker=cost_blocker(row)
            if blocker:raise RuleError(blocker)
        data=dict(amendment=row.pk,version=row.lock_version,decision=decision,reason=_reason(reason),cursor=_cursor(row.event))
        return dict(amendment=row,decision=decision,reason=data['reason'],proposal_token=proposal(actor,REVIEW,('FINANCE',),data))

@business_errors
@transaction.atomic
def confirm_cost_review(*,actor,proposal_token,confirmed,expected_amendment_id=None):
    if confirmed is not True:raise RuleError('请明确确认独立审核决定。')
    payload=read_proposal(actor,REVIEW,('FINANCE',),proposal_token);data=payload['data']
    if (set(data)!={'amendment','version','decision','reason','cursor'} or type(data['amendment']) is not int or not 0<data['amendment']<2**63 or
        type(data['version']) is not int or data['version']!=0 or data['decision'] not in ('approve','reject')):raise RuleError('审核内容无效。')
    if expected_amendment_id is not None and expected_amendment_id!=data['amendment']:raise RuleError('审核来源不匹配。')
    initial=EquipmentCostAmendment.objects.get(pk=data['amendment'])
    users={u.pk:u for u in UserAccount.objects.select_for_update().filter(pk__in=[actor.pk,initial.prepared_by_id]).order_by('pk')}
    lock_finance_write(actor)
    event=_event(initial.event_id,lock=True)
    row=EquipmentCostAmendment.objects.select_for_update().get(pk=initial.pk)
    if row.prepared_by_id==actor.pk:raise RuleError('申请人与审核人必须为不同账号。')
    target='APPROVED' if data['decision']=='approve' else 'REJECTED'
    reason=_reason(data['reason'])
    if row.state!='PENDING':
        if row.state==target and row.reviewed_by_id==actor.pk and row.review_reason==reason:return row,True
        raise RuleError('已有其他审核结果，请查看历史。')
    if target=='APPROVED':
        grant=RoleAssignment.objects.select_for_update().filter(user_id=row.prepared_by_id,is_active=True,
            role='MANAGER',scope_kind='CLINIC',clinic_id=event.asset.clinic_id).first()
        if not users[row.prepared_by_id].is_active or not grant:raise RuleError('原申请人授权已失效。')
        if _cursor(event)!=data['cursor']:raise RuleError('费用或记账历史已变化，请重新预览。')
        blocker=cost_blocker(row,event)
        if blocker:raise RuleError(blocker)
    row.state=target;row.lock_version=1;row.reviewed_by=actor;row.reviewed_at=timezone.now();row.review_reason=reason
    row.save(update_fields=['state','lock_version','reviewed_by','reviewed_at','review_reason'])
    emit(actor,'EQUIPMENT_COST_APPROVED' if target=='APPROVED' else 'EQUIPMENT_COST_REJECTED',row,summary={'event_id':event.pk})
    return row,False

def cost_history(actor,event_id,page='1'):
    with reporting_snapshot():
        event=scoped_events(actor).get(pk=cost_id(event_id))
        current,based=effective_cost(event)
        rows=event.cost_amendments.select_related('prepared_by','reviewed_by').order_by('-pk')
        page_obj=Paginator(rows,20).get_page(page)
        history=list(page_obj.object_list)
        pending=rows.filter(state='PENDING').exists()
        net=event_net(event.pk);pending_cash=event.cash_entries.filter(state='PENDING').exists()
        for row in history:row.approval_blocker=cost_blocker(row,event) if row.state=='PENDING' else ''
        return dict(event=event,current_cost=current,based_amendment_id=based,amendments=history,page_obj=page_obj,
            pending_cost=pending,pending_cash=pending_cash,net_expense=net,
            can_prepare=actor._adc_workspace.role=='MANAGER' and not pending and not pending_cash and net==0)
