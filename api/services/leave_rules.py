"""
api/services/leave_rules.py
=============================================================================
Business rules for technician leave requests.

Rules used by the console command, future mobile endpoint, and supervisor
approval API:
    * Earliest leave start is operating roll-date + 14 days.
    * Maximum leave interval is 7 calendar days, inclusive.
    * This feature is intended for maintenance and callback technicians.
=============================================================================
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from django.utils import timezone

MIN_NOTICE_DAYS = 14
MAX_LEAVE_DAYS = 7


def get_operating_date(request=None) -> date:
    """Return the simulation/admin roll-date, falling back to local date."""
    try:
        from api.active_day import get_active_date
        return get_active_date(request) if request is not None else get_active_date()
    except Exception:
        return timezone.localdate()


def parse_iso_date(value, *, field_name: str = "date") -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not value:
        raise ValueError(f"{field_name} is required in YYYY-MM-DD format.")
    try:
        return date.fromisoformat(str(value))
    except Exception:
        raise ValueError(f"{field_name} must be YYYY-MM-DD.")


def inclusive_days(start_date: date, end_date: date) -> int:
    return (end_date - start_date).days + 1


def validate_leave_window(
    start_date: date,
    end_date: date,
    *,
    today: Optional[date] = None,
    enforce_notice: bool = True,
) -> None:
    """Raise ValueError if the requested leave window breaks the rules."""
    today = today or get_operating_date()

    if end_date < start_date:
        raise ValueError("Leave end_date cannot be before start_date.")

    length = inclusive_days(start_date, end_date)
    if length < 1:
        raise ValueError("Leave interval must contain at least one day.")
    if length > MAX_LEAVE_DAYS:
        raise ValueError(f"Leave interval can be maximum {MAX_LEAVE_DAYS} days.")

    earliest = today + timedelta(days=MIN_NOTICE_DAYS)
    if enforce_notice and start_date < earliest:
        raise ValueError(
            f"Leave must start at least {MIN_NOTICE_DAYS} days after the operating date. "
            f"Operating date is {today.isoformat()}, earliest allowed start is {earliest.isoformat()}."
        )


def validate_instant_leave_window(
    start_date: date,
    end_date: date,
    *,
    today: Optional[date] = None,
) -> None:
    """Validate emergency/instant leave.

    Instant leave is allowed without the normal 14-day notice rule, but it still
    uses the same basic safety rules:
        * end date cannot be before start date
        * maximum interval is MAX_LEAVE_DAYS
        * start date cannot be before the current operating date

    In the mobile/dashboard flow, instant leave starts on the active roll date.
    """
    today = today or get_operating_date()
    validate_leave_window(start_date, end_date, today=today, enforce_notice=False)

    if start_date < today:
        raise ValueError(
            f"Instant leave cannot start before the operating date. "
            f"Operating date is {today.isoformat()}."
        )
