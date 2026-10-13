"""Read-only front desk collaboration, scoped BEFORE any per-slot read.

Short source-slot row locks coordinate a consistent projection with existing
application commands. They do NOT pause booking after the response is returned.
Only identity codes are projected: no name, phone, complaint or clinical content.
"""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone
from accounts.policies import bindings
from coordination.models import WaitOffer
from patients.models import Patient
from scheduling.models import AvailabilitySlot, Visit
from scheduling.coordination import lock_slots
from scheduling.availability_rules import (MAX_RELATIONS, AvailabilityError,
    assess_relations, display_time, positive_id)
from scheduling.front_coordination_rules import (CONTRACT, assessment,
    relation_anomalies, visit_instruction, offer_instruction, safe_page)
from workspaces.context import require_active, valid_context
from workspaces.models import WorkspaceContext


def require_front_coordination(actor):
    ctx = getattr(actor, '_adc_workspace', None)
    if ctx is None or ctx.role != 'FRONT_DESK' or ctx.clinic_id is None:
        raise PermissionDenied('请以获授权的前台身份选择当前诊所。')
    require_active(actor, ('FRONT_DESK',), ctx.clinic_id)
    if not valid_context(actor, ctx) or not WorkspaceContext.objects.filter(
            pk=ctx.pk, user_id=actor.pk, role='FRONT_DESK', clinic_id=ctx.clinic_id,
            revision=ctx.revision).exists():
        raise PermissionDenied('工作身份或诊所已经变化，请返回当前工作台。')
    if not bindings(actor).filter(role='FRONT_DESK', scope_kind='CLINIC', clinic_id=ctx.clinic_id).exists():
        raise PermissionDenied('当前诊所的前台授权已经失效。')
    return ctx


def _identity(ctx):
    return str(ctx.pk), ctx.user_id, ctx.role, ctx.clinic_id, ctx.revision


def _reauthorize(actor, original):
    if _identity(require_front_coordination(actor)) != original:
        raise PermissionDenied('当前工作上下文已变化，不返回旧范围数据。')


def _slot_card(s):
    return {'id': s.pk, 'clinic': s.clinic.name, 'dentist': s.dentist.name,
        'employee_no': s.dentist.employee_no, 'start': display_time(s.starts_at),
        'end': display_time(s.ends_at), 'active': s.is_active, 'paused': s.booking_paused}


def list_coordination_slots(*, actor, mode='upcoming', slot_id=None, page='1'):
    ctx = require_front_coordination(actor); original = _identity(ctx)
    now = timezone.now()
    if mode not in ('upcoming', 'all'):
        raise AvailabilityError('请选择未来及进行中出诊，或全部历史。')
    qs = AvailabilitySlot.objects.filter(clinic_id=ctx.clinic_id)
    if slot_id is not None:
        positive_id(slot_id)
        qs = qs.filter(pk=slot_id)  # Exact-code lookup intentionally includes history.
    elif mode == 'upcoming':
        qs = qs.filter(ends_at__gt=now)
    pending = WaitOffer.objects.filter(slot_id=OuterRef('pk'), state='PENDING', expires_at__gt=now)
    # Exists keeps offer joins from multiplying Visit counts.
    qs = qs.annotate(scheduled_count=Count('visits', filter=Q(visits__status='SCHEDULED')),
        care_count=Count('visits', filter=Q(visits__status__in=('CHECKED_IN','COMPLETED','CLOSED_NO_TREATMENT'))),
        has_effective_offer=Exists(pending)).select_related('clinic','dentist').order_by('starts_at','id')
    total = qs.count(); number, start, pages = safe_page(page, total)
    rows = [_slot_card(s) | {'scheduled_count': s.scheduled_count,
        'care_count': s.care_count, 'has_effective_offer': s.has_effective_offer}
        for s in qs[start:start + 20]]
    _reauthorize(actor, original)
    return {'rows': rows, 'total': total, 'number': number, 'pages': pages,
        'observed_at': display_time(now), 'contract': CONTRACT}


def _serialized(qs, fields):
    rows = list(qs.values(*fields)[:MAX_RELATIONS + 1])
    return [{k: v.isoformat() if hasattr(v, 'isoformat') else v for k, v in row.items()} for row in rows]


@transaction.atomic
def read_coordination_slot(*, actor, slot_id, visit_page='1', offer_page='1'):
    ctx = require_front_coordination(actor); original = _identity(ctx)
    try:
        positive_id(slot_id)
    except AvailabilityError:
        raise PermissionDenied('出诊不存在或不属于当前诊所。') from None
    # Reject an unknown/foreign object before locking or inspecting its relations.
    if not AvailabilitySlot.objects.filter(pk=slot_id, clinic_id=ctx.clinic_id).exists():
        raise PermissionDenied('出诊不存在或不属于当前诊所。')
    slot = lock_slots([slot_id])[slot_id]
    if slot.clinic_id != ctx.clinic_id:
        raise PermissionDenied('出诊范围已经变化。')
    now = timezone.now()
    facts = {'slot_id': slot.pk, 'clinic_id': slot.clinic_id, 'dentist_id': slot.dentist_id,
        'starts_at': slot.starts_at.isoformat(), 'ends_at': slot.ends_at.isoformat(),
        'is_active': slot.is_active, 'clinic_active': slot.clinic.is_active,
        'dentist_active': slot.dentist.is_active}
    vq = Visit.objects.filter(availability_slot_id=slot.pk).order_by('scheduled_start','id')
    oq = WaitOffer.objects.filter(slot_id=slot.pk).order_by('starts_at','id')
    vc, oc = vq.count(), oq.count()
    visits = _serialized(vq, ('id','visit_no','availability_slot_id','clinic_id','dentist_id',
        'patient_id','scheduled_start','scheduled_end','status','lock_version'))
    offers = _serialized(oq, ('id','slot_id','request_id','request__clinic_id','request__patient_id',
        'request__state','starts_at','ends_at','expires_at','state','visit_id'))
    impact = assess_relations(slot=facts, visits=visits, offers=offers, now=now, visit_count=vc, offer_count=oc)
    extra = relation_anomalies(slot_id=slot.pk, visits=visits, offers=offers)
    clinical_count = sum(v['status'] in ('CHECKED_IN','COMPLETED','CLOSED_NO_TREATMENT') for v in visits)
    result = assessment(facts, impact, now, clinical_count=clinical_count, additional_anomalies=extra)
    base = {'slot': _slot_card(slot), 'impact': impact, 'assessment': result,
        'observed_at': display_time(now), 'contract': CONTRACT, 'clinical_count': clinical_count,
        'visits': [], 'offers': [], 'visit_count': vc, 'offer_count': oc,
        'unsafe': result.code == 'REVIEW'}
    if base['unsafe']:
        # A malformed foreign relation must not leak a patient code or deep link.
        _reauthorize(actor, original)
        return base
    vn, vi, vp = safe_page(visit_page, vc)
    on, oi, op = safe_page(offer_page, oc)
    selected_visits = visits[vi:vi+20]; selected_offers = offers[oi:oi+20]
    ids = {v['patient_id'] for v in selected_visits} | {o['request__patient_id'] for o in selected_offers}
    # Minimal identification only; identity/contact verification stays in original authorized pages.
    patients = dict(Patient.objects.filter(pk__in=ids).values_list('pk', 'patient_no'))
    from datetime import datetime
    for v in selected_visits:
        instruction = visit_instruction(v['status'], starts_at=datetime.fromisoformat(v['scheduled_start']), now=now)
        base['visits'].append({'id': v['id'], 'visit_no': v['visit_no'],
            'patient_no': patients.get(v['patient_id'],'资料待核对'),
            'start': display_time(datetime.fromisoformat(v['scheduled_start'])),
            'end': display_time(datetime.fromisoformat(v['scheduled_end'])), **instruction})
    for o in selected_offers:
        instruction = offer_instruction(o['state'], expires_at=datetime.fromisoformat(o['expires_at']), now=now)
        base['offers'].append({'id': o['id'], 'request_id': o['request_id'],
            'visit_id': o['visit_id'], 'patient_no': patients.get(o['request__patient_id'],'资料待核对'),
            'start': display_time(datetime.fromisoformat(o['starts_at'])),
            'end': display_time(datetime.fromisoformat(o['ends_at'])),
            'expires': display_time(datetime.fromisoformat(o['expires_at'])), **instruction})
    base.update(visit_number=vn, visit_pages=vp, offer_number=on, offer_pages=op)
    _reauthorize(actor, original)
    return base
