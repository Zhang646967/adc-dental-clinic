"""Framework-free patient booking rules, synthetic coursework policy [D]."""
from datetime import datetime, timedelta
from adc_core.rules import RuleError, aware

BOOKING_MINUTES = 30
HORIZON_DAYS = 14

def validate_public_start(start: datetime, slot_start: datetime, slot_end: datetime, now: datetime):
    for item in (start, slot_start, slot_end, now): aware(item)
    end = start + timedelta(minutes=BOOKING_MINUTES)
    if start < now or start > now + timedelta(days=HORIZON_DAYS):
        raise RuleError("自助预约只开放未来14天；其他时间请联系前台。")
    delta = (start - slot_start).total_seconds()
    if delta < 0 or delta % (BOOKING_MINUTES * 60) != 0 or end > slot_end:
        raise RuleError("请选择系统公布的30分钟预约时段。实际治疗时长由诊所安排。")
    return end
