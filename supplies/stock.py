"""Inventory owns its balance and append-only receipt, loss and recall commands."""
from datetime import date

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from accounts.policies import require_writable
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal, workspace_binding
from adc_core.rules import RuleError
from care.audit import emit
from clinical.prescription_payload import required_text
from supplies.access import warehouse
from supplies.models import StockItem, StockLot, StockMovement, StockRecall

CONTRACT = 'adc.stock.c5.v1'
ROLES = ('MANAGER', 'PHARMACIST')
Kind = StockMovement.Kind
INCOMING = (Kind.RECEIPT, Kind.REVERSE_OUT)
OUTGOING = (Kind.ISSUE, Kind.USE, Kind.WASTE, Kind.REVERSE_IN)
REVERSALS = {Kind.RECEIPT: Kind.REVERSE_IN, Kind.WASTE: Kind.REVERSE_OUT}


def lot_choices(items):
    return StockLot.objects.filter(item__in=items).annotate(
        available=Sum('movements__quantity', filter=Q(movements__kind__in=INCOMING), default=0) -
                  Sum('movements__quantity', filter=Q(movements__kind__in=OUTGOING), default=0),
    ).select_related('item','recall').order_by('expires_on','pk')


def available(lot):
    counts = lot.movements.aggregate(
        incoming=Sum('quantity', filter=Q(kind__in=INCOMING), default=0),
        outgoing=Sum('quantity', filter=Q(kind__in=OUTGOING), default=0),
    )
    return counts['incoming']-counts['outgoing']


def require_available(lot, quantity):
    if lot.expires_on < timezone.localdate():
        raise RuleError('该批次已过有效期，请选择其他批次。')
    if StockRecall.objects.filter(lot=lot).exists():
        raise RuleError('该批次已召回，请选择其他批次。')
    if available(lot)<quantity:
        raise RuleError('该批次可用数量不足，请核对库存或选择其他批次。')


def _text(value, label, limit):
    text=required_text(value,label)
    if len(text)>limit:
        raise RuleError(f'{label}最多 {limit} 个字。')
    return text


def _quantity(value):
    if type(value) is not int or not 1<=value<=1000000:
        raise RuleError('请填写 1 至 1000000 的实际数量。')
    return value


def _day(value):
    try:
        day=date.fromisoformat(value)
    except (TypeError,ValueError) as exc:
        raise RuleError('请填写有效的批次到期日期。') from exc
    if day<timezone.localdate():
        raise RuleError('到货批次已过有效期，请按异常到货处置。')
    return day


def _prepare_data(actor, action, fields, *, lock=False):
    bound=workspace_binding(actor,ROLES)
    clinic=bound['clinic']
    kinds=warehouse(actor,clinic,lock=lock)
    items=StockItem.objects.filter(clinic_id=clinic,kind__in=kinds)
    data=dict(action=action,clinic=clinic,reason=required_text(fields.get('reason'),'办理依据'))
    if action=='RECEIPT':
        if lock:
            items=items.select_for_update()
        item=items.filter(pk=fields.get('item')).first()
        if item is None:
            raise RuleError('请选择本店已登记的库存条目。')
        code=_text(fields.get('code'),'批号',60)
        expiry=_day(fields.get('expires_on'))
        reference=_text(fields.get('reference'),'到货凭据',120)
        lots=StockLot.objects.filter(item=item,code=code)
        if lock:
            lots=lots.select_for_update()
        lot=lots.first()
        if lot:
            if lot.expires_on!=expiry:
                raise RuleError('已有同批号记录，效期不同，请核对凭据。')
            require_available(lot,0)
            if lot.movements.filter(kind=Kind.RECEIPT,reference=reference).exists():
                raise RuleError('该凭据已登记此批次，请先查阅入库记录。')
        return dict(data,item=item.pk,code=code,expires_on=expiry.isoformat(),reference=reference,
                    quantity=_quantity(fields.get('quantity')))
    lots=StockLot.objects.filter(item__in=items)
    if lock:
        lots=lots.select_for_update()
    lot=lots.filter(pk=fields.get('lot')).first()
    if lot is None:
        raise RuleError('该批次不在当前门店与岗位范围。')
    data['lot']=lot.pk
    if action=='RECALL':
        if StockRecall.objects.filter(lot=lot).exists():
            raise RuleError('该批次已有召回记录，请查看原记录。')
        return dict(data,reference=_text(fields.get('reference'),'召回依据编号',120))
    if action=='WASTE':
        quantity=_quantity(fields.get('quantity'))
        if available(lot)<quantity:
            raise RuleError('报损数量不能超过现存数量。')
        return dict(data,quantity=quantity)
    if action!='REVERSE':
        raise RuleError('请选择有效的库存办理类型。')
    original=lot.movements.filter(pk=fields.get('movement'),kind__in=REVERSALS).first()
    if original is None or hasattr(original,'reversal'):
        raise RuleError('请选择未冲回的本批次到货或报损记录。')
    if original.kind==Kind.RECEIPT and available(lot)<original.quantity:
        raise RuleError('库存不足以冲回原到货，请核对已经使用的数量。')
    return dict(data,movement=original.pk,quantity=original.quantity,kind=REVERSALS[original.kind])


@sensitive_variables()
def prepare(actor, action, fields):
    data=_prepare_data(actor,action,fields)
    return data,proposal(actor,CONTRACT,ROLES,data)


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm(actor, token, confirmed, *, expected_lot=None, expected_action=None):
    if confirmed is not True:
        raise RuleError('请核对批次与数量后明确确认。')
    p=read_proposal(actor,CONTRACT,ROLES,token)
    data,op=p['data'],p['operation']
    require_writable(actor)
    warehouse(actor,data['clinic'],lock=True)
    kind=data['action']
    if (expected_lot is not None and data.get('lot')!=expected_lot) or (expected_action and kind!=expected_action):
        raise RuleError('本次确认与当前库存入口不一致，请返回原记录。')
    if kind=='RECALL':
        old=StockRecall.objects.filter(operation_id=op,actor=actor,lot__item__clinic_id=data['clinic']).first()
    else:
        old=StockMovement.objects.filter(operation_id=op,actor=actor,lot__item__clinic_id=data['clinic']).first()
    if old:
        return old,True
    actual=_prepare_data(actor,kind,data,lock=True)
    if data!=actual:
        raise RuleError('批次或数量已变化，请重新预览。')
    if kind=='RECEIPT':
        lot,_=StockLot.objects.get_or_create(item_id=data['item'],code=data['code'],
                                            defaults={'expires_on':date.fromisoformat(data['expires_on'])})
    else:
        lot=StockLot.objects.get(pk=data['lot'])
    if kind=='RECALL':
        result=StockRecall.objects.create(lot=lot,actor=actor,reference=data['reference'],reason=data['reason'],operation_id=op)
    else:
        result=StockMovement.objects.create(lot=lot,actor=actor,kind=data.get('kind',kind),quantity=data['quantity'],
            reference=data.get('reference',''),reverses_id=data.get('movement'),reason=data['reason'],operation_id=op)
    emit(actor,'STOCK_'+kind,result,summary={'lot':lot.pk,'quantity':data.get('quantity')})
    return result,False
