"""Manager-owned maintenance with another manager's explicit acceptance."""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count,Max,Sum
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from adc_core.commands import business_errors,assert_revision
from adc_core.proposals import proposal,read_proposal
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from care.audit import emit
from equipment.models import EquipmentAsset,EquipmentEvent
from equipment.maintenance_models import MaintenanceOrder,MaintenanceAction,ACTIVE,ACTIONS
from equipment.policies import manager_clinic,equipment_scope
from equipment.services import _date,_text,_cost,_change

CONTRACT='adc.maintenance.action.v1'

def order_scope(actor):
    clinic=equipment_scope(actor)
    qs=MaintenanceOrder.objects.select_related('asset__clinic','maintenance_event','created_by','assigned_to','submitted_by','reviewed_by','service_event')
    return qs.filter(asset__clinic_id=clinic) if clinic is not None else qs

def owners(clinic):
    return UserAccount.objects.filter(is_active=True,role_assignments__is_active=True,role_assignments__role='MANAGER',role_assignments__scope_kind='CLINIC',role_assignments__clinic_id=clinic).distinct().order_by('username')

def _owner(owner_id,clinic,lock=False):
    if type(owner_id) is not int or not 0<owner_id<2**63:raise RuleError('请选择当前诊所的有效主管负责人。')
    grants=RoleAssignment.objects.filter(user_id=owner_id,is_active=True,role='MANAGER',scope_kind='CLINIC',clinic_id=clinic)
    if lock:grants=grants.select_for_update()
    if not UserAccount.objects.filter(pk=owner_id,is_active=True).exists() or not grants.exists():raise RuleError('负责人账号或本店主管授权已失效，请调整负责人。')
    return owner_id

def _cursor(asset):
    x=asset.maintenance_orders.aggregate(n=Count('pk'),last=Max('pk'),v=Sum('lock_version'))
    return [x['n'],x['last'] or 0,x['v'] or 0]

def snapshot(row):
    return dict(state=row.state,owner=row.assigned_to_id,due=row.due_on.isoformat(),
        performed=row.performed_on.isoformat() if row.performed_on else None,
        cost=format(row.cost,'.2f') if row.cost is not None else None,
        next_due=row.next_service_due.isoformat() if row.next_service_due else None,
        evidence=row.completion_note,schedule_checked=row.schedule_checked,submitter=row.submitted_by_id,
        reviewer=row.reviewed_by_id,service_event=row.service_event_id)

def _source(asset,row=None):
    latest=asset.events.order_by('-sequence').first()
    if asset.state!='MAINTENANCE' or not latest or latest.kind!='MAINTENANCE' or latest.sequence!=asset.lock_version:
        raise RuleError('请先登记设备送修；工单只能针对当前维修状态办理。')
    if row and row.maintenance_event_id!=latest.pk:raise RuleError('维修来源已变化，请核对设备历史。')
    return latest

def _fields(action,fields):
    expected={'OPEN':{'owner','due','issue'},'ASSIGN':{'owner','due'},'SUBMIT':{'performed','cost','next_due','evidence','schedule_checked'}}.get(action,set())
    if type(fields) is not dict or set(fields)!=expected:raise RuleError('工单字段范围无效。')
    clean=dict(fields)
    if action in ('OPEN','ASSIGN'):
        if type(clean['owner']) is not int or not 0<clean['owner']<2**63:raise RuleError('负责人无效。')
        clean['due']=_date(clean['due'])
        if clean['due']<timezone.localdate():raise RuleError('新办理期限不能早于今天。')
    if action=='OPEN':clean['issue']=_text(clean['issue'],500)
    if action=='SUBMIT':
        clean['performed']=_date(clean['performed']);clean['cost']=_cost(clean['cost'])
        if clean['cost']==0:clean['cost']=abs(clean['cost'])
        clean['next_due']=_date(clean['next_due']) if clean['next_due'] else None
        clean['evidence']=_text(clean['evidence'],500)
        if clean['schedule_checked'] is not True:raise RuleError('请明确确认已核对出诊影响和后续协调事项。')
    return clean

def _validate(actor,asset,row,action,fields,lock=False):
    if action not in dict(ACTIONS):raise RuleError('工单操作无效。')
    source=_source(asset,row)
    if action=='OPEN':
        if row or asset.maintenance_orders.filter(state__in=ACTIVE).exists():raise RuleError('该设备已有未完成工单，请进入原工单办理。')
        _owner(fields['owner'],asset.clinic_id,lock);return source
    if row is None or row.state not in ACTIVE:raise RuleError('工单已结束，保留原记录；需要时从新的维修事实办理。')
    expected={'START':('ASSIGNED',),'ASSIGN':('ASSIGNED','IN_PROGRESS'),'SUBMIT':('IN_PROGRESS',),'RETURN':('READY',),'WITHDRAW':('READY',),'APPROVE':('READY',),'CANCEL':('ASSIGNED','IN_PROGRESS')}
    if row.state not in expected.get(action,()):raise RuleError('当前工单状态不能执行此操作。')
    if action in ('START','SUBMIT','WITHDRAW') and row.assigned_to_id!=actor.pk:raise RuleError('仅当前负责人可以执行本操作。')
    if action in ('RETURN','APPROVE') and actor.pk in (row.assigned_to_id,row.submitted_by_id):raise RuleError('维修提交人与验收人必须为不同账号。')
    if action=='ASSIGN':
        _owner(fields['owner'],asset.clinic_id,lock)
        if fields['owner']==row.assigned_to_id and fields['due']==row.due_on:raise RuleError('负责人和期限均未变化。')
    if action in ('SUBMIT','APPROVE'):
        _owner(row.assigned_to_id,asset.clinic_id,lock)
        data=fields if action=='SUBMIT' else dict(performed=row.performed_on,cost=row.cost,next_due=row.next_service_due,evidence=row.completion_note)
        _change(asset,dict(kind='SERVICE',performed_on=data['performed'],cost=data['cost'],next_service_due=data['next_due'],note=data['evidence']))
    return source

def _serialized(fields):
    return {k:(v.isoformat() if k in ('due','performed','next_due') and v else format(v,'.2f') if k=='cost' and v is not None else v) for k,v in fields.items()}

def prepare_maintenance(*,actor,asset_id,action,fields,note,order_id=None):
    with reporting_snapshot():
        clinic=manager_clinic(actor);asset=EquipmentAsset.objects.get(pk=asset_id,clinic_id=clinic)
        row=MaintenanceOrder.objects.get(pk=order_id,asset=asset) if order_id else None
        clean=_fields(action,fields);note=_text(note,500);_validate(actor,asset,row,action,clean)
        data=dict(clinic=clinic,asset=asset.pk,asset_version=asset.lock_version,order=row.pk if row else None,
            version=row.lock_version if row else None,owner=row.assigned_to_id if row else None,
            cursor=_cursor(asset),action=action,fields=_serialized(clean),note=note)
        return dict(asset=asset,row=row,action=action,fields=clean,note=note,
            proposal_token=proposal(actor,CONTRACT,('MANAGER',),data))

def _payload(data):
    if type(data) is not dict or set(data)!={'clinic','asset','asset_version','order','version','owner','cursor','action','fields','note'}:raise RuleError('工单确认内容无效。')
    for k in ('clinic','asset'):
        if type(data[k]) is not int or not 0<data[k]<2**63:raise RuleError('工单来源无效。')
    if type(data['asset_version']) is not int or data['asset_version']<0:raise RuleError('设备版本无效。')
    if data['action']=='OPEN':
        if any(data[k] is not None for k in ('order','version','owner')):raise RuleError('新工单来源无效。')
    elif any(type(data[k]) is not int or data[k]<(0 if k=='version' else 1) or data[k]>=2**63 for k in ('order','version','owner')):raise RuleError('工单版本无效。')
    if type(data['cursor']) is not list or len(data['cursor'])!=3 or any(type(v) is not int or v<0 for v in data['cursor']):raise RuleError('工单历史校验无效。')
    return _fields(data['action'],data['fields'])

def _clear_report(row):
    row.performed_on=row.cost=row.next_service_due=row.submitted_by_id=row.submitted_at=None
    row.completion_note='';row.schedule_checked=False

@business_errors
@transaction.atomic
def confirm_maintenance(*,actor,proposal_token,confirmed,expected_asset_id=None,expected_order_id=None,expected_action=None):
    if confirmed is not True:raise RuleError('请核对后明确确认本次维护操作。')
    payload=read_proposal(actor,CONTRACT,('MANAGER',),proposal_token);data=payload['data'];clean=_payload(data);note=_text(data['note'],500)
    if expected_asset_id is not None and (data['asset']!=expected_asset_id or data['order']!=expected_order_id or data['action']!=expected_action):raise RuleError('确认内容不属于当前工单操作。')
    user_ids={actor.pk,data['owner'],clean.get('owner')}-{None}
    list(UserAccount.objects.select_for_update().filter(pk__in=user_ids).order_by('pk'))
    clinic=manager_clinic(actor,lock=True)
    if clinic!=data['clinic']:raise PermissionDenied
    asset=EquipmentAsset.objects.select_for_update().get(pk=data['asset'],clinic_id=clinic)
    prior=MaintenanceAction.objects.filter(operation_id=payload['operation'],actor=actor,order__asset=asset).first()
    if prior:return MaintenanceOrder.objects.get(pk=prior.order_id),True
    assert_revision(asset,data['asset_version'])
    row=MaintenanceOrder.objects.select_for_update().get(pk=data['order'],asset=asset) if data['order'] else None
    if row:
        assert_revision(row,data['version'])
        if row.assigned_to_id!=data['owner']:raise RuleError('负责人已变化，请重新核对。')
    if _cursor(asset)!=data['cursor']:raise RuleError('工单历史已变化，请重新预览。')
    action=data['action'];source=_validate(actor,asset,row,action,clean,lock=True)
    if action=='OPEN':
        row=MaintenanceOrder.objects.create(asset=asset,maintenance_event=source,issue=clean['issue'],created_by=actor,assigned_to_id=clean['owner'],due_on=clean['due'])
    else:
        if action=='START':row.state='IN_PROGRESS'
        elif action=='ASSIGN':row.assigned_to_id=clean['owner'];row.due_on=clean['due'];row.state='ASSIGNED'
        elif action=='SUBMIT':
            row.performed_on=clean['performed'];row.cost=clean['cost'];row.next_service_due=clean['next_due'];row.completion_note=clean['evidence'];row.schedule_checked=True
            row.submitted_by=actor;row.submitted_at=timezone.now();row.state='READY'
        elif action in ('RETURN','WITHDRAW'):row.state='IN_PROGRESS';_clear_report(row)
        elif action=='CANCEL':row.state='CANCELLED'
        elif action=='APPROVE':
            event_fields=_change(asset,dict(kind='SERVICE',performed_on=row.performed_on,cost=row.cost,next_service_due=row.next_service_due,note=row.completion_note))
            asset.state='IN_SERVICE';asset.next_service_due=row.next_service_due;asset.lock_version+=1
            asset.save(update_fields=['state','next_service_due','lock_version'])
            event=EquipmentEvent.objects.create(asset=asset,operation_id=payload['operation'],sequence=asset.lock_version,recorded_by=actor,**event_fields)
            row.state='CLOSED';row.reviewed_by=actor;row.reviewed_at=timezone.now();row.review_reason=note;row.service_event=event
            emit(actor,'EQUIPMENT_RECORDED',event,summary={'asset_id':asset.pk,'sequence':asset.lock_version,'kind':event.kind,'maintenance_order':row.pk})
        row.lock_version+=1;row.save()
    step=MaintenanceAction.objects.create(order=row,operation_id=payload['operation'],sequence=row.lock_version,action=action,actor=actor,note=note,snapshot=snapshot(row))
    emit(actor,'MAINTENANCE_ACTION',step,summary={'order':row.pk,'action':action,'sequence':row.lock_version})
    return row,False

def available_actions(actor,row):
    if getattr(getattr(actor,'_adc_workspace',None),'role',None)!='MANAGER':return []
    result=[]
    candidates={'ASSIGNED':['START','ASSIGN','CANCEL'],'IN_PROGRESS':['SUBMIT','ASSIGN','CANCEL'],'READY':['APPROVE','RETURN','WITHDRAW']}.get(row.state,[])
    for action in candidates:
        if action in ('START','SUBMIT','WITHDRAW') and row.assigned_to_id!=actor.pk:continue
        if action in ('APPROVE','RETURN') and actor.pk in (row.assigned_to_id,row.submitted_by_id):continue
        result.append((action,dict(ACTIONS)[action]))
    return result
