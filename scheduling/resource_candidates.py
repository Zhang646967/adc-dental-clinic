"""Bounded, deterministic observations, never reservations or consent."""
from datetime import timedelta
from django.db.models import Q
from django.utils import timezone
from adc_core.rules import OCCUPYING_STATUSES,RuleError
from scheduling.models import Visit,AvailabilitySlot
from scheduling.resources import ResourceCalendar,service_for
from scheduling.worklists import day_bounds
from coordination.models import WaitOffer

STEP=timedelta(minutes=15)

def candidates(*,clinic_id,service_id,day,patient_id,dentist_id=None,ignore_visit=None,horizon=True):
    now=timezone.now();begin,finish=day_bounds(day)
    if day<timezone.localdate() or (horizon and day>timezone.localdate()+timedelta(days=14)):
        raise RuleError('请选择未来十四天内日期。' if horizon else '请选择今日或未来已发布的出诊。')
    service=service_for(clinic_id,service_id);duration=timedelta(minutes=service.duration_minutes)
    slots=AvailabilitySlot.objects.filter(clinic_id=clinic_id,is_active=True,booking_paused=False,
        clinic__is_active=True,dentist__is_active=True,dentist__in=service.dentists.all(),
        starts_at__lt=finish,ends_at__gt=max(begin,now)).select_related('clinic','dentist')
    if dentist_id:slots=slots.filter(dentist_id=dentist_id)
    calendar=ResourceCalendar(clinic_id,begin,finish)
    busy=list(Visit.objects.filter(status__in=OCCUPYING_STATUSES,clinic_id=clinic_id,
        scheduled_start__lt=finish+duration,scheduled_end__gt=begin).exclude(pk=ignore_visit).values_list(
            'patient_id','dentist_id','scheduled_start','scheduled_end'))
    # Patient conflicts can be in another clinic.
    busy+=list(Visit.objects.filter(patient_id=patient_id,status__in=OCCUPYING_STATUSES,
        scheduled_start__lt=finish+duration,scheduled_end__gt=begin).exclude(pk=ignore_visit).exclude(clinic_id=clinic_id).values_list(
            'patient_id','dentist_id','scheduled_start','scheduled_end')) if patient_id else []
    held=list(WaitOffer.objects.filter(state='PENDING',expires_at__gt=now,starts_at__lt=finish+duration,
        ends_at__gt=begin).filter(Q(request__clinic_id=clinic_id)|Q(request__patient_id=patient_id)).values_list(
            'request__patient_id','slot__dentist_id','starts_at','ends_at'))
    rows=[];checked=0
    for slot in slots.order_by('starts_at','pk')[:80]:
        lower=max(begin,now,slot.starts_at);start=slot.starts_at+((lower-slot.starts_at)//STEP)*STEP
        if start<=now or start<lower:start+=STEP
        while start+duration<=min(slot.ends_at,finish) and (not horizon or start<=now+timedelta(days=14)):
            checked+=1
            if checked>480:return rows
            end=start+duration
            if not any((p==patient_id or d==slot.dentist_id) and a<end and start<b for p,d,a,b in busy+held):
                bundles=calendar.bundles(service,slot.dentist_id,start,end,limit=1)
                if bundles:
                    rows.append({'slot':slot,'slot_id':slot.pk,'start':start,'end':end,'start_iso':start.isoformat(),
                        'end_iso':end.isoformat(),'resources':bundles[0],'service':service})
                    if len(rows)>=80:return rows
            start+=STEP
    return rows
