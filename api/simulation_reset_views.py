"""
api/simulation_reset_views.py
=============================================================================
"Reset to clean slate" for the web Generate-Schedule flow.

    POST /api/simulation/reset/   { optional "group_id" / "group" }
        1) deletes the previous derived plan  (Schedule rows for the group)
        2) re-seeds every unit's maintenance clock back to the staggered seed
           (re-runs `run_maintenance_cycle --init`, which is idempotent)
        3) resets the operating clock to a clean start (today 08:00)
        4) clears any leftover run marker so the status goes back to idle

Why this exists: generating a schedule ADVANCES each unit's maintenance clock
(complete_task) and `solve_month` never deletes the previous run's Schedule
rows. So a second generate over the same window finds "nothing due" and the
old plan stays visible. Resetting these three pieces of state makes every
generate start from a true clean slate.

IMPORTANT (coordinate with the optimizer team before relying on this):
this view touches shared simulation state -- the Schedule table, the per-unit
UnitMaintenanceState clocks (via the existing seed command), and the sim clock.
It does NOT touch any optimizer internals (no solver code, no cost weights). It
reuses the existing `run_maintenance_cycle --init` command rather than
re-implementing the seeding maths, so if the seeding logic changes, this stays
correct automatically.

Additive: new file + one url line. Reuses SimulationRunView's own group
resolution so the deletion scope matches exactly what `generate` would build.
=============================================================================
"""
from datetime import date, datetime

from django.core.management import call_command
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Schedule, OptimizationRun
from . import sim_clock
# reuse the run view's group resolution + job-file cleanup so behaviour matches
from .simulation_run_views import SimulationRunView, _clear_files


class SimulationResetView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # ---- resolve which group's plan to wipe (same logic as generate) ----
        try:
            group = SimulationRunView()._resolve_group(request)
        except Exception:
            group = None

        # ---- 1) clear the previous derived plan -----------------------------
        if group is not None:
            sched_qs = Schedule.objects.filter(technician__group=group)
        else:
            # no group resolved (shouldn't happen for a logged-in supervisor):
            # fall back to clearing all maintenance schedules for the demo.
            sched_qs = Schedule.objects.all()

        cleared = sched_qs.count()
        sched_qs.delete()

        # drop optimization runs that no longer have any schedules (cosmetic;
        # guarded so a reverse-relation name change can never break the reset)
        try:
            used = set(
                Schedule.objects.values_list("optimization_run_id", flat=True)
            )
            OptimizationRun.objects.exclude(
                id__in=[u for u in used if u is not None]
            ).delete()
        except Exception:
            pass

        # ---- 2) re-seed every unit's maintenance clock ----------------------
        # run_maintenance_cycle --init is idempotent (update_or_create) and is
        # the single source of truth for the staggered seed.
        try:
            call_command("run_maintenance_cycle", init=True)
        except Exception as exc:
            return Response(
                {"reset": False,
                 "error": f"clock re-seed failed: {exc}",
                 "cleared_schedules": cleared},
                status=http.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # ---- 3) reset the operating clock to a clean start (today 08:00) ----
        today = date.today()
        sim_clock.set_clock(datetime(today.year, today.month, today.day, 8, 0))

        # ---- 4) clear any leftover run marker so status goes idle -----------
        try:
            _clear_files()
        except Exception:
            pass

        now = sim_clock.now()
        return Response(
            {
                "reset": True,
                "group": group.name if group is not None else None,
                "cleared_schedules": cleared,
                "clock": now.isoformat() if now else None,
            },
            status=http.HTTP_200_OK,
        )
