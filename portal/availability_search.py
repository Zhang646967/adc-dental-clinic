"""Bounded chronological search. The supplied reader retains admission rules."""
from datetime import timedelta


def availability_result(rows, *, service, day, dentist_id=None):
    """Explain a current lookup without treating every missing option as a full shift."""
    if rows:
        return 'AVAILABLE', ''

    from django.utils import timezone
    from portal.rules import HORIZON_DAYS
    from scheduling.models import AvailabilitySlot
    from scheduling.worklists import day_bounds

    today = timezone.localdate()
    first, _ = day_bounds(day or today)
    _, end = day_bounds(day or today + timedelta(days=HORIZON_DAYS))
    shifts = AvailabilitySlot.objects.filter(
        clinic_id=service.department.clinic_id, is_active=True, booking_paused=False,
        dentist__is_active=True, dentist__booking_services=service,
        starts_at__lt=end, ends_at__gt=max(first, timezone.now()),
    )
    if dentist_id:
        shifts = shifts.filter(dentist_id=dentist_id)
    period = '该日' if day else '未来14天'
    if shifts.exists():
        return 'NO_COMBINATION', f'{period}暂无符合就诊人与资源条件的组合，可换医师、日期或登记候补。'
    return 'NO_SCHEDULE', f'{period}暂无对应的已发布出诊，可换日期或登记候补。'


def future_options(reader, *, first_day, horizon_days=14, limit=80):
    if type(horizon_days) is not int or not 0 <= horizon_days <= 14:
        raise ValueError('Availability search horizon must be between 0 and 14 days.')
    if type(limit) is not int or not 1 <= limit <= 80:
        raise ValueError('Availability result limit must be between 1 and 80.')
    rows = []
    for offset in range(horizon_days + 1):
        rows.extend(reader(first_day + timedelta(days=offset)))
        if len(rows) >= limit:
            break
    return rows[:limit]
