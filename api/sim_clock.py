"""
api/sim_clock.py
=============================================================================
The OPERATING CLOCK for the live system.

This is NOT a fake simulation. It only answers one question: "what day and time
is it right now?" -- so the benchmark month schedule (which lives on dates like
2026-07-07, not the real calendar today) can be operated as if it were happening
live.

You set an anchor from the console (set_clock management command). From then on:

    now() = anchor_sim_time + (real_wall_clock_now - anchor_set_at)

so the clock TICKS FORWARD in real time. Set it to 2026/07/07 09:43 and ten real
minutes later now() returns 2026/07/07 09:53. Both the phone and the supervisor
dashboard read this same clock, so they always agree on the moment.

Stored in a small JSON file (no migration). The dev server is one process, so
the phone and web requests read the same anchor.
=============================================================================
"""
import os
import json
from datetime import datetime

from django.conf import settings
from django.utils import timezone


def _path():
    base = getattr(settings, "BASE_DIR", ".")
    return os.path.join(str(base), ".sim_clock.json")


def set_clock(sim_start):
    """Anchor 'now' to `sim_start` (a datetime). It then ticks in real time."""
    if timezone.is_naive(sim_start):
        sim_start = timezone.make_aware(sim_start)
    data = {
        "sim_start": sim_start.isoformat(),
        "set_at": timezone.now().isoformat(),
    }
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(data, f)
    return sim_start


def clear_clock():
    try:
        os.remove(_path())
    except FileNotFoundError:
        pass


def now():
    """Current operating datetime, or None if the clock has not been set."""
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        sim_start = datetime.fromisoformat(data["sim_start"])
        set_at = datetime.fromisoformat(data["set_at"])
    except Exception:
        return None
    return sim_start + (timezone.now() - set_at)


def status():
    """Human-readable clock status for the console."""
    n = now()
    if n is None:
        return "Operating clock is NOT set (system falls back to the first scheduled day)."
    return f"Operating clock: now = {n.isoformat()} (ticking in real time)."
