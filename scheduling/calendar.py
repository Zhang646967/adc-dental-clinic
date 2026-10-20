"""Front-desk day/week observations from the existing scheduling facts."""
from collections import defaultdict
from datetime import timedelta
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
from adc_core.rules import OCCUPYING_STATUSES
from coordination.models import WaitOffer,CoordinationTask
from registry.models import Dentist
from scheduling.models import AvailabilitySlot,Visit
from scheduling.resource_models import BookingService,ResourceClaim
from scheduling.resources import ResourceCalendar
from scheduling.worklists import day_bounds
from scheduling.availability_services import require_availability_actor

STEP=timedelta(minutes=15)

def free_intervals(start,end,occupied):
    """Subtract a union of half-open intervals; overlapping promises count once."""
    result=[];cursor=start
    for a,b in sorted(occupied):
        a=max(a,start);b=min(b,end)
        if b<=cursor or a>=end:continue
        if a>cursor:result.append((cursor,a))
        cursor=max(cursor,b)
    if cursor<end:result.append((cursor,end))
    return result

def doctor_choices(clinic_id):
    return Dentist.objects.filter(pk__in=AvailabilitySlot.objects.filter(clinic_id=clinic_id).values('dentist_id')).order_by('employee_no')

def calendar_context(*,actor,day,mode='week',dentist_id=None,service=None,page=1):
    ctx=require_availability_actor(actor);clinic=ctx.clinic_id;now=timezone.now()
    first=day-timedelta(days=day.weekday()) if mode=='week' else day
    count=7 if mode=='week' else 1
    begin,_=day_bounds(first);_,finish=day_bounds(first+timedelta(days=count-1))
    qs=AvailabilitySlot.objects.filter(clinic_id=clinic,starts_at__lt=finish,ends_at__gt=begin).select_related('dentist','clinic')
    if dentist_id:qs=qs.filter(dentist_id=dentist_id)
    pages=Paginator(qs.order_by('starts_at','dentist__employee_no','pk'),28);current=pages.get_page(page);slots=list(current)
    ids=[s.pk for s in slots];visits=defaultdict(list);offers=defaultdict(list);tasks={}
    for v in Visit.objects.filter(availability_slot_id__in=ids).filter(Q(scheduled_start__lt=finish,scheduled_end__gt=begin)|Q(status='CHECKED_IN')).values(
            'pk','visit_no','patient__patient_no','availability_slot_id','scheduled_start','scheduled_end','status'):
        visits[v['availability_slot_id']].append(v)
    for o in WaitOffer.objects.filter(slot_id__in=ids,state='PENDING',starts_at__lt=finish,ends_at__gt=begin).values('pk','slot_id','starts_at','ends_at','expires_at'):
        offers[o['slot_id']].append(o)
    for t in CoordinationTask.objects.filter(slot_id__in=ids,state__in=['OPEN','IN_PROGRESS','READY']).select_related('assignee'):
        tasks[t.slot_id]=t
    resources=ResourceCalendar(clinic,begin,finish)
    eligible=set(service.dentists.filter(is_active=True).values_list('pk',flat=True)) if service else set()
    days=[]
    for offset in range(count):
        date=first+timedelta(days=offset);a,b=day_bounds(date);rows=[]
        for slot in slots:
            if slot.starts_at>=b or slot.ends_at<=a:continue
            events=[];busy=[];in_care=False
            for v in visits[slot.pk]:
                start,end=v['scheduled_start'],v['scheduled_end']
                if start<b and end>a or v['status']=='CHECKED_IN' and date==timezone.localdate():
                    events.append(dict(kind='visit',id=v['pk'],label=dict(Visit._meta.get_field('status').choices).get(v['status'],v['status']),
                        code=v['visit_no'],patient_code=v['patient__patient_no'],start=start,end=end,
                        overdue=v['status']=='CHECKED_IN' and end<now))
                if v['status'] in OCCUPYING_STATUSES:busy.append((start,end))
                in_care|=v['status']=='CHECKED_IN'
            for o in offers[slot.pk]:
                active=o['expires_at']>now
                if o['starts_at']<b and o['ends_at']>a:
                    events.append(dict(kind='offer',id=o['pk'],label='有效邀约暂占' if active else '邀约到期，待回收',
                        start=o['starts_at'],end=o['ends_at'],expires=o['expires_at']))
                if active:busy.append((o['starts_at'],o['ends_at']))
            lower=max(slot.starts_at,a,now);upper=min(slot.ends_at,b)
            windows=free_intervals(lower,upper,busy) if lower<upper and slot.is_active else []
            feasible=[]
            if service and slot.is_active and not slot.booking_paused and slot.dentist_id in eligible and resources.ready:
                duration=timedelta(minutes=service.duration_minutes)
                for window_start,end in windows:
                    start=slot.starts_at+((window_start-slot.starts_at)//STEP)*STEP
                    while start<window_start or start<=now:start+=STEP
                    while start+duration<=end:
                        bundles=resources.bundles(service,slot.dentist_id,start,start+duration,limit=1)
                        if bundles:
                            feasible.append(dict(start=start,end=start+duration,room=bundles[0]['room']['name'],
                                resources='、'.join(r['name'] for r in bundles[0]['resources'])))
                            break
                        start+=STEP
                    if len(feasible)==3:break
            task=tasks.get(slot.pk)
            rows.append(dict(slot=slot,events=sorted(events,key=lambda e:(e['start'],e['kind'],e['id'])),
                windows=[dict(start=x,end=y) for x,y in windows],candidates=feasible,in_care=in_care,
                service_eligible=not service or slot.dentist_id in eligible,task=task,
                task_overdue=bool(task and task.due_at and task.due_at<now)))
        days.append(dict(day=date,rows=rows))
    inventory=[]
    overrun=set(ResourceClaim.objects.filter(asset__clinic_id=clinic,plan__is_current=True,
        plan__visit__status='CHECKED_IN',plan__visit__scheduled_end__lt=now).values_list('asset_id',flat=True))
    for binding in resources.bindings:
        blocks=[block for block in resources.blocks if block.asset_id==binding.asset_id or
            binding.room_id and (block.room_id==binding.room_id or block.department_id==binding.room.department_id)]
        inventory.append(dict(asset=binding.asset,room=binding.room.name if binding.room_id else '本店共享',
            busy=[dict(start=x,end=y) for x,y in sorted(resources.busy[binding.asset_id])],blocks=blocks,
            in_care_overrun=binding.asset_id in overrun))
    require_availability_actor(actor)
    return dict(days=days,first=first,last=first+timedelta(days=count-1),mode=mode,page=current,total_slots=pages.count,
        inventory=inventory,resource_ready=resources.ready,service=service,observed_at=now,
        previous_day=first-timedelta(days=count),next_day=first+timedelta(days=count))
