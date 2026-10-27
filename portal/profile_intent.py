"""Doctor selection is short-lived navigation, never appointment authority."""
from django.core import signing
from django.utils import timezone
from scheduling.service_content import positive_id
from scheduling.resource_models import BookingService
from datetime import date,timedelta

ENTRY='adc_profile_entry'
SIGNED='adc_profile_doctor_intent'
SALT='adc.profile.doctor-intent.p1'


def valid_day(value):
    try:day=date.fromisoformat(value)
    except (TypeError,ValueError):return None
    return day.isoformat() if timezone.localdate()<=day<=timezone.localdate()+timedelta(days=14) else None


def capture(request,service_id=None):
    raw=request.POST if request.method=='POST' else request.GET
    service_id=service_id or positive_id(raw.get('booking_service') or raw.get('service') or '')
    doctor=positive_id(raw.get('booking_dentist') or raw.get('dentist') or '')
    day=valid_day(raw.get('booking_day') or raw.get('day'))
    previous=request.session.get(ENTRY,{})
    if service_id and (doctor or day) and BookingService.objects.filter(pk=service_id,is_active=True).exists():
        if doctor and not BookingService.objects.filter(pk=service_id,dentists__pk=doctor,dentists__is_active=True).exists():return None
        previous={'service':service_id,'dentist':doctor,'day':day,'expires':timezone.now().timestamp()+600}
        request.session[ENTRY]=previous
    if previous.get('service')==service_id and previous.get('expires',0)>timezone.now().timestamp():
        return previous.get('dentist')
    return None


def remember(request,service_id):
    doctor=capture(request,service_id)
    entry=request.session.get(ENTRY,{})
    day=valid_day(entry.get('day')) if entry.get('service')==service_id and entry.get('expires',0)>timezone.now().timestamp() else None
    if doctor or day:
        request.session[SIGNED]=signing.dumps({'user':request.user.pk,'workspace':str(request.workspace.pk),
            'service':service_id,'dentist':doctor,'day':day},salt=SALT)


def consume_selection(request,service_id):
    raw=request.session.pop(SIGNED,None)
    if not raw:return {}
    try:data=signing.loads(raw,salt=SALT,max_age=600)
    except (signing.BadSignature,TypeError,ValueError):return {}
    if (data.get('user')!=request.user.pk or data.get('workspace')!=str(request.workspace.pk) or data.get('service')!=service_id):return {}
    doctor=data.get('dentist')
    if doctor and (type(doctor) is not int or not BookingService.objects.filter(pk=service_id,dentists__pk=doctor,dentists__is_active=True).exists()):return {}
    return dict(dentist=doctor,day=valid_day(data.get('day')))


def consume(request,service_id):
    return consume_selection(request,service_id).get('dentist')
