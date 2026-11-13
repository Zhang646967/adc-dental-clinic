"""One patient projection for the website and native service centre."""
from django.utils import timezone
from coordination.models import WaitRequest, WaitOffer
from coordination.presentation import active_offers
from portal.policies import patient_access
from portal.report_notices import unread_count
from scheduling.models import Visit


ACTION_COPY = {
    'CHECKED_IN': ('已到诊', '查看到诊安排', '门店已登记到诊，请按现场指引就诊。'),
    'CONFIRM_OFFER': ('候补邀约待确认', '核对并答复', '请在截止时间前核对门店提供的时段。'),
    'UPCOMING_VISIT': ('下一次就诊', '查看到诊安排', '核对时间和门店，按预约安排到诊。'),
    'CONTACT_CLINIC': ('请联系门店核实', '查看预约与联系方式', '预约时间已过，结果由门店核实。'),
    'WAITLIST': ('候补进度', '查看我的候补', '查看门店提供的安排和当前结果。'),
    'BOOK': ('预约就诊', '选择服务', '查看服务、门店和可预约时间。'),
}


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
    action = primary_action(visits, current, offers, waiting_count, now)
    label, button, hint = ACTION_COPY[action['kind']]
    action.update(label=label, button=button, hint=hint)
    return dict(patient=access.patient, can_view_funds=not access.delegated, next_visit=current or upcoming,
        active_count=visits.filter(status__in=('SCHEDULED', 'CHECKED_IN')).count(),
        history_count=visits.exclude(status__in=('SCHEDULED', 'CHECKED_IN')).count(),
        waiting_count=waiting_count, offer_count=offers.count(),
        primary_action=action, report_unread_count=unread_count(access))
