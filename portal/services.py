"""Portal command boundaries never trust patient_id, dentist_id or price from a browser."""
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from adc_core.rules import RuleError, OCCUPYING_STATUSES
from accounts.policies import require_writable
from care.audit import emit
from patients.models import Patient
from scheduling.models import AvailabilitySlot, Visit
from adc_core.commands import business_errors, assert_revision as _assert_current
from scheduling.coordination import lock_slots as _lock_slots
from scheduling.services import create_visit_locked
from portal.models import BookingReceipt
from portal.policies import patient_access, check_authority, check_action_authority
from portal.rules import validate_public_start, BOOKING_MINUTES, HORIZON_DAYS

SALT = "adc.portal.booking.v04"

def public_options(user, clinic_id=None, day=None, service_id=None, dentist_id=None):
    access = patient_access(user)
    now = timezone.now()
    if access.delegated:
        if clinic_id:access.require_clinic(clinic_id)
        clinic_id=access.clinic_id
    if service_id:
        from scheduling.resource_candidates import candidates
        from scheduling.resources import service_for
        from scheduling.resource_models import BookingService
        service = BookingService.objects.select_related('department').get(pk=service_id,department__clinic__is_active=True)
        if clinic_id and clinic_id != service.department.clinic_id: raise RuleError('服务与所选诊所不一致，请重新选择。')
        if day:
            return candidates(clinic_id=service.department.clinic_id,service_id=service_id,day=day,
                patient_id=access.patient_id,dentist_id=dentist_id)
        from portal.availability_search import future_options
        return future_options(lambda selected_day:candidates(clinic_id=service.department.clinic_id,
            service_id=service_id,day=selected_day,patient_id=access.patient_id,dentist_id=dentist_id),
            first_day=timezone.localdate(),horizon_days=HORIZON_DAYS)
    from scheduling.resource_models import ResourcePolicy
    if clinic_id and ResourcePolicy.objects.filter(clinic_id=clinic_id).exists():raise RuleError('请先选择该诊所的预约服务，再查询可用组合。')
    slots = AvailabilitySlot.objects.filter(is_active=True, booking_paused=False, clinic__is_active=True,
        dentist__is_active=True, ends_at__gt=now, starts_at__lt=now+timedelta(days=HORIZON_DAYS)).select_related("clinic","dentist")
    slots = slots.exclude(clinic_id__in=ResourcePolicy.objects.values("clinic_id"))
    if clinic_id: slots = slots.filter(clinic_id=clinic_id)
    if dentist_id: slots = slots.filter(dentist_id=dentist_id)
    if day:
        from datetime import time
        from adc_core.rules import BUSINESS_TZ
        begin = datetime.combine(day, time.min, BUSINESS_TZ)
        slots = slots.filter(starts_at__lt=begin+timedelta(days=1), ends_at__gt=begin)
    rows = []
    for slot in slots.order_by("starts_at","id")[:60]:
        # A display snapshot, NOT a reservation. DB constraints recheck on confirmation.
        occupied = list(Visit.objects.filter(status__in=OCCUPYING_STATUSES,
            scheduled_start__lt=slot.ends_at, scheduled_end__gt=slot.starts_at)
            .filter(Q(dentist_id=slot.dentist_id) |
                    Q(patient_id=access.patient_id))
            .values_list("scheduled_start","scheduled_end"))
        from coordination.models import WaitOffer
        occupied.extend(WaitOffer.objects.filter(state='PENDING',expires_at__gt=now,
            starts_at__lt=slot.ends_at,ends_at__gt=slot.starts_at).filter(
            Q(slot__dentist_id=slot.dentist_id)|Q(request__patient_id=access.patient_id)).values_list('starts_at','ends_at'))
        step = timedelta(minutes=BOOKING_MINUTES)
        lower = max(slot.starts_at, now)
        if day:
            lower = max(lower, begin)
        skipped = max(0, int((lower-slot.starts_at).total_seconds() // step.total_seconds()))
        start = slot.starts_at + skipped*step
        if start < lower:
            start += step
        upper = min(slot.ends_at, now+timedelta(days=HORIZON_DAYS)+step)
        if day:
            upper = min(upper, begin+timedelta(days=1))
        while start+step <= upper:
            end = start+timedelta(minutes=BOOKING_MINUTES)
            if start >= now and start <= now+timedelta(days=HORIZON_DAYS) and (not day or timezone.localtime(start).date()==day) and not any(start<b and a<end for a,b in occupied):
                rows.append({"slot":slot,"start":start,"end":end,"start_iso":start.isoformat()})
                if len(rows)>=80: return rows
            start = end
    return rows

def preview_booking(*, user, slot_id, start, service_id=None):
    access = patient_access(user)
    slot = AvailabilitySlot.objects.select_related("clinic","dentist").get(pk=slot_id,
        is_active=True, booking_paused=False, clinic__is_active=True, dentist__is_active=True)
    access.require_clinic(slot.clinic_id)
    from scheduling.resources import policy,choose_bundle,service_for
    from adc_core.rules import validate_slot
    bundle=None
    if policy(slot.clinic_id):
        service=service_for(slot.clinic_id,service_id)
        end=start+timedelta(minutes=service.duration_minutes)
        _resource_public_time(start,end,slot)
        from coordination.reservations import assert_free
        assert_free(access.patient_id,slot.dentist_id,start,end)
        bundle=choose_bundle(slot=slot,start=start,end=end,service_id=service_id)
    else:end = validate_public_start(start, slot.starts_at, slot.ends_at, timezone.now())
    data = {"uid":user.pk,"access":access.pk,"slot":slot.pk,"start":start.isoformat(),"nonce":str(uuid4()),"intake_revision":slot.intake_revision}
    ctx=getattr(user,'_adc_workspace',None)
    data.update(service=service_id,resources=bundle,end=end.isoformat(),authority=access.stamp,
        context=str(ctx.pk) if ctx else None,context_revision=ctx.revision if ctx else None)
    return slot, end, signing.dumps(data, salt=SALT, compress=True)

def _read_token(token, user):
    try:
        data = signing.loads(token, salt=SALT, max_age=600)
        if type(data) is not dict or data.get("uid") != user.pk: raise ValueError()
        UUID(data["nonce"])
        return data
    except (signing.BadSignature, ValueError, KeyError, TypeError) as exc:
        raise RuleError("确认页已失效或不属于当前账号，请重新选择时段。") from exc

@business_errors
@transaction.atomic
def confirm_booking(*, actor, token, patient_request='', require_published_service=False):
    require_writable(actor)
    access = patient_access(actor, lock=True)
    data = _read_token(token, actor)
    if data.get("access") != access.pk: raise RuleError("患者端授权已变化，请重新确认。")
    check_authority(access,data.get('authority'))
    ctx=getattr(actor,'_adc_workspace',None)
    if (data.get('context'),data.get('context_revision')) != ((str(ctx.pk),ctx.revision) if ctx else (None,None)):
        raise RuleError('就诊人或工作台已切换，请重新核对预约。')
    receipt = BookingReceipt.objects.filter(nonce=data["nonce"], **access.receipt_fields).select_related("visit").first()
    if receipt: return receipt.visit
    from scheduling.service_content import patient_request as normalize_request
    try:reason=normalize_request(patient_request)
    except ValueError as exc:raise RuleError(str(exc)) from exc
    slot = _lock_slots([data["slot"]])[data["slot"]]
    access.require_clinic(slot.clinic_id)
    revision = data.get('intake_revision', 0)  # Legacy previews valid only before intake has ever changed.
    if type(revision) is not int or revision != slot.intake_revision:
        raise RuleError('出诊接收状态已变化，请重新选择并核对，原确认页不能继续使用。')
    patient = Patient.objects.select_for_update().get(pk=access.patient_id, is_active=True)
    try: start = datetime.fromisoformat(data["start"])
    except (ValueError, TypeError) as exc: raise RuleError("预约时间格式失效。") from exc
    from scheduling.resources import policy
    if policy(slot.clinic_id):
        if not data.get('resources'):raise RuleError('本店已启用诊疗资源，请重新选择服务和时间。')
        end=datetime.fromisoformat(data['end']);_resource_public_time(start,end,slot)
    else:end = validate_public_start(start, slot.starts_at, slot.ends_at, timezone.now())
    visit = create_visit_locked(actor=actor, patient=patient, slot=slot, start=start, end=end,
                       chief_complaint=reason or "患者端预约；具体需求由接诊人员确认。",
                       service_id=data.get("service"),resource_snapshot=data.get("resources"),
                       require_published_service=require_published_service)
    BookingReceipt.objects.create(nonce=data["nonce"], visit=visit, **access.receipt_fields)
    emit(actor, "PORTAL_BOOKING_CONFIRMED", visit, visit=visit, summary={"source":"patient_portal"})
    return visit

@business_errors
@transaction.atomic
def cancel_booking(*, actor, visit_id, expected_version, reason, authority=None):
    require_writable(actor)
    access = patient_access(actor, lock=True)
    check_action_authority(access,authority)
    preview = access.scope(Visit.objects.all()).get(pk=visit_id)
    _lock_slots([preview.availability_slot_id])
    from coordination.reservations import lock_resources
    from scheduling.resources import lock_physical
    lock_resources(patients=[preview.patient_id],dentists=[preview.dentist_id]);lock_physical(preview.clinic_id)
    visit = Visit.objects.select_for_update().get(pk=visit_id, patient_id=access.patient_id)
    _assert_current(visit, expected_version)
    if visit.status != "SCHEDULED" or visit.scheduled_start <= timezone.now():
        raise RuleError("仅可自助取消尚未开始的预约；其他情况请联系前台。")
    if not isinstance(reason,str) or not 1 <= len(reason.strip()) <= 500:
        raise RuleError("请填写1至500字的取消原因。")
    from scheduling.resources import release_visit_locked
    release_visit_locked(visit, 'PORTAL_CANCELLED')
    visit.status="CANCELLED";visit.cancellation_party="PATIENT";visit.cancellation_reason=reason.strip()
    visit.lock_version+=1
    visit.save(update_fields=["status","cancellation_party","cancellation_reason","lock_version"])
    emit(actor,"PORTAL_CANCELLED",visit,visit=visit,reason=reason.strip(),summary={"status":visit.status})
    return visit


def _resource_public_time(start,end,slot):
    from adc_core.rules import validate_slot
    now=timezone.now()
    validate_slot(start,end,slot.starts_at,slot.ends_at,now)
    if start>now+timedelta(days=HORIZON_DAYS) or (start-slot.starts_at).total_seconds()%900:
        raise RuleError('请选择未来十四天内、与出诊起点按十五分钟对齐的时间。')
