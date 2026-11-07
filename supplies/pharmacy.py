"""Single transaction bridge from physical pharmacy work to lot evidence."""
from django.db.models import Sum
from django.utils import timezone

from adc_core.rules import RuleError
from supplies.access import enabled
from supplies.models import StockItem, StockLot, StockMovement
from supplies.stock import lot_choices, require_available


def choices(lines):
    if not enabled():
        return StockLot.objects.none()
    items=StockItem.objects.filter(prescription_item_id__in=[line.item_id for line in lines])
    return lot_choices(items).filter(expires_on__gte=timezone.localdate(),recall__isnull=True,available__gt=0)


def administered(issue):
    return issue.administrations.aggregate(total=Sum('quantity',default=0))['total']


def lot_for(visit, line, kind, quantity, *, lot_id=None, issue=None, lock=False):
    if kind=='RETURN':
        existing=StockMovement.objects.filter(dispense=issue,kind='ISSUE').first()
        if existing is None:
            return None  # Historical untracked issue remains untracked.
        lots=StockLot.objects.filter(pk=existing.lot_id)
    elif not enabled():
        if lot_id:
            raise RuleError('批次演练当前未启用，请重新核对发药。')
        return None
    else:
        lots=StockLot.objects.filter(pk=lot_id,item__clinic_id=visit.clinic_id,
                                     item__prescription_item_id=line.item_id,item__unit=line.unit_snapshot)
    if lock:
        lots=lots.select_for_update(of=('self',))
    lot=lots.first()
    if lot is None:
        raise RuleError('请选择与本店药品和计量单位相符的实际批次。')
    if kind=='ISSUE':
        require_available(lot,quantity)
    return lot


def record_lot(movement,lot_id):
    if lot_id:
        return StockMovement.objects.create(
            lot_id=lot_id,kind='ISSUE' if movement.kind=='ISSUE' else 'QUARANTINE',
            quantity=movement.quantity,actor_id=movement.actor_id,dispense=movement,
            reason=movement.reason,operation_id=movement.operation_id,
        )
    return None
