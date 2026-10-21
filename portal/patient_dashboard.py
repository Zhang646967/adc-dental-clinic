"""One patient projection for the website and native service centre."""
from django.utils import timezone
from coordination.models import WaitRequest, WaitOffer
from portal.policies import patient_access
from scheduling.models import Visit


def dashboard(actor):
    access = patient_access(actor)
    visits = Visit.objects.filter(patient_id=access.patient_id)
    waits = WaitRequest.objects.filter(patient_id=access.patient_id)
    now = timezone.now()
    current = visits.filter(status='CHECKED_IN').select_related('clinic', 'dentist').order_by('scheduled_start', 'pk').first()
    upcoming = visits.filter(status='SCHEDULED', scheduled_start__gt=now).select_related('clinic', 'dentist').order_by('scheduled_start', 'pk').first()
    return dict(patient=access.patient, next_visit=current or upcoming,
        active_count=visits.filter(status__in=('SCHEDULED', 'CHECKED_IN')).count(),
        history_count=visits.exclude(status__in=('SCHEDULED', 'CHECKED_IN')).count(),
        waiting_count=waits.filter(state__in=('WAITING', 'OFFERED')).count(),
        offer_count=WaitOffer.objects.filter(request__in=waits, request__state='OFFERED',
            state='PENDING', expires_at__gt=now).count())
