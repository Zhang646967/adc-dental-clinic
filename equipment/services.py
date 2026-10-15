"""Explicit manager commands; no automatic scheduling or expense posting."""
from datetime import date
from functools import wraps
from django.db import transaction, IntegrityError
from adc_core.rules import RuleError
from adc_core.commands import assert_revision
from adc_core.proposals import proposal,read_proposal
from adc_core.snapshots import reporting_snapshot
from care.audit import emit
from equipment.models import EquipmentAsset,EquipmentEvent,CATEGORIES
from equipment.policies import manager_clinic
from finance.policies import money
from django.utils import timezone

CONTRACT='adc.equipment.change.v1'
def _date(value):
    if type(value) is date:return value
    if type(value) is str:
        try:return date.fromisoformat(value)
        except ValueError as exc:raise RuleError('日期格式无效。') from exc
    raise RuleError('日期格式无效。')

def _cost(value):
    return None if value is None else money(value)

def _text(value,max_length):
    if type(value) is not str or not 1<=len(value.strip())<=max_length:
        raise RuleError('请填写完整且未超长的设备资料。')
    return value.strip()

def _registration(data):
    import re
    code=_text(data['asset_code'],40).upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9_-]{1,39}',code):raise RuleError('设备编号格式无效。')
    acquired=_date(data['acquired_on'])
    if acquired>timezone.localdate():raise RuleError('接收日期不能在未来。')
    due=_date(data['next_service_due']) if data.get('next_service_due') else None
    if due and due<acquired:raise RuleError('保养到期日不能早于设备接收日。')
    if data['category'] not in dict(CATEGORIES):raise RuleError('设备类别无效。')
    return dict(asset_code=code,name=_text(data['name'],120),category=data['category'],
        location=_text(data['location'],120),acquired_on=acquired,
        acquisition_cost=_cost(data.get('acquisition_cost')),next_service_due=due,note=_text(data['note'],500))

def _serial(data):
    return {k:v.isoformat() if isinstance(v,date) else str(v) if k in ('cost','acquisition_cost') and v is not None else v for k,v in data.items()}

def equipment_errors(fn):
    @wraps(fn)
    def wrapped(*args,**kwargs):
        try:return fn(*args,**kwargs)
        except IntegrityError as exc:
            if getattr(getattr(exc.__cause__,'diag',None),'constraint_name',None)=='equipment_code_unique':
                raise RuleError('设备编号已被使用，请核对后重新登记。') from exc
            raise
    return wrapped

def prepare_registration(*,actor,**data):
    with reporting_snapshot():
        clinic=manager_clinic(actor)
        clean=_registration(data)
        if EquipmentAsset.objects.filter(asset_code=clean['asset_code']).exists():raise RuleError('设备编号已被使用。')
        payload=dict(action='register',clinic=clinic,fields=_serial(clean))
        return dict(fields=clean,proposal_token=proposal(actor,CONTRACT,('MANAGER',),payload),title='核对设备登记')

def _change(asset,data):
    kind=data['kind']
    next_state={'MAINTENANCE':'MAINTENANCE','SERVICE':'IN_SERVICE','RETIRE':'RETIRED'}.get(kind)
    if not next_state or asset.state=='RETIRED' or (kind=='MAINTENANCE' and asset.state!='IN_SERVICE'):
        raise RuleError('当前设备状态不能执行此操作。')
    performed=_date(data['performed_on'])
    latest=asset.events.order_by('-sequence').first()
    if performed>timezone.localdate() or performed<(latest.performed_on if latest else asset.acquired_on):
        raise RuleError('事实日期不能在未来或早于已有设备历史。')
    cost=_cost(data.get('cost'))
    due=_date(data['next_service_due']) if data.get('next_service_due') else None
    if kind!='SERVICE' and (cost is not None or due is not None):raise RuleError('仅保养完成时登记费用和下次到期日。')
    if due and due<=performed:raise RuleError('下次保养日必须晚于本次完成日。')
    return dict(kind=kind,previous_state=asset.state,next_state=next_state,performed_on=performed,
        cost=cost,next_service_due=due if kind=='SERVICE' else None if kind=='RETIRE' else asset.next_service_due,
        note=_text(data['note'],500))

def prepare_change(*,actor,asset_id,**data):
    with reporting_snapshot():
        clinic=manager_clinic(actor)
        asset=EquipmentAsset.objects.get(pk=asset_id,clinic_id=clinic)
        clean=_change(asset,data)
        payload=dict(action='change',clinic=clinic,asset=asset.pk,version=asset.lock_version,fields=_serial(clean))
        return dict(asset=asset,fields=clean,proposal_token=proposal(actor,CONTRACT,('MANAGER',),payload),title='核对设备状态与保养记录')

@equipment_errors
@transaction.atomic
def confirm_equipment(*,actor,proposal_token,confirmed,expected_action=None,expected_asset_id=None):
    if confirmed is not True:raise RuleError('请核对后明确确认。')
    payload=read_proposal(actor,CONTRACT,('MANAGER',),proposal_token)
    data=payload['data'];clinic=manager_clinic(actor,lock=True)
    action=data.get('action')
    keys={'action','clinic','fields'} if action=='register' else {'action','clinic','asset','version','fields'}
    if (action not in ('register','change') or set(data)!=keys or type(data.get('fields')) is not dict or
        type(data.get('clinic')) is not int or
        (action=='change' and (type(data.get('asset')) is not int or data['asset']<=0 or
                              type(data.get('version')) is not int or data['version']<0))):
        raise RuleError('设备确认内容无效。')
    field_keys=({'asset_code','name','category','location','acquired_on','acquisition_cost','next_service_due','note'}
        if action=='register' else {'kind','previous_state','next_state','performed_on','cost','next_service_due','note'})
    if set(data['fields'])!=field_keys:raise RuleError('设备字段范围无效。')
    if expected_action is not None and (data.get('action')!=expected_action or
            (expected_action=='change' and data.get('asset')!=expected_asset_id)):
        raise RuleError('确认内容不属于当前设备操作，请重新预览。')
    if data.get('clinic')!=clinic:raise RuleError('当前诊所已变化。')
    prior=EquipmentEvent.objects.filter(operation_id=payload['operation'],recorded_by_id=actor.pk,asset__clinic_id=clinic).first()
    if prior:
        return EquipmentAsset.objects.get(pk=prior.asset_id),True
    if data.get('action')=='register':
        clean=_registration(data['fields']);note=clean.pop('note')
        if EquipmentAsset.objects.filter(asset_code=clean['asset_code']).exists():raise RuleError('设备编号已被使用。')
        asset=EquipmentAsset.objects.create(clinic_id=clinic,registered_by=actor,**clean)
        event=EquipmentEvent.objects.create(asset=asset,operation_id=payload['operation'],sequence=0,kind='REGISTER',
            previous_state='',next_state=asset.state,performed_on=asset.acquired_on,next_service_due=asset.next_service_due,
            cost=asset.acquisition_cost,note=note,recorded_by=actor)
    elif data.get('action')=='change':
        asset=EquipmentAsset.objects.select_for_update().get(pk=data['asset'],clinic_id=clinic)
        assert_revision(asset,data['version'])
        fields={k:v for k,v in data['fields'].items() if k not in ('previous_state','next_state')}
        if fields['kind']!='SERVICE':
            fields['cost']=None;fields['next_service_due']=None
        clean=_change(asset,fields)
        if clean['previous_state']!=data['fields']['previous_state'] or clean['next_state']!=data['fields']['next_state']:
            raise RuleError('设备状态已变化，请重新预览。')
        asset.state=clean['next_state'];asset.next_service_due=clean['next_service_due'];asset.lock_version+=1
        asset.save(update_fields=['state','next_service_due','lock_version'])
        event=EquipmentEvent.objects.create(asset=asset,operation_id=payload['operation'],sequence=asset.lock_version,recorded_by=actor,**clean)
    else:raise RuleError('未知设备操作。')
    emit(actor,'EQUIPMENT_RECORDED',event,summary={'asset_id':asset.pk,'sequence':asset.lock_version,'kind':event.kind})
    return asset,False
