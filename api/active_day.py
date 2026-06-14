"""
api/active_day.py
=============================================================================
Single source of truth for "what datetime is it now" across the live app.

Resolution order (first match wins):
    1. ?date=YYYY-MM-DD on the request          (manual override for testing)
    2. the operating clock (api/sim_clock)       (set from the console; ticks)
    3. smart default: latest scheduled day <= real today, else earliest

get_active_datetime() -> full datetime (date + time of day, for progress)
get_active_date()     -> just the date (which day's schedule to show)
=============================================================================
"""
from datetime import date, datetime

from django.utils import timezone

from api.sim_clock import now as clock_now


def get_active_datetime(request=None):
    # 1. ?date= override (combine with the real time-of-day so progress still moves)
    if request is not None:
        raw = None
        if hasattr(request, "query_params"):
            raw = request.query_params.get("date")
        elif hasattr(request, "GET"):
            raw = request.GET.get("date")
        if raw:
            try:
                d = date.fromisoformat(raw)
                now_t = timezone.localtime().time()
                return timezone.make_aware(datetime.combine(d, now_t))
            except ValueError:
                pass

    # 2. the operating clock (set from the console)
    n = clock_now()
    if n is not None:
        return n

    # 3. smart default from the schedule data
    return _default_datetime()


def get_active_date(request=None):
    return get_active_datetime(request).date()


def _default_datetime():
    from api.models import Schedule
    today = timezone.localdate()
    now_t = timezone.localtime().time()
    qs = Schedule.objects.exclude(start_time__isnull=True)

    latest = (qs.filter(start_time__date__lte=today)
                .order_by("-start_time")
                .values_list("start_time", flat=True)
                .first())
    if latest:
        return timezone.make_aware(datetime.combine(latest.date(), now_t))

    earliest = (qs.order_by("start_time")
                  .values_list("start_time", flat=True)
                  .first())
    base = earliest.date() if earliest else today
    return timezone.make_aware(datetime.combine(base, now_t))
