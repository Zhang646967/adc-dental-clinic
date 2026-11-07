"""Synthetic inventory and independent current-clinic nursing authority."""
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.utils import timezone

from accounts.policies import lock_clinic_grant, require_clinic
from clinical.dispensing import dispenser
from supplies.models import NursingDuty, StockItem
from workspaces.context import require_active


def enabled():
    return settings.ADC_CLINICAL_SYNTHETIC and settings.ADC_STOCK_REHEARSAL


def require_enabled():
    if not enabled():
        raise Http404('批次与护理演练当前未启用。')


def warehouse(actor, clinic_id, *, lock=False):
    require_enabled()
    role = actor._adc_workspace.role
    if role == 'PHARMACIST':
        dispenser(actor, clinic_id, lock=lock)
        return [StockItem.Kind.DRUG]
    require_active(actor, ('MANAGER',), clinic_id)
    if lock:
        lock_clinic_grant(actor, clinic_id, ('MANAGER',))
    else:
        require_clinic(actor, clinic_id, ('MANAGER',))
    return [StockItem.Kind.MATERIAL, StockItem.Kind.IMPLANT]


def duties(user_id):
    now = timezone.now()
    return NursingDuty.objects.filter(user_id=user_id, revoked_at__isnull=True,
                                      valid_from__lte=now, valid_until__gt=now, clinic__is_active=True)


def nurse(actor, clinic_id, kind, *, lock=False):
    require_enabled()
    require_active(actor, ('NURSE',), clinic_id)
    if lock:
        lock_clinic_grant(actor, clinic_id, ('NURSE',))
    else:
        require_clinic(actor, clinic_id, ('NURSE',))
    rows = duties(actor.pk).filter(clinic_id=clinic_id, kind=kind)
    if lock:
        rows = rows.select_for_update()
    duty = rows.first()
    if not duty:
        raise PermissionDenied('本店没有有效的对应护理职责。')
    return duty
