"""Patient-owned rescheduling uses the scheduling module's retained successor chain."""
from datetime import datetime, timedelta
from django.db import transaction
from django.utils import timezone
from accounts.policies import require_writable
from adc_core.commands import assert_revision, business_errors
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError, validate_slot
from adc_core.snapshots import reporting_snapshot
from care.audit import emit
from patients.models import Patient
from portal.models import BookingReceipt
from portal.policies import patient_access
from portal.rules import validate_public_start
from scheduling.coordination import lock_slots
from scheduling.models import AvailabilitySlot, Visit
from scheduling.reschedule_selectors import check_target, options_for_visit
from scheduling.resources import current_plan, policy, service_for, choose_bundle, lock_physical, inspect_reserved_resources
from scheduling.services import reschedule_visit_locked
from coordination.reservations import lock_resources

CONTRACT = 'adc.portal.reschedule.v1'


def owned_visit(actor, visit_id):
    access = patient_access(actor)
    return Visit.objects.select_related('patient', 'clinic', 'dentist').get(pk=visit_id, patient_id=access.patient_id)


def check_source(visit):
    if visit.status != 'SCHEDULED' or visit.scheduled_start <= timezone.now():
        raise RuleError('仅可自助改期尚未开始的预约；请核对相关结果，其他情况联系原诊所前台。')
    if not visit.patient.is_active or not visit.clinic.is_active:
        raise RuleError('患者资料或原诊所已停用，请联系前台协助；没有取消原预约。')


def options(*, actor, visit_id, day, dentist_id=None):
    visit = owned_visit(actor, visit_id)
    check_source(visit)
    return options_for_visit(visit=visit, day=day, dentist_id=dentist_id)


def _arrangement(visit, slot, start):
    plan = current_plan(visit)
    if policy(visit.clinic_id):
        if plan is None:
            raise RuleError('原预约的服务和资源尚待核实，请联系前台；原预约保留。')
        service = service_for(visit.clinic_id, plan.service_id)
        end = start + timedelta(minutes=service.duration_minutes)
        from portal.services import _resource_public_time
        _resource_public_time(start, end, slot)
    else:
        service = None
        validate_public_start(start, slot.starts_at, slot.ends_at, timezone.now())
        end = start + (visit.scheduled_end-visit.scheduled_start)
        validate_slot(start, end, slot.starts_at, slot.ends_at, timezone.now())
    check_target(visit, slot, start, end, timezone.now())
    return plan, service, end


def _offer(visit, offer_id):
    from coordination.models import WaitOffer
    offer = WaitOffer.objects.select_related('request', 'slot__clinic', 'slot__dentist').get(
        pk=offer_id, request__patient_id=visit.patient_id, request__clinic_id=visit.clinic_id)
    if (offer.state != 'PENDING' or offer.request.state != 'OFFERED' or
            offer.expires_at <= timezone.now()):
        raise RuleError('这条邀约已处理或到期，请核对候补结果；原预约没有因此改期。')
    source = current_plan(visit)
    plan = inspect_reserved_resources(offer)
    if ((policy(visit.clinic_id) and (source is None or plan is None or source.service_id != plan.service_id)) or
            plan is None and offer.ends_at-offer.starts_at != visit.scheduled_end-visit.scheduled_start):
        raise RuleError('邀约与原预约服务不一致，请联系前台核对；不能将不同服务直接用作改期。')
    check_target(visit, offer.slot, offer.starts_at, offer.ends_at, timezone.now(), ignore_offer=offer.pk)
    return offer, plan


def prepare(*, actor, visit_id, expected_version, slot_id, start, reason, offer_id=None):
    with reporting_snapshot():
        access = patient_access(actor)
        visit = owned_visit(actor, visit_id)
        check_source(visit)
        assert_revision(visit, expected_version)
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
            raise RuleError('请填写1至500字的改期原因。')
        offer = None; offer_plan = None
        if offer_id:
            offer, offer_plan = _offer(visit, offer_id)
            slot, start, end = offer.slot, offer.starts_at, offer.ends_at
            plan = current_plan(visit)
            service = offer_plan.service if offer_plan else None
            bundle = offer_plan.snapshot if offer_plan else None
        else:
            slot = AvailabilitySlot.objects.select_related('clinic', 'dentist').get(pk=slot_id, clinic_id=visit.clinic_id)
            plan, service, end = _arrangement(visit, slot, start)
            bundle = choose_bundle(slot=slot, start=start, end=end, service_id=service.pk if service else None,
                ignore_visit=visit.pk)
        data = dict(access=access.pk, patient=access.patient_id, visit=visit.pk, version=visit.lock_version,
            source_plan=plan.pk if plan else None, slot=slot.pk, intake_revision=slot.intake_revision,
            start=start.isoformat(), end=end.isoformat(), reason=reason.strip(),
            service=service.pk if service else None, resources=bundle, offer=offer.pk if offer else None,
            offer_revision=offer.request.revision if offer else None, offer_plan=offer_plan.pk if offer_plan else None)
        return dict(original=visit, destination=slot, start=start, end=end, reason=reason.strip(),
            service=service, resources=bundle, offer=offer, duration_changed=end-start != visit.scheduled_end-visit.scheduled_start,
            proposal_token=proposal(actor, CONTRACT, ('PATIENT',), data))


@business_errors
@transaction.atomic
def confirm(*, actor, visit_id, proposal_token, confirmed):
    require_writable(actor)
    access = patient_access(actor, lock=True)
    if confirmed is not True:
        raise RuleError('请核对原安排、新安排与改期原因后明确确认。')
    p = read_proposal(actor, CONTRACT, ('PATIENT',), proposal_token)
    d = p['data']
    if (d['access'], d['patient'], d['visit']) != (access.pk, access.patient_id, visit_id):
        raise RuleError('确认内容或患者授权已经变化，请重新打开本人预约。')
    # A receipt proves this exact successful request, even if its result later changes.
    prior = BookingReceipt.objects.select_related('visit').filter(nonce=p['operation'], access=access,
        visit__replaces_visit_id=visit_id, visit__patient_id=access.patient_id).first()
    if prior:
        return prior.visit, True
    preview = owned_visit(actor, visit_id)
    reception_case = None
    if d['offer']:
        offer, _ = _offer(preview, d['offer'])
        from reception.services import lock_waitlist_case
        reception_case = lock_waitlist_case(offer.request_id)
    slots = lock_slots([preview.availability_slot_id, d['slot']])
    lock_resources(patients=[access.patient_id], dentists=[s.dentist_id for s in slots.values()])
    lock_physical(preview.clinic_id)
    Patient.objects.select_for_update().get(pk=access.patient_id, is_active=True)
    visit = Visit.objects.select_for_update(of=('self',)).select_related('patient', 'clinic', 'dentist').get(
        pk=visit_id, patient_id=access.patient_id)
    check_source(visit)
    assert_revision(visit, d['version'])
    slot = slots[d['slot']]
    if slot.clinic_id != visit.clinic_id or (not d['offer'] and slot.intake_revision != d['intake_revision']):
        raise RuleError('目标诊所或接收状态已经变化，请重新选择；本次没有改约。')
    plan = current_plan(visit)
    if (plan.pk if plan else None) != d['source_plan']:
        raise RuleError('原预约资源方案已经变化，请重新核对；本次没有改约。')
    if d['offer']:
        offer, held_plan = _offer(visit, d['offer'])
        if ((held_plan.pk if held_plan else None) != d['offer_plan'] or
                offer.starts_at.isoformat() != d['start'] or offer.ends_at.isoformat() != d['end']):
            raise RuleError('邀约资源或时间已经变化，请重新核对；本次没有改约。')
        from coordination.reschedule_offer import accept_replacement_locked
        new = accept_replacement_locked(actor=actor, old=visit, slot=slot, offer_id=offer.pk,
            expected_revision=d['offer_revision'], expected_version=d['version'], reason=d['reason'],
            reception_case=reception_case)
    else:
        start = datetime.fromisoformat(d['start'])
        plan, service, end = _arrangement(visit, slot, start)
        if (service.pk if service else None) != d['service'] or end.isoformat() != d['end']:
            raise RuleError('服务或预计时长已经变化，请重新核对；本次没有改约。')
        new = reschedule_visit_locked(actor=actor, old=visit, slot=slot, expected_version=d['version'],
            start=start, end=end, reason=d['reason'], service_id=d['service'], resource_snapshot=d['resources'])
    BookingReceipt.objects.create(nonce=p['operation'], access=access, visit=new)
    emit(actor, 'PORTAL_RESCHEDULE_CONFIRMED', new, visit=new,
        summary={'original_id': visit.pk, 'source': 'patient_portal'})
    return new, False


def related_context(actor, visit):
    """Only own immediate links; each later history page reauthorizes independently."""
    access = patient_access(actor)
    own = Visit.objects.filter(patient_id=access.patient_id)
    from coordination.models import WaitRequest
    return dict(previous_visit=own.filter(pk=visit.replaces_visit_id).first() if visit.replaces_visit_id else None,
        next_visit=own.filter(replaces_visit_id=visit.pk).first(),
        open_wait=WaitRequest.objects.filter(patient_id=access.patient_id, state__in=('WAITING', 'OFFERED')).exists(),
        source_plan=current_plan(visit))
