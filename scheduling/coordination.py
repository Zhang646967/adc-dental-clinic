"""Public scheduling lock protocol shared by portal, care and staff commands.
Precondition: active transaction. Lock availability rows in ascending id order
before their Visit rows. This is coordination, not authorization.
"""
from django.db import connection
from adc_core.rules import RuleError
from scheduling.models import AvailabilitySlot

def lock_slots(ids):
    if not connection.in_atomic_block:
        raise RuntimeError("lock_slots requires an active transaction")
    ids=tuple(set(ids))
    result={r.pk:r for r in AvailabilitySlot.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    if len(result)!=len(ids):
        raise RuleError("出诊时段不存在。")
    return result
