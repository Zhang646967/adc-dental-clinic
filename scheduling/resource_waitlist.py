"""Resource-mode waitlist: oldest request, earliest feasible start, stable assets.

A deterministic bounded greedy proposal, with no global-optimality claim.
Publication rechecks every suggestion under the shared locks.
"""
from datetime import timedelta
from django.utils import timezone
from adc_core.rules import RuleError
from care.audit import emit
from coordination.models import WaitRequest,WaitOffer,SchedulePlan
from coordination.solver import overlaps
from scheduling.models import AvailabilitySlot,Visit
from scheduling.resources import ResourceCalendar
from adc_core.rules import OCCUPYING_STATUSES

STEP=timedelta(minutes=15)

def create_resource_plan(actor,clinic_id):
    now=timezone.now();finish=now+timedelta(days=14)
    entries=list(WaitRequest.objects.filter(clinic_id=clinic_id,state='WAITING',patient__is_active=True,
        latest__gt=now).select_related('service__department').order_by('created_at','pk')[:60])
    slots=list(AvailabilitySlot.objects.filter(clinic_id=clinic_id,is_active=True,booking_paused=False,
        dentist__is_active=True,clinic__is_active=True,ends_at__gt=now,starts_at__lt=finish).order_by('starts_at','pk')[:80])
    busy=list(Visit.objects.filter(status__in=OCCUPYING_STATUSES,scheduled_end__gt=now,
        scheduled_start__lt=finish+timedelta(hours=4)).values_list('patient_id','dentist_id','scheduled_start','scheduled_end'))
    busy+=list(WaitOffer.objects.filter(state='PENDING',expires_at__gt=now).values_list(
        'request__patient_id','slot__dentist_id','starts_at','ends_at'))
    calendar=ResourceCalendar(clinic_id,now,finish+timedelta(hours=4));suggestions=[];unassigned=[];checked=0
    for entry in entries:
        service=entry.service
        if not service:
            unassigned.append(entry.pk);continue  # Legacy intention needs explicit service verification.
        duration=timedelta(minutes=service.duration_minutes);chosen=None
        for slot in slots:
            if entry.preferred_dentist_id and entry.preferred_dentist_id!=slot.dentist_id:continue
            lower=max(slot.starts_at,entry.earliest,now)
            start=slot.starts_at+((lower-slot.starts_at)//STEP)*STEP
            if start<lower or start<=now:start+=STEP
            local_checked=0
            while start+duration<=min(slot.ends_at,entry.latest,finish):
                checked+=1;local_checked+=1
                if local_checked>200:break
                end=start+duration
                if not any((p==entry.patient_id or d==slot.dentist_id) and overlaps(start,end,a,b) for p,d,a,b in busy):
                    try:bundles=calendar.bundles(service,slot.dentist_id,start,end,limit=1)
                    except RuleError:bundles=[]
                    if bundles:
                        candidate=(start,slot.pk,slot,end,bundles[0])
                        if chosen is None or candidate[:2]<chosen[:2]:chosen=candidate
                        break
                start+=STEP
        if chosen:
            start,_,slot,end,bundle=chosen
            suggestions.append({'request_id':entry.pk,'request_revision':entry.revision,'slot_id':slot.pk,
                'start':start.isoformat(),'end':end.isoformat(),'intake_revision':slot.intake_revision,
                'service_id':service.pk,'resources':bundle})
            busy.append((entry.patient_id,slot.dentist_id,start,end))
            for r in bundle['resources']:calendar.busy[r['id']].append((start,end))
        else:unassigned.append(entry.pk)
    plan=SchedulePlan.objects.create(clinic_id=clinic_id,created_by=actor,suggestions=suggestions,
        metadata={'scheduling_contract':SchedulePlan.CONTRACT,'algorithm':'RESOURCE_GREEDY_V1','status':'BOUNDED_GREEDY','bounded':True,'request_count':len(entries),
            'slot_count':len(slots),'checked_cells':checked,'unassigned':unassigned,'as_of':now.isoformat(),
            'limits':{'requests':60,'slots':80,'starts_per_slot':200},
            'request_limit_hit':len(entries)==60,'slot_limit_hit':len(slots)==80,
            'notice':'按候补登记先后、可行时间先后及稳定资源顺序生成建议；按服务时长占用整段资源，不保证全局最优。缺服务的旧需求须先核实。'})
    emit(actor,'SCHEDULE_SUGGESTED',plan,summary={'matched':len(suggestions),'clinic_id':clinic_id})
    return plan
