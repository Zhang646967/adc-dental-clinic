"""Accept one retained offer as an explicitly chosen replacement, under shared locks."""
from django.db import connection
from django.utils import timezone
from adc_core.rules import RuleError
from care.audit import emit
from coordination.models import WaitOffer, WaitRequest
from coordination.policies import require_owner_or_front
from scheduling.services import reschedule_visit_locked


def accept_replacement_locked(*, actor, old, slot, offer_id, expected_revision, expected_version,
                              reason, reception_case):
    if not connection.in_atomic_block:
        raise RuntimeError('Offer replacement requires a locked transaction')
    preview = WaitOffer.objects.select_related('request').get(pk=offer_id)
    require_owner_or_front(actor, preview.request)
    entry = WaitRequest.objects.select_for_update().get(pk=preview.request_id)
    offer = WaitOffer.objects.select_for_update().get(pk=offer_id)
    if (entry.patient_id != old.patient_id or entry.clinic_id != old.clinic_id or
            offer.slot_id != slot.pk or entry.revision != expected_revision or entry.state != 'OFFERED' or
            offer.state != 'PENDING' or offer.expires_at <= timezone.now()):
        raise RuleError('候补邀约已经变化或到期；本次没有改期，请核对当前结果。')
    new = reschedule_visit_locked(actor=actor, old=old, slot=slot, expected_version=expected_version,
        start=offer.starts_at, end=offer.ends_at, reason=reason, honor_offer_id=offer.pk)
    offer.visit = new; offer.state = 'ACCEPTED'
    entry.state = 'BOOKED'; entry.revision += 1
    from reception.services import link_waitlist_result_locked
    link_waitlist_result_locked(reception_case, entry, new, actor)
    offer.save(update_fields=['visit', 'state']); entry.save(update_fields=['state', 'revision'])
    emit(actor, 'WAIT_OFFER_ANSWERED', offer, visit=new, summary={'accepted': True})
    return new
