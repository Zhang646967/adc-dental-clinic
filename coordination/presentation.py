"""Shared read-only state for patient and front-desk offer screens."""

EXPIRED_LABEL = '已到期，待前台重新安排'


def active_offers(offers, now):
    return offers.filter(request__state='OFFERED', state='PENDING', expires_at__gt=now)


def offer_status(offer, now):
    if offer.state != 'PENDING':
        label = EXPIRED_LABEL if offer.state == 'EXPIRED' else offer.get_state_display()
        return label, False
    if offer.expires_at <= now:
        return EXPIRED_LABEL, False
    if offer.request.state != 'OFFERED':
        return '已不可确认', False
    return offer.get_state_display(), True


def wait_status(entry, offers):
    if entry.state == 'OFFERED' and any(state == 'PENDING' and label == EXPIRED_LABEL for state, label in offers):
        return EXPIRED_LABEL
    return entry.get_state_display()
