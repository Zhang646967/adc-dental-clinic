"""Typed, authorized navigation context. Never redirect to a supplied URL.

Only keep an origin if it is the current record's slot, or the direct predecessor
visit's slot after a successful reschedule within the current clinic.
"""
from django.urls import reverse
from scheduling.front_coordination_selectors import require_front_coordination


from scheduling.front_coordination_rules import origin_id


def visit_return_slot(actor, raw, visit):
    ctx = getattr(actor, '_adc_workspace', None)
    if ctx is None or ctx.role != 'FRONT_DESK': return None
    ctx = require_front_coordination(actor)
    sid = origin_id(raw)
    if sid is None or visit.clinic_id != ctx.clinic_id: return None
    if sid == visit.availability_slot_id: return sid
    if visit.replaces_visit_id:
        from scheduling.models import Visit
        if Visit.objects.filter(pk=visit.replaces_visit_id, clinic_id=ctx.clinic_id,
                availability_slot_id=sid, patient_id=visit.patient_id).exists():
            return sid
    return None


def offer_return_slot(actor, raw, offer):
    ctx = getattr(actor, '_adc_workspace', None)
    if ctx is None or ctx.role != 'FRONT_DESK': return None
    ctx = require_front_coordination(actor)
    sid = origin_id(raw)
    return sid if sid == offer.slot_id and offer.request.clinic_id == ctx.clinic_id else None


def return_context(slot_id):
    return {'coordination_slot_id': slot_id,
        'coordination_back_url': reverse('front_coordination_detail', args=[slot_id]) if slot_id else ''}


def visit_chain_context(actor, visit, origin=None):
    """Immediate reschedule links, constrained to the active front desk clinic.

    Existing role/object authorization still runs when the linked page is opened.
    A predecessor/successor is not returned when the patient or clinic differs.
    """
    result = {'coordination_predecessor': None, 'coordination_successor': None}
    ctx = getattr(actor, '_adc_workspace', None)
    if ctx is None or ctx.role != 'FRONT_DESK': return result
    ctx = require_front_coordination(actor)
    if visit.clinic_id != ctx.clinic_id: return result
    from urllib.parse import urlencode
    from scheduling.models import Visit
    from scheduling.availability_rules import display_time
    scoped = Visit.objects.filter(clinic_id=ctx.clinic_id, patient_id=visit.patient_id)
    previous = scoped.filter(pk=visit.replaces_visit_id).first() if visit.replaces_visit_id else None
    following = scoped.filter(replaces_visit_id=visit.pk).first() if visit.status == 'RESCHEDULED' else None
    for key, other in (('coordination_predecessor', previous), ('coordination_successor', following)):
        if other:
            sid = visit_return_slot(actor, str(origin), other) if origin else None
            url = reverse('visit_detail', args=[other.pk])
            if sid: url += '?' + urlencode({'coord_slot':sid})
            result[key] = {'visit_no':other.visit_no, 'start':display_time(other.scheduled_start),
                'end':display_time(other.scheduled_end), 'status':other.get_status_display(), 'url':url}
    require_front_coordination(actor)
    return result
