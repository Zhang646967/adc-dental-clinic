"""A manager explicitly selects potentially affected slots; GET changes no facts."""
from urllib.parse import urlencode
from django.core.paginator import Paginator
from django.utils import timezone
from adc_core.snapshots import reporting_snapshot
from equipment.models import EquipmentAsset
from equipment.policies import manager_clinic
from equipment.fees import source_id
from scheduling.models import AvailabilitySlot
from scheduling.availability_services import observe_availability_locked
from scheduling.coordination import lock_slots
from django.db import transaction
from coordination.models import CoordinationTask

def maintenance_schedule(actor,asset_id,slot='',page='1'):
    clinic=manager_clinic(actor)
    slot_id=source_id(slot) if slot else None
    with reporting_snapshot():
        asset=EquipmentAsset.objects.select_related('clinic').get(pk=asset_id,clinic_id=clinic)
        now=timezone.now()
        qs=AvailabilitySlot.objects.filter(clinic_id=clinic,is_active=True,ends_at__gt=now).select_related('dentist').order_by('starts_at','pk')
        page_obj=Paginator(qs,20).get_page(page)
        rows=list(page_obj.object_list)
        if slot_id is not None:AvailabilitySlot.objects.get(pk=slot_id,clinic_id=clinic)
    data=dict(asset=asset,rows=rows,page_obj=page_obj,page_query=urlencode(dict(slot=slot)),selected=None)
    if slot_id is not None:
        with transaction.atomic():
            manager_clinic(actor)
            selected=AvailabilitySlot.objects.get(pk=slot_id,clinic_id=clinic)
            locked=lock_slots([selected.pk])[selected.pk]
            snapshot=observe_availability_locked(locked)
        data.update(selected=snapshot.slot,impact=snapshot.impact,blocked=snapshot.blocked,observed_at=snapshot.observed_at,
            task_eligible=snapshot.slot.is_active and snapshot.slot.starts_at>snapshot.observed_at and snapshot.slot.booking_paused)
        with reporting_snapshot():
            task=CoordinationTask.objects.filter(slot_id=slot_id,state__in=['OPEN','IN_PROGRESS','READY']).order_by('-pk').first()
            data['existing_task']=task
    from scheduling.resource_models import ResourceClaim,ResourceCoordination
    data['resource_impacts']=ResourceCoordination.objects.filter(asset=asset).select_related('plan__visit','plan__offer').order_by('-pk')[:100]
    data['resource_binding']=getattr(asset,'scheduling_binding',None)
    manager_clinic(actor)
    return data
