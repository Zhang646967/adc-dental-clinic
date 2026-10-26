"""Doctor selection is short-lived navigation, never appointment authority."""
from django.core import signing
from django.utils import timezone
from scheduling.service_content import positive_id
from scheduling.resource_models import BookingService

ENTRY='adc_profile_entry'
SIGNED='adc_profile_doctor_intent'
SALT='adc.profile.doctor-intent.p1'


def capture(request,service_id=None):
    raw=request.POST if request.method=='POST' else request.GET
    service_id=service_id or positive_id(raw.get('booking_service') or raw.get('service') or '')
    doctor=positive_id(raw.get('booking_dentist') or raw.get('dentist') or '')
    previous=request.session.get(ENTRY,{})
    if doctor and service_id and BookingService.objects.filter(pk=service_id,is_active=True,dentists__pk=doctor,dentists__is_active=True).exists():
        previous={'service':service_id,'dentist':doctor,'expires':timezone.now().timestamp()+600}
        request.session[ENTRY]=previous
    if previous.get('service')==service_id and previous.get('expires',0)>timezone.now().timestamp():
        return previous.get('dentist')
    return None


def remember(request,service_id):
    doctor=capture(request,service_id)
    if doctor:
        request.session[SIGNED]=signing.dumps({'user':request.user.pk,'workspace':str(request.workspace.pk),
            'service':service_id,'dentist':doctor},salt=SALT)


def consume(request,service_id):
    raw=request.session.pop(SIGNED,None)
    if not raw:return None
    try:data=signing.loads(raw,salt=SALT,max_age=600)
    except (signing.BadSignature,TypeError,ValueError):return None
    if (data.get('user')!=request.user.pk or data.get('workspace')!=str(request.workspace.pk) or data.get('service')!=service_id):return None
    doctor=data.get('dentist')
    return doctor if type(doctor) is int and BookingService.objects.filter(pk=service_id,dentists__pk=doctor,dentists__is_active=True).exists() else None
