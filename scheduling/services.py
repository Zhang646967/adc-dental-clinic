"""UC-03/04/05/14 command boundaries. All writes re-check authorization."""
from functools import wraps
from django.db import IntegrityError, OperationalError, transaction, connection
from django.db.models import F
from django.utils import timezone
from accounts.policies import lock_clinic_grant, require_writable
from adc_core.rules import RuleError, validate_interval, validate_slot, validate_transition
from care.audit import emit
from patients.models import Patient
from registry.models import Clinic, Dentist
from scheduling.models import AvailabilitySlot, Visit, VisitRequest

from adc_core.commands import business_errors, assert_revision as _assert_current
from scheduling.coordination import lock_slots as _lock_slots


def _slot_ids_for_visit(visit_id):
    return Visit.objects.only("availability_slot_id").get(pk=visit_id).availability_slot_id



# Internal public command used by authorized staff/portal coordinators.
# PRE: active transaction, authorized actor/patient, and slot row already locked.
# This helper is not an HTTP endpoint and does not grant access by itself.
def create_visit_locked(*, actor, patient, slot, start, end, chief_complaint="", special_needs="", replaces=None, honor_offer_id=None, service_id=None, resource_snapshot=None, require_published_service=False):
    if not connection.in_atomic_block:
        raise RuntimeError('create_visit_locked requires a transaction and the source-slot lock')
    from scheduling.intake_rules import require_new_admission, validate_reserved_offer, IntakeError
    ignore_offer = None
    if honor_offer_id is not None:
        # Not a client-provided bypass. Re-read the locked promise and check ALL exact fields.
        if (type(honor_offer_id) is not int or honor_offer_id <= 0 or
                replaces is not None and (replaces.status != 'RESCHEDULED' or
                    replaces.patient_id != patient.pk or replaces.clinic_id != slot.clinic_id)):
            raise RuleError('原邀约编号或预约来源无效。')
        from coordination.models import WaitOffer
        from coordination.policies import require_owner_or_front
        promise = WaitOffer.objects.select_for_update().get(pk=honor_offer_id)
        require_owner_or_front(actor, promise.request)
        try:
            validate_reserved_offer(slot_id=slot.pk, patient_id=patient.pk, clinic_id=slot.clinic_id,
                start=start, end=end, offer_slot_id=promise.slot_id,
                offer_patient_id=promise.request.patient_id, offer_clinic_id=promise.request.clinic_id,
                offer_start=promise.starts_at, offer_end=promise.ends_at, expires_at=promise.expires_at,
                now=timezone.now(), offer_state=promise.state, request_state=promise.request.state,
                visit_id=promise.visit_id)
        except IntakeError as exc:
            raise RuleError(str(exc)) from exc
        ignore_offer = promise.pk
    else:
        try:
            require_new_admission(active=slot.is_active, paused=slot.booking_paused)
        except IntakeError as exc:
            raise RuleError(str(exc)) from exc
    if not patient.is_active or not slot.is_active:
        raise RuleError("患者或出诊时段已停用。")
    if not Clinic.objects.filter(pk=slot.clinic_id, is_active=True).exists() or not Dentist.objects.filter(pk=slot.dentist_id, is_active=True).exists():
        raise RuleError("诊所或牙医已停用。")
    validate_slot(start, end, slot.starts_at, slot.ends_at, timezone.now())
    from coordination.reservations import lock_resources, assert_free
    lock_resources(patients=[patient.pk], dentists=[slot.dentist_id])
    assert_free(patient.pk, slot.dentist_id, start, end, ignore_offer=ignore_offer)
    from scheduling.resources import choose_bundle, claim_locked, accept_offer_resources_locked, validate_reserved_resources_locked
    if honor_offer_id is not None:
        validate_reserved_resources_locked(promise)
        bundle = None
    else:
        bundle = choose_bundle(slot=slot, start=start, end=end, service_id=service_id,
            expected=resource_snapshot, locked=True)
    if require_published_service:
        # Native new-booking policy, after shared physical locks and before writes.
        # Existing reschedules, held offers and receipt replays keep their contracts.
        from portal.service_catalogue import require_self_service
        require_self_service(service_id, clinic_id=slot.clinic_id)
    v = Visit.objects.create(patient=patient, dentist_id=slot.dentist_id, clinic_id=slot.clinic_id,
                             availability_slot=slot, scheduled_start=start, scheduled_end=end,
                             chief_complaint=chief_complaint, special_needs=special_needs, replaces_visit=replaces)
    if honor_offer_id is not None:
        accept_offer_resources_locked(actor, promise, v)
    else:
        claim_locked(actor=actor, snapshot=bundle, start=start, end=end, visit=v)
    emit(actor, "VISIT_CREATED", v, visit=v, summary={"clinic_id": v.clinic_id, "status": v.status})
    return v

@business_errors
@transaction.atomic
def create_slot(*, actor, clinic_id, dentist_id, start, end, operation_id=None):
    lock_clinic_grant(actor, clinic_id, roles=("FRONT_DESK",))
    validate_interval(start, end)
    if start < timezone.now():
        raise RuleError("新出诊安排必须位于未来。")
    clinic = Clinic.objects.get(pk=clinic_id, is_active=True)
    dentist = Dentist.objects.get(pk=dentist_id, is_active=True)
    obj = AvailabilitySlot.objects.create(clinic=clinic, dentist=dentist, starts_at=start, ends_at=end)
    emit(actor, "SLOT_CREATED", obj, summary={"clinic_id": clinic_id, "dentist_id": dentist_id,
        **({'operation':operation_id} if operation_id else {})})
    return obj

@business_errors
@transaction.atomic
def create_appointment(*, actor, patient_no, slot_id, start, end, chief_complaint="", special_needs="", requests=(), service_id=None, resource_snapshot=None):
    require_writable(actor)
    preview = AvailabilitySlot.objects.only("clinic_id").get(pk=slot_id)
    lock_clinic_grant(actor, preview.clinic_id)
    slot = _lock_slots([slot_id])[slot_id]
    # Re-check the clinic after locking; don't trust the earlier preview or form.
    lock_clinic_grant(actor, slot.clinic_id)
    patient = Patient.objects.get(patient_no=patient_no, is_active=True)
    v = create_visit_locked(actor=actor, patient=patient, slot=slot, start=start, end=end,
                   chief_complaint=chief_complaint, special_needs=special_needs, service_id=service_id, resource_snapshot=resource_snapshot)
    for text in requests:
        text = str(text).strip()
        if not text or len(text) > 500:
            raise RuleError("治疗意向必须是1至500字的非空文本。")
        VisitRequest.objects.create(visit=v, description=text)
    return v

@business_errors
@transaction.atomic
def change_appointment(*, actor, visit_id, expected_version, action, reason="", party=""):
    require_writable(actor)
    preview = Visit.objects.only("clinic_id", "availability_slot_id", "patient_id", "dentist_id").get(pk=visit_id)
    lock_clinic_grant(actor, preview.clinic_id)
    _lock_slots([preview.availability_slot_id])
    from coordination.reservations import lock_resources
    from scheduling.resources import lock_physical
    lock_resources(patients=[preview.patient_id], dentists=[preview.dentist_id])
    lock_physical(preview.clinic_id)
    v = Visit.objects.select_for_update().get(pk=visit_id)
    lock_clinic_grant(actor, v.clinic_id)
    _assert_current(v, expected_version)
    target = {"check_in": "CHECKED_IN", "cancel": "CANCELLED", "no_show": "NO_SHOW"}.get(action)
    if target is None:
        raise RuleError("当前版本没有开放该业务命令。")
    validate_transition(v.status, target)
    now = timezone.now()
    if target == "NO_SHOW":
        if now < v.scheduled_end:
            raise RuleError("尚未达到预约结束时间，不能认定爽约。")
        if not reason.strip():
            raise RuleError("请记录核实未到诊的说明。")
    if target == "CANCELLED":
        if party not in ("PATIENT", "CLINIC") or not reason.strip():
            raise RuleError("取消必须指定发起方和原因。")
        v.cancellation_party, v.cancellation_reason = party, reason.strip()
    from scheduling.resources import check_in_resources_locked, release_visit_locked
    if target == "CHECKED_IN":
        check_in_resources_locked(v)
        v.attended, v.attended_at = True, now
    if target in ('CANCELLED', 'NO_SHOW'):
        release_visit_locked(v, target)
    v.status = target
    v.lock_version += 1
    v.save(update_fields=["status", "attended", "attended_at", "cancellation_party", "cancellation_reason", "lock_version"])
    emit(actor, "VISIT_" + target, v, visit=v, reason=reason, summary={"status": target}, occurred_at=now)
    return v

@business_errors
@transaction.atomic
def reschedule(*, actor, visit_id, expected_version, new_slot_id, start, end, reason, service_id=None, resource_snapshot=None):
    require_writable(actor)
    if not reason.strip():
        raise RuleError("改期必须记录原因。")
    preview = Visit.objects.only("clinic_id", "availability_slot_id", "patient_id", "dentist_id").get(pk=visit_id)
    target = AvailabilitySlot.objects.only("clinic_id").get(pk=new_slot_id)
    for clinic_id in sorted({preview.clinic_id, target.clinic_id}):
        lock_clinic_grant(actor, clinic_id)
    slots = _lock_slots([preview.availability_slot_id, new_slot_id])
    from coordination.reservations import lock_resources
    from scheduling.resources import lock_physical
    lock_resources(patients=[preview.patient_id], dentists=[s.dentist_id for s in slots.values()])
    for clinic_id in sorted({s.clinic_id for s in slots.values()}): lock_physical(clinic_id)
    old = Visit.objects.select_for_update().get(pk=visit_id)
    slot = slots[new_slot_id]
    lock_clinic_grant(actor, old.clinic_id)
    lock_clinic_grant(actor, slot.clinic_id)
    return reschedule_visit_locked(actor=actor, old=old, slot=slot, expected_version=expected_version,
        start=start, end=end, reason=reason, service_id=service_id, resource_snapshot=resource_snapshot)


def reschedule_visit_locked(*, actor, old, slot, expected_version, start, end, reason,
                            service_id=None, resource_snapshot=None, honor_offer_id=None):
    """Shared atomic effect; callers own authorization and ordered source/resource locks."""
    if not connection.in_atomic_block:
        raise RuntimeError('Rescheduling requires an authorized locked transaction')
    _assert_current(old, expected_version)
    validate_transition(old.status, "RESCHEDULED")
    if not isinstance(reason, str) or not reason.strip():
        raise RuleError('改期必须记录原因。')
    # Release only within this transaction; any failure restores the original booking.
    from scheduling.resources import release_visit_locked, current_plan
    original_plan = current_plan(old)
    if service_id is None and original_plan: service_id = original_plan.service_id
    release_visit_locked(old, 'RESCHEDULED')
    old.status = "RESCHEDULED"
    old.lock_version += 1
    old.save(update_fields=["status", "lock_version"])
    new = create_visit_locked(actor=actor, patient=old.patient, slot=slot, start=start, end=end,
                    chief_complaint=old.chief_complaint, special_needs=old.special_needs, replaces=old,
                    service_id=service_id, resource_snapshot=resource_snapshot, honor_offer_id=honor_offer_id)
    VisitRequest.objects.bulk_create([VisitRequest(visit=new, description=r.description, treatment_type_id=r.treatment_type_id) for r in old.requests.all()])
    emit(actor, "VISIT_RESCHEDULED", old, visit=old, reason=reason, summary={"replacement_id": new.pk})
    return new
