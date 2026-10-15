from django.core.paginator import Paginator
from django.db.models import Count,Q,Sum
from django.utils import timezone
from adc_core.snapshots import reporting_snapshot
from adc_core.rules import RuleError
from equipment.models import EquipmentAsset
from equipment.policies import equipment_scope

def scoped_assets(actor):
    clinic=equipment_scope(actor)
    qs=EquipmentAsset.objects.select_related('clinic')
    return qs.filter(clinic_id=clinic) if clinic is not None else qs

def equipment_listing(actor,state='',due='',page='1'):
    if state not in ('','IN_SERVICE','MAINTENANCE','RETIRED') or due not in ('','overdue','unknown'):
        raise RuleError('设备筛选条件无效。')
    with reporting_snapshot():
        qs=scoped_assets(actor);today=timezone.localdate()
        totals=qs.aggregate(total=Count('pk'),maintenance=Count('pk',filter=Q(state='MAINTENANCE')),
            overdue=Count('pk',filter=Q(next_service_due__lte=today)&~Q(state='RETIRED')),
            unknown_due=Count('pk',filter=Q(next_service_due__isnull=True)&~Q(state='RETIRED')),
            known_acquisition=Sum('acquisition_cost'),unknown_cost=Count('pk',filter=Q(acquisition_cost__isnull=True)))
        if state:qs=qs.filter(state=state)
        if due=='overdue':qs=qs.filter(next_service_due__lte=today).exclude(state='RETIRED')
        elif due=='unknown':qs=qs.filter(next_service_due__isnull=True).exclude(state='RETIRED')
        page_obj=Paginator(qs.order_by('asset_code'),20).get_page(page)
        rows=list(page_obj.object_list)
        return dict(rows=rows,page_obj=page_obj,totals=totals,today=today,state_filter=state,due_filter=due)

def equipment_detail(actor,asset_id):
    with reporting_snapshot():
        asset=scoped_assets(actor).get(pk=asset_id)
        events=list(asset.events.select_related('recorded_by').order_by('-sequence')[:50])
        return dict(asset=asset,events=events,history_limited=asset.events.count()>50,today=timezone.localdate())
