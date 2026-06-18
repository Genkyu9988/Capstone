"""
api/management/commands/compare_v4_v5.py
=============================================================================
READ-ONLY, FAIRER comparison of v4 (heuristic) vs v5 (Gurobi MILP) maintenance
solvers over the same days / same tasks for one supervisor group.

Improvements over the first version:
  * In-memory proxy coordinates for technicians that have no stored location,
    so travel is realistic and varied instead of a flat 0.25h default.
    (Nothing is written to the DB -- proxies exist only for this run.)
  * Overtime is measured per (technician, work_day), so v4's multi-day
    spreading is no longer mislabeled as overtime.
  * Reports the number of work-days each solver spread the work across
    (this is how v4's "defer" vs v5's "drop" shows up).
  * Separate "fair-subset" totals over only the days where BOTH solvers
    fully covered the work (0 unassigned for each) -- on those days the cost
    comparison is clean (no missed-task penalty distortion).
  * --v5-overtime-hours to give v5 a per-period overtime budget.

    python manage.py compare_v4_v5 "Ahmet Yılmaz Group" --start 2026-06-14 --end 2026-07-14
    python manage.py compare_v4_v5 "Ahmet Yılmaz Group" --start 2026-06-14 --end 2026-07-14 --v5-overtime-hours 2
=============================================================================
"""
import time as _time
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from api.models import (
    SupervisorGroup, Technician, Task, OperationType, TechnicianRole,
)
from api.services.maps.distance_service import haversine_distance_km

from api.services.optimization.solver import (
    _technicians_to_records, _maintenance_tasks_to_records,
    _build_technician_to_task_travel_matrix,
)
from api.services.optimization.optimizer_v4 import (
    solve_maintenance_from_records as v4_solve, SolverConfig as V4Config,
)
from api.services.optimization.optimizer_v5 import (
    solve_maintenance_from_records as v5_solve, SolverConfig as V5Config,
)
from api.services.optimization.optimizer_v5 import (
    LABOR_COST_PER_HOUR, TRAVEL_TIME_COST_PER_HOUR,
    OVERTIME_PENALTY, MAINTENANCE_MISSED_PENALTY,
)

ROAD_FACTOR = 1.35
SPEED_KMH = 30.0


def _metrics(result, available_hours):
    """Uniform metrics. Overtime is per (technician, work_day) so multi-day
    spreading is not counted as overtime."""
    assignments = result.get("assignments", []) or []
    unassigned = result.get("unassigned_tasks", []) or []

    total_service = total_travel = 0.0
    per_tech_day = {}          # (tech, work_day) -> hours used
    techs = set()
    work_days = set()

    for row in assignments:
        t = str(row.get("technician_id"))
        wd = row.get("work_day", 1) or 1
        svc = float(row.get("service_time", 0) or 0)
        trv = float(row.get("travel_time", 0) or 0)
        total_service += svc
        total_travel += trv
        per_tech_day[(t, wd)] = per_tech_day.get((t, wd), 0.0) + svc + trv
        techs.add(t)
        work_days.add(wd)

    overtime = 0.0
    for (t, wd), used in per_tech_day.items():
        cap = float(available_hours.get(t, 0.0))
        if used > cap:
            overtime += used - cap

    meta = result.get("meta", {}) or {}
    objective = meta.get("objective_value", result.get("objective_value"))

    cost = (LABOR_COST_PER_HOUR * total_service
            + TRAVEL_TIME_COST_PER_HOUR * total_travel
            + OVERTIME_PENALTY * overtime
            + MAINTENANCE_MISSED_PENALTY * len(unassigned))

    return {
        "assigned": len(assignments), "unassigned": len(unassigned),
        "service_h": total_service, "travel_h": total_travel,
        "overtime_h": overtime, "techs_used": len(techs),
        "work_days": max(work_days) if work_days else 0,
        "objective": objective, "cost": cost,
    }


class Command(BaseCommand):
    help = "Read-only, fairer v4-vs-v5 maintenance comparison over a date range."

    def add_arguments(self, parser):
        parser.add_argument("group_name", type=str)
        parser.add_argument("--start", type=str, required=True)
        parser.add_argument("--end", type=str, required=True)
        parser.add_argument("--keep-weekends", action="store_true")
        parser.add_argument("--v5-overtime-hours", type=float, default=None,
                            help="Per-period overtime budget for v5 (default: leave config as-is).")

    def handle(self, *args, **opts):
        group = SupervisorGroup.objects.filter(name=opts["group_name"]).first()
        if group is None:
            raise CommandError(f"Group '{opts['group_name']}' not found.")
        start = date.fromisoformat(opts["start"])
        end = date.fromisoformat(opts["end"])
        if end < start:
            raise CommandError("--end is before --start.")
        skip_weekends = not opts["keep_weekends"]

        techs = list(Technician.objects.filter(
            group=group, tech_role=TechnicianRole.MAINTENANCE, is_available=True))
        if not techs:
            raise CommandError("No maintenance-capable technicians in this group.")

        # ---- in-memory proxy coordinates for techs with no stored location ----
        coord_pool = []
        for la, ln in Task.objects.filter(
                planning_period__start_date__gte=start,
                planning_period__start_date__lte=end,
                assigned_group=group,
                task_type__operation_type=OperationType.MAINTENANCE,
        ).select_related("unit").values_list(
                "unit__latitude", "unit__longitude").distinct():
            if la is not None and ln is not None:
                coord_pool.append((float(la), float(ln)))

        tech_loc = {}
        proxied = 0
        for i, t in enumerate(techs):
            if t.current_latitude is not None and t.current_longitude is not None:
                tech_loc[t.id] = (float(t.current_latitude), float(t.current_longitude))
            elif coord_pool:
                tech_loc[t.id] = coord_pool[i % len(coord_pool)]   # spread across territory
                proxied += 1

        v5cfg_kwargs = {}
        if opts["v5_overtime_hours"] is not None:
            v5cfg_kwargs["max_maintenance_overtime_hours"] = opts["v5_overtime_hours"]

        self.stdout.write(self.style.SUCCESS(
            f"=== compare_v4_v5: {group.name} | {start}..{end} ===\n"
            f"{len(techs)} maintenance techs ({proxied} given in-memory proxy locations; "
            f"nothing written to DB)"
            + (f"\nv5 overtime budget set to {opts['v5_overtime_hours']}h/period"
               if opts["v5_overtime_hours"] is not None else "")))

        tech_records = _technicians_to_records(techs)
        available_hours = {r["technician_id"]: float(r["available_hours"]) for r in tech_records}

        hdr = (f"\n{'Day':<12}{'tasks':>6} | "
               f"{'v4 asn':>7}{'v4 un':>6}{'v4 wd':>6}{'v4 ot':>7}{'v4 cost':>11} | "
               f"{'v5 asn':>7}{'v5 un':>6}{'v5 wd':>6}{'v5 ot':>7}{'v5 obj':>11}{'v5 cost':>11}")
        self.stdout.write(hdr)
        self.stdout.write("-" * len(hdr))

        ALL = {k: {x: 0.0 for x in ("assigned", "unassigned", "service_h", "travel_h",
                                    "overtime_h", "cost", "secs")} for k in ("v4", "v5")}
        FAIR = {k: dict(ALL[k]) for k in ("v4", "v5")}   # only days both fully cover
        days_all = days_fair = 0

        d = start
        while d <= end:
            if skip_weekends and d.weekday() >= 5:
                d += timedelta(days=1); continue
            tasks = list(Task.objects.filter(
                planning_period__start_date=d, assigned_group=group,
                task_type__operation_type=OperationType.MAINTENANCE,
            ).select_related("unit", "task_type", "planning_period", "assigned_group"))
            if not tasks:
                d += timedelta(days=1); continue

            tt_time = {}
            for t in techs:
                loc = tech_loc.get(t.id)
                if not loc:
                    continue
                for task in tasks:
                    u = task.unit
                    if u.latitude is None or u.longitude is None:
                        continue
                    km = haversine_distance_km(loc[0], loc[1], u.latitude, u.longitude) * ROAD_FACTOR
                    tt_time[(t.id, task.id)] = km / SPEED_KMH

            task_records = _maintenance_tasks_to_records(tasks)
            matrix = _build_technician_to_task_travel_matrix(tasks, techs, tt_time)

            try:
                t0 = _time.perf_counter()
                r4 = v4_solve(technician_records=tech_records, task_records=task_records,
                              travel_time_matrix=matrix, config=V4Config())
                dt4 = _time.perf_counter() - t0
                m4 = _metrics(r4, available_hours)
                t0 = _time.perf_counter()
                r5 = v5_solve(technician_records=tech_records, task_records=task_records,
                              travel_time_matrix=matrix, config=V5Config(**v5cfg_kwargs))
                dt5 = _time.perf_counter() - t0
                m5 = _metrics(r5, available_hours)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"{d}  failed: {e}"))
                d += timedelta(days=1); continue

            obj5 = "n/a" if m5["objective"] is None else f"{m5['objective']:.0f}"
            self.stdout.write(
                f"{d.isoformat():<12}{len(tasks):>6} | "
                f"{m4['assigned']:>7}{m4['unassigned']:>6}{m4['work_days']:>6}{m4['overtime_h']:>7.1f}{m4['cost']:>11.0f} | "
                f"{m5['assigned']:>7}{m5['unassigned']:>6}{m5['work_days']:>6}{m5['overtime_h']:>7.1f}{obj5:>11}{m5['cost']:>11.0f}")

            for key, m, dt in (("v4", m4, dt4), ("v5", m5, dt5)):
                for x, v in (("assigned", m["assigned"]), ("unassigned", m["unassigned"]),
                             ("service_h", m["service_h"]), ("travel_h", m["travel_h"]),
                             ("overtime_h", m["overtime_h"]), ("cost", m["cost"]), ("secs", dt)):
                    ALL[key][x] += v
            days_all += 1
            if m4["unassigned"] == 0 and m5["unassigned"] == 0:
                for key, m, dt in (("v4", m4, dt4), ("v5", m5, dt5)):
                    for x, v in (("assigned", m["assigned"]), ("service_h", m["service_h"]),
                                 ("travel_h", m["travel_h"]), ("overtime_h", m["overtime_h"]),
                                 ("cost", m["cost"]), ("secs", dt)):
                        FAIR[key][x] += v
                days_fair += 1
            d += timedelta(days=1)

        if days_all == 0:
            raise CommandError("No days with maintenance tasks in that range for this group.")

        def block(title, T, n):
            self.stdout.write("\n" + "=" * 64)
            self.stdout.write(f"{title}  ({n} days)")
            self.stdout.write("=" * 64)
            for key in ("v4", "v5"):
                t = T[key]
                label = "v4 (heuristic)" if key == "v4" else "v5 (Gurobi)"
                self.stdout.write(
                    f"{label:<16} assigned={t['assigned']:>5.0f}  unassigned={t['unassigned']:>4.0f}  "
                    f"service={t['service_h']:>7.1f}h  travel={t['travel_h']:>6.1f}h  "
                    f"overtime={t['overtime_h']:>6.1f}h  cost={t['cost']:>13.0f}  solve={t['secs']:>5.2f}s")
            c4, c5 = T["v4"]["cost"], T["v5"]["cost"]
            if c4 > 0:
                delta = (c4 - c5) / c4 * 100.0
                self.stdout.write(f"-> v5 cost is {abs(delta):.1f}% {'lower' if delta>=0 else 'higher'} than v4.")

        block("ALL DAYS (confounded: defer-vs-drop)", ALL, days_all)
        if days_fair:
            block("FAIR SUBSET (days BOTH fully covered)", FAIR, days_fair)
        else:
            self.stdout.write("\n(no days where both solvers fully covered the work; "
                              "try --v5-overtime-hours to let v5 cover more)")
        self.stdout.write(self.style.SUCCESS("\nRead-only comparison complete. No data modified."))
