"""Validate a bounded medication list against the current clinic catalogue."""
from decimal import Decimal, InvalidOperation
from adc_core.rules import RuleError
from clinical.prescription_models import PrescriptionCatalogueItem

MAX_ITEMS = 5


def catalogue_for(clinic_id):
    return PrescriptionCatalogueItem.objects.filter(clinic_id=clinic_id, is_active=True)


def required_text(value, label):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 500:
        raise RuleError(f'{label}须填写 1 至 500 字。')
    return value.strip()


def normalize_items(clinic_id, entries, *, lock=False):
    if not 1 <= len(entries) <= MAX_ITEMS:
        raise RuleError(f'请选择 1 至 {MAX_ITEMS} 个目录条目。')
    ids = [entry['item_id'] for entry in entries]
    if len(set(ids)) != len(ids):
        raise RuleError('同一个目录条目只能填写一行。')
    rows = catalogue_for(clinic_id).filter(pk__in=ids).order_by('pk')
    if lock:
        rows = rows.select_for_update(of=('self',))
    catalogue = {item.pk: item for item in rows}
    items = []
    for entry in entries:
        item = catalogue.get(entry['item_id'])
        if item is None:
            raise RuleError('有目录条目已停用或不属于当前诊所，请重新选择。')
        try:
            dose = Decimal(entry['dose'])
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise RuleError('请填写有效的剂量。') from exc
        if not dose.is_finite() or not 0 < dose <= 9999 or dose.as_tuple().exponent < -3:
            raise RuleError('请填写大于零、最多三位小数的剂量。')
        for name, ceiling, label in [('frequency', 24, '每日次数'), ('days', 90, '疗程天数'), ('quantity', 9999, '调配数量')]:
            if type(entry[name]) is not int or not 1 <= entry[name] <= ceiling:
                raise RuleError(f'{label}超出演练表单允许的范围。')
        items.append(dict(
            item_id=item.pk, code=item.code, name=item.name, strength=item.strength,
            route=item.route, route_label=item.get_route_display(), dose_unit=item.dose_unit,
            quantity_unit=item.quantity_unit, dose=format(dose.normalize(), 'f'),
            frequency=entry['frequency'], days=entry['days'], quantity=entry['quantity'],
        ))
    return items
