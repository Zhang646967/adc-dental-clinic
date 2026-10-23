"""Bounded chronological search. The supplied reader retains admission rules."""
from datetime import timedelta


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
