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
from portal.policies import patient_access
from portal.rules import validate_public_start, BOOKING_MINUTES, HORIZON_DAYS

SALT = "adc.portal.booking.v04"

def public_options(user, clinic_id=None, day=None):
    access = patient_access(user)
    now = timezone.now()
    slots = AvailabilitySlot.objects.filter(is_active=True, booking_paused=False, clinic__is_active=True,
        dentist__is_active=True, ends_at__gt=now, starts_at__lt=now+timedelta(days=HORIZON_DAYS)).select_related("clinic","dentist")
    if clinic_id: slots = slots.filter(clinic_id=clinic_id)
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

def preview_booking(*, user, slot_id, start):
    access = patient_access(user)
    slot = AvailabilitySlot.objects.select_related("clinic","dentist").get(pk=slot_id,
        is_active=True, booking_paused=False, clinic__is_active=True, dentist__is_active=True)
    end = validate_public_start(start, slot.starts_at, slot.ends_at, timezone.now())
    data = {"uid":user.pk,"access":access.pk,"slot":slot.pk,"start":start.isoformat(),"nonce":str(uuid4()),"intake_revision":slot.intake_revision}
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
def confirm_booking(*, actor, token):
    require_writable(actor)
    access = patient_access(actor, lock=True)
    data = _read_token(token, actor)
    if data.get("access") != access.pk: raise RuleError("患者端授权已变化，请重新确认。")
    receipt = BookingReceipt.objects.filter(nonce=data["nonce"], access=access).select_related("visit").first()
    if receipt: return receipt.visit
    slot = _lock_slots([data["slot"]])[data["slot"]]
    revision = data.get('intake_revision', 0)  # Legacy previews valid only before intake has ever changed.
    if type(revision) is not int or revision != slot.intake_revision:
        raise RuleError('出诊接收状态已变化，请重新选择并核对，原确认页不能继续使用。')
    patient = Patient.objects.select_for_update().get(pk=access.patient_id, is_active=True)
    try: start = datetime.fromisoformat(data["start"])
    except (ValueError, TypeError) as exc: raise RuleError("预约时间格式失效。") from exc
    end = validate_public_start(start, slot.starts_at, slot.ends_at, timezone.now())
    visit = create_visit_locked(actor=actor, patient=patient, slot=slot, start=start, end=end,
                       chief_complaint="患者端预约；具体需求由接诊人员确认。")
    BookingReceipt.objects.create(nonce=data["nonce"], access=access, visit=visit)
    emit(actor, "PORTAL_BOOKING_CONFIRMED", visit, visit=visit, summary={"source":"patient_portal"})
    return visit

@business_errors
@transaction.atomic
def cancel_booking(*, actor, visit_id, expected_version, reason):
    require_writable(actor)
    access = patient_access(actor, lock=True)
    preview = Visit.objects.get(pk=visit_id, patient_id=access.patient_id)
    _lock_slots([preview.availability_slot_id])
    visit = Visit.objects.select_for_update().get(pk=visit_id, patient_id=access.patient_id)
    _assert_current(visit, expected_version)
    if visit.status != "SCHEDULED" or visit.scheduled_start <= timezone.now():
        raise RuleError("仅可自助取消尚未开始的预约；其他情况请联系前台。")
    if not isinstance(reason,str) or not 1 <= len(reason.strip()) <= 500:
        raise RuleError("请填写1至500字的取消原因。")
    visit.status="CANCELLED";visit.cancellation_party="PATIENT";visit.cancellation_reason=reason.strip()
    visit.lock_version+=1
    visit.save(update_fields=["status","cancellation_party","cancellation_reason","lock_version"])
    emit(actor,"PORTAL_CANCELLED",visit,visit=visit,reason=reason.strip(),summary={"status":visit.status})
    return visit
