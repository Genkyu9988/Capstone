"""
api/clock_views.py
=============================================================================
Set the operating (sim) clock from the web dashboard.

    POST /api/clock/set/   body { "date": "2026-07-20", "time": "08:00" }
        - date: YYYY-MM-DD (required)   the day to roll from
        - time: HH:MM       (optional)  default 08:00 (work-day start)
        Calls sim_clock.set_clock(...) -- exactly what the console command does --
        so the clock is anchored to that moment and ticks forward in real time.
        The Live Map / mobile read this same clock and roll from there, unchanged.

    GET  /api/clock/set/   -> { now, set, status }   current clock state

This is additive: it reuses api/sim_clock.set_clock and touches nothing else.
=============================================================================
"""
from datetime import date, datetime

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status as http

from . import sim_clock


class SetClockView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        date_raw = request.data.get("date")
        if not date_raw:
            return Response({"error": "date is required (YYYY-MM-DD)."},
                            status=http.HTTP_400_BAD_REQUEST)
        try:
            d = date.fromisoformat(str(date_raw))
        except ValueError:
            return Response({"error": "date must be YYYY-MM-DD."},
                            status=http.HTTP_400_BAD_REQUEST)

        hh, mm = 8, 0  # default: start of the work day
        time_raw = request.data.get("time")
        if time_raw:
            try:
                parts = str(time_raw).split(":")
                hh = int(parts[0])
                mm = int(parts[1]) if len(parts) > 1 else 0
                if not (0 <= hh <= 23 and 0 <= mm <= 59):
                    raise ValueError
            except (ValueError, IndexError):
                return Response({"error": "time must be HH:MM (24h)."},
                                status=http.HTTP_400_BAD_REQUEST)

        # naive datetime; set_clock makes it timezone-aware, just like the console
        sim_start = datetime(d.year, d.month, d.day, hh, mm)
        sim_clock.set_clock(sim_start)

        n = sim_clock.now()
        return Response({
            "ok": True,
            "now": n.isoformat() if n else None,
            "date": d.isoformat(),
            "time": f"{hh:02d}:{mm:02d}",
        }, status=http.HTTP_200_OK)

    def get(self, request):
        n = sim_clock.now()
        return Response({
            "set": n is not None,
            "now": n.isoformat() if n else None,
            "status": sim_clock.status(),
        }, status=http.HTTP_200_OK)
