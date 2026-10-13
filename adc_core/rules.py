"""Framework-free rules actually used by the application; [D] v0.1–v0.3.
No clinical advice or real-world financial policy is encoded here.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import StrEnum
from typing import Iterable
from zoneinfo import ZoneInfo

class RuleError(ValueError):
    """An input or state violates a documented business rule."""

class VisitStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CLOSED_NO_TREATMENT = "CLOSED_NO_TREATMENT"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    RESCHEDULED = "RESCHEDULED"

STATUS_LABELS = {
    "SCHEDULED": "已预约", "CHECKED_IN": "已到诊", "COMPLETED": "治疗完成",
    "CLOSED_NO_TREATMENT": "无治疗关闭", "CANCELLED": "已取消",
    "NO_SHOW": "已爽约", "RESCHEDULED": "已改期替代",
}
STATUS_CHOICES = tuple(STATUS_LABELS.items())
ATTENDED_STATUSES = ("CHECKED_IN", "COMPLETED", "CLOSED_NO_TREATMENT")
CLOSED_STATUSES = ("COMPLETED", "CLOSED_NO_TREATMENT")
OCCUPYING_STATUSES = ("SCHEDULED", "CHECKED_IN", "COMPLETED", "CLOSED_NO_TREATMENT")
ROLE_CHOICES = (("FRONT_DESK", "前台"), ("DENTIST", "牙医"), ("MANAGER", "诊所主管"),
                ("HQ", "总部管理"), ("FINANCE", "财务"), ("SYSADMIN", "系统管理员"))
SCOPE_CHOICES = (("CLINIC", "诊所"), ("SELF_DENTIST", "本人接诊"),
                 ("CHAIN", "全链"), ("TECHNICAL", "技术管理"))
ROLE_SCOPE = {"FRONT_DESK": "CLINIC", "MANAGER": "CLINIC", "DENTIST": "SELF_DENTIST",
              "HQ": "CHAIN", "FINANCE": "CHAIN", "SYSADMIN": "TECHNICAL"}
TRANSITIONS = {
    "SCHEDULED": {"CHECKED_IN", "CANCELLED", "NO_SHOW", "RESCHEDULED"},
    "CHECKED_IN": {"COMPLETED", "CLOSED_NO_TREATMENT"},
}
BUSINESS_TZ = ZoneInfo("Asia/Shanghai")
CENT = Decimal("0.01")

def aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise RuleError("时间必须包含时区。")
    return value

def validate_interval(start: datetime, end: datetime) -> None:
    if aware(start) >= aware(end):
        raise RuleError("结束时间必须晚于开始时间。")

def overlaps(a: datetime, b: datetime, c: datetime, d: datetime) -> bool:
    validate_interval(a, b); validate_interval(c, d)
    return a < d and c < b

def validate_slot(start: datetime, end: datetime, slot_start: datetime,
                  slot_end: datetime, now: datetime) -> None:
    validate_interval(start, end); validate_interval(slot_start, slot_end)
    if start < aware(now):
        raise RuleError("普通预约不能创建过去时段。")
    if start < slot_start or end > slot_end:
        raise RuleError("预约必须完整处于所选出诊时段内。")

def validate_transition(old: str, new: str) -> None:
    if new not in TRANSITIONS.get(old, set()):
        raise RuleError("该状态变化不允许；终态更正须走独立审核流程。")

def validate_state(status: str, attended: bool, attended_at: datetime | None,
                   completed_at: datetime | None) -> None:
    if status not in STATUS_LABELS:
        raise RuleError("未知就诊状态。")
    expected = status in ATTENDED_STATUSES
    if type(attended) is not bool or attended != expected:
        raise RuleError("状态与到诊标志不一致。")
    if (attended_at is not None) != expected:
        raise RuleError("到诊时间与到诊事实不一致。")
    if attended_at is not None:
        aware(attended_at)
    closed = status in CLOSED_STATUSES
    if (completed_at is not None) != closed:
        raise RuleError("完成时间与闭合状态不一致。")
    if closed and aware(completed_at) < attended_at:
        raise RuleError("完成时间不能早于到诊时间。")

def validate_allergies(status: str, item_ids: Iterable[int]) -> tuple[int, ...]:
    ids = tuple(sorted(set(item_ids)))
    if status not in ("UNKNOWN", "NO_KNOWN", "KNOWN"):
        raise RuleError("过敏知识状态无效。")
    if (status == "KNOWN") != bool(ids):
        raise RuleError("已知过敏须有项目；未知或无已知过敏不能带有效项目。")
    return ids

def validate_birth(birth: date, today: date) -> None:
    if birth > today:
        raise RuleError("出生日期不能晚于当前业务日。")

def decimal_value(value: str | Decimal | int, places: int, max_value: Decimal) -> Decimal:
    if isinstance(value, (float, bool)):
        raise RuleError("金额/数量必须使用字符串或精确十进制，不能使用浮点数。")
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RuleError("无效数值。") from exc
    if not number.is_finite() or number < 0 or number > max_value:
        raise RuleError("数值必须有限、非负且不超过字段上限。")
    step = Decimal(1).scaleb(-places)
    if number != number.quantize(step):
        raise RuleError(f"最多允许 {places} 位有效小数。")
    return number

def line_amount(quantity: str | Decimal | int, price: str | Decimal | int,
                price_reason: str = "") -> Decimal:
    q = decimal_value(quantity, 3, Decimal("999999999.999"))
    p = decimal_value(price, 2, Decimal("9999999999.99"))
    if q <= 0:
        raise RuleError("治疗数量必须大于零。")
    if p == 0 and not price_reason.strip():
        raise RuleError("零价格必须有授权后的原因记录。")
    result = (q * p).quantize(CENT, rounding=ROUND_HALF_UP)
    if result > Decimal("99999999999999.99"):
        raise RuleError("行金额超过存储上限。")
    return result

def total_amount(lines: Iterable[Decimal]) -> Decimal:
    result = sum((decimal_value(v, 2, Decimal("99999999999999.99")) for v in lines), Decimal(0))
    if result > Decimal("99999999999999.99"):
        raise RuleError("总金额超过存储上限。")
    return result.quantize(CENT)

def quarter_bounds(year: int, quarter: int) -> tuple[datetime, datetime]:
    if not 1900 <= year <= 9998 or quarter not in (1, 2, 3, 4):
        raise RuleError("年份或季度无效。")
    month = 3 * quarter - 2
    start = datetime(year, month, 1, tzinfo=BUSINESS_TZ)
    end = datetime(year + 1, 1, 1, tzinfo=BUSINESS_TZ) if quarter == 4 else datetime(year, month + 3, 1, tzinfo=BUSINESS_TZ)
    return start, end

def validate_role_scope(role: str, scope_kind: str, clinic_id: int | None,
                        dentist_id: int | None) -> None:
    if ROLE_SCOPE.get(role) != scope_kind:
        raise RuleError("角色与范围类型不匹配。")
    if (scope_kind == "CLINIC") != (clinic_id is not None):
        raise RuleError("诊所范围必须且只能指定一家诊所。")
    if role == "DENTIST" and dentist_id is None:
        raise RuleError("牙医账号需要关联真实的演示牙医档案。")
