"""One patient projection for the website and native service centre."""
from django.utils import timezone
from coordination.models import WaitRequest, WaitOffer
from coordination.presentation import active_offers
from portal.policies import patient_access
from scheduling.models import Visit


def needs_outcome_review(visit, now):
    return visit.status == 'SCHEDULED' and visit.scheduled_end <= now


def primary_action(visits, current, offers, waiting_count, now):
    if current:
        return dict(kind='CHECKED_IN', visit=current, offer=None)
    offer = offers.order_by('expires_at', 'pk').first()
    if offer:
        return dict(kind='CONFIRM_OFFER', visit=None, offer=offer)
    scheduled = visits.filter(status='SCHEDULED').select_related('clinic', 'dentist')
    upcoming = scheduled.filter(scheduled_end__gt=now).order_by('scheduled_start', 'pk').first()
    if upcoming:
        return dict(kind='UPCOMING_VISIT', visit=upcoming, offer=None)
    overdue = scheduled.filter(scheduled_end__lte=now).order_by('-scheduled_end', 'pk').first()
    if overdue:
        return dict(kind='CONTACT_CLINIC', visit=overdue, offer=None)
    return dict(kind='WAITLIST' if waiting_count else 'BOOK', visit=None, offer=None)


def dashboard(actor, *, now=None):
    access = patient_access(actor)
    visits = access.scope(Visit.objects.all())
    waits = access.scope(WaitRequest.objects.all())
    now = now or timezone.now()
    current = visits.filter(status='CHECKED_IN').select_related('clinic', 'dentist').order_by('scheduled_start', 'pk').first()
    upcoming = visits.filter(status='SCHEDULED', scheduled_start__gt=now).select_related('clinic', 'dentist').order_by('scheduled_start', 'pk').first()
    waiting_count = waits.filter(state__in=('WAITING', 'OFFERED')).count()
    offers = active_offers(WaitOffer.objects.filter(request__in=waits), now)
    return dict(patient=access.patient, next_visit=current or upcoming,
        active_count=visits.filter(status__in=('SCHEDULED', 'CHECKED_IN')).count(),
        history_count=visits.exclude(status__in=('SCHEDULED', 'CHECKED_IN')).count(),
        waiting_count=waiting_count, offer_count=offers.count(),
        primary_action=primary_action(visits, current, offers, waiting_count, now))
