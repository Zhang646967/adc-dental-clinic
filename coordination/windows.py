"""Authoritative rolling waitlist window policy. No database/UI dependencies."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

MIN_DURATION = timedelta(minutes=30)
HORIZON = timedelta(days=14)
BEIJING = ZoneInfo('Asia/Shanghai')

class WindowError(ValueError):
    def __init__(self, field, code, message):
        self.field, self.code = field, code
        super().__init__(message)

def validate_wait_window(start, end, *, now, minimum=MIN_DURATION):
    for name, value in (('earliest', start), ('latest', end), ('clock', now)):
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise WindowError(name, 'timezone', '请选择有效的北京时间；时间必须明确所属时区。')
    if end <= start:
        raise WindowError('latest', 'order', '最晚结束时间必须晚于最早开始时间。')
    if end - start < minimum:
        raise WindowError('latest', 'duration', f'结束时间至少比开始时间晚{int(minimum.total_seconds()//60)}分钟，才能放下一个完整的候补预约。')
    if start <= now:
        raise WindowError('earliest', 'past', '开始时间已经过去或刚刚到达，请重新选择未来时间。')
    if end > now + HORIZON:
        limit = (now + HORIZON).astimezone(BEIJING).strftime('%Y-%m-%d %H:%M')
        raise WindowError('latest', 'horizon', f'结束时间不能晚于 {limit}（北京时间，当前时刻之后14天）。')
    return start, end

@dataclass(frozen=True)
class WindowBounds:
    now: datetime
    min_start: datetime
    max_start: datetime
    max_end: datetime

    def as_dict(self):
        def wall(t): return t.astimezone(BEIJING).strftime('%Y-%m-%dT%H:%M')
        return {'server_now': self.now.astimezone(timezone.utc).isoformat(),
                'min_start': wall(self.min_start), 'max_start': wall(self.max_start),
                'max_end': wall(self.max_end), 'duration_minutes': 30,
                'choice_step_minutes': 15, 'timezone': 'Asia/Shanghai'}

def window_bounds(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Aware server time required')
    # Start must be STRICTLY later than current time, including an exact minute.
    low = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    high = (now + HORIZON).replace(second=0, microsecond=0)
    return WindowBounds(now, low, high - MIN_DURATION, high)
