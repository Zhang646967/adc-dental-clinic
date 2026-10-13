"""Pure read-model contract: no Django, database writes, model calls, or auto-confirmation.

The result describes saved facts at an observation time, not the fate of an arbitrary
HTTP request. An accepted offer remains historical even after the booking is cancelled.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

CONTRACT_VERSION = "WAIT-RESULT-09A.1"

@dataclass(frozen=True)
class VisitFact:
    id: int
    number: str
    patient_id: int
    clinic_id: int
    dentist_id: int
    start: datetime
    end: datetime
    status: str

@dataclass(frozen=True)
class OfferFact:
    id: int
    state: str
    dentist_id: int
    clinic_id: int
    start: datetime
    end: datetime
    expires: datetime
    visit: Optional[VisitFact] = None

@dataclass(frozen=True)
class WaitFact:
    id: int
    patient_id: int
    clinic_id: int
    state: str
    earliest: datetime
    latest: datetime
    offers: Tuple[OfferFact, ...] = ()  # only PENDING or ACCEPTED, one SELECT snapshot

@dataclass(frozen=True)
class Assessment:
    code: str
    title: str
    explanation: str
    next_step: str
    target: str = "waitlist"
    target_id: Optional[int] = None
    visit: Optional[VisitFact] = None
    offer: Optional[OfferFact] = None


def _aware(*times):
    return all(isinstance(t, datetime) and t.utcoffset() is not None for t in times)


def inconsistent():
    return Assessment("INCONSISTENT", "关联记录需要工作人员核对",
        "当前候补、邀约和预约的关联未能一致核对。不能据此确认办理成功，也不要重复创建预约。",
        "请联系前台核对这条候补；保留原记录，不自行补写或删除。")


def assess_wait(fact: WaitFact, now: datetime) -> Assessment:
    """Return deterministic, allowlisted guidance using only authorized saved facts."""
    if not _aware(now, fact.earliest, fact.latest) or fact.earliest >= fact.latest:
        return inconsistent()
    if len(fact.offers) > 2:
        return inconsistent()
    pending = [o for o in fact.offers if o.state == "PENDING"]
    accepted = [o for o in fact.offers if o.state == "ACCEPTED"]
    if len(pending) + len(accepted) != len(fact.offers):
        return inconsistent()
    if len(pending) > 1 or len(accepted) > 1 or (pending and accepted):
        return inconsistent()
    for o in fact.offers:
        if not _aware(o.start, o.end, o.expires) or not (fact.earliest <= o.start < o.end <= fact.latest):
            return inconsistent()
        if o.clinic_id != fact.clinic_id or o.expires > o.start:
            return inconsistent()
    # Evaluate accepted history BEFORE expiry. Expiry never erases a saved booking.
    if fact.state == "BOOKED":
        if len(accepted) != 1 or pending:
            return inconsistent()
        o = accepted[0]; v = o.visit
        if v is None or not v.number or not _aware(v.start, v.end):
            return inconsistent()
        if (v.patient_id, v.clinic_id, v.dentist_id, v.start, v.end) != (
                fact.patient_id, fact.clinic_id, o.dentist_id, o.start, o.end):
            return inconsistent()
        messages = {
            "SCHEDULED": ("BOOKING_FOUND", "已核对到对应的正式预约", "这条候补已经转成预约，当前状态为已预约。请核对下方编号和时间，不要再次接受邀约。"),
            "CHECKED_IN": ("CHECKED_IN", "对应预约已登记到诊", "候补转换已完成；当前预约已到诊。到诊不代表治疗完成或已付款。"),
            "COMPLETED": ("VISIT_COMPLETED", "对应就诊显示治疗完成", "候补转换已完成。当前就诊状态为治疗完成；本核对不检查账单金额或付款。"),
            "CLOSED_NO_TREATMENT": ("VISIT_CLOSED", "对应就诊显示无治疗关闭", "候补转换已完成；之后以无治疗方式关闭。本核对不评价诊疗或核实付款。"),
            "CANCELLED": ("BOOKING_CANCELLED", "候补曾转预约，但该预约后来已取消", "已转预约是历史事实，不能据此认定现在仍有有效安排。"),
            "RESCHEDULED": ("BOOKING_REPLACED", "原预约后来已被改期替代", "本条候补关联原预约。新的有效时间请到预约记录核对；不要再次接受旧邀约。"),
            "NO_SHOW": ("BOOKING_NO_SHOW", "对应预约当前已标为爽约", "候补转换曾经完成，但当前已不是待就诊预约。需要安排新时间请联系前台。"),
        }
        if v.status not in messages:
            return inconsistent()
        code, title, explanation = messages[v.status]
        return Assessment(code, title, explanation, "打开对应预约详情，核对当前状态与完整时间。", "visit", v.id, v, o)
    if accepted:
        return inconsistent()
    if fact.state == "OFFERED":
        if len(pending) != 1 or pending[0].visit is not None:
            return inconsistent()
        o = pending[0]
        if now >= o.expires or now >= o.start:
            return Assessment("OFFER_EXPIRED", "该邀约已超过确认期限",
                "候补记录仍可能显示等待确认，但此邀约现在不能首次接受；它不会自动生成预约。",
                "请联系前台回收过期邀约并重新协调；本核对不会延长期限。", offer=o)
        return Assessment("NEEDS_CONFIRMATION", "有一份邀约，仍需你明确确认",
            "已发出邀约不等于已经预约。本核对没有替你接受或拒绝。",
            "打开邀约页面，核对诊所、牙医、时间及截止后，自行决定是否接受。", "offer", o.id, offer=o)
    if pending:
        return inconsistent()
    if fact.state == "WITHDRAWN":
        return Assessment("WITHDRAWN", "这条候补已经退出", "退出记录保留；本核对不取消其他正式预约。", "需要新的安排时，从候补列表或预约时间重新办理。")
    if fact.state == "WAITING":
        if now >= fact.latest:
            return Assessment("WINDOW_PASSED", "登记的可接受时间范围已结束", "这条候补还未转为预约；原时间范围已经过去。", "请退出这条旧候补，再选择新的合法时间范围；本核对不自动退出。")
        return Assessment("WAITING", "候补已登记，尚待安排", "当前没有待确认邀约，也未核对到由这条候补产生的预约。", "在候补列表查看后续邀约，或联系前台协调；不要当作已经预约。")
    return inconsistent()
