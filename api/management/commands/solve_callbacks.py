"""
api/management/commands/solve_callbacks.py
=============================================================================
Window-based, GUROBI-dispatched callback (breakdown) generator.

This is the callback analog of solve_month, and it replaces the greedy
solve_callbacks_year. Same UX as maintenance:

    * pick a window: --start with --end, OR --months 1..6
    * the operating clock ("roll date") bounds what reports show -- no extra
      code here, it's the shared SetClockView / report as_of mechanism.

For each day in the window:
    1) synthesize that day's callbacks (Poisson per region, AA fraction,
       reduced weekend standby crew) as CALLBACK Tasks
    2) ASSIGN THEM WITH GUROBI: build Task rows + a haversine travel matrix and
       call solve_with_gurobi(), which routes CALLBACK tasks into the Gurobi
       breakdown MILP (optimizer_v4.solve_breakdown). NO greedy dispatch.
    3) write Schedules via result_writer (unassigned callbacks are flagged ->
       Req_16), lay each tech's stops out sequentially for realistic daily
       hours, attribute each callback to the responding tech's group, and mark
       it completed/inactive as history.

    python manage.py solve_callbacks --start 2026-07-01 --months 1
    python manage.py solve_callbacks --start 2026-07-01 --end 2026-09-30 --rate 1.5
    python manage.py solve_callbacks --start 2026-07-01 --months 6 --clear

NOTE: each day is a real Gurobi solve. Back up db.sqlite3 before long windows.
Use --clear to wipe previously persisted CB- callbacks before regenerating.
=============================================================================
"""
import calendar
import math
import random
from datetime import date, datetime, timedelta, time

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from api.models import (
    Technician, Unit, Task, TaskType, Schedule, PlanningPeriod,
    OptimizationRun, RunStatus, OperationType, SpecialtyType,
    TechnicianRole, CallbackPriority, TaskStatus,
)
from api.services.optimization.solver import solve_with_gurobi
from api.services.optimization.result_writer import write_optimization_results
from api.services.maps.distance_service import haversine_distance_km

BOSPHORUS_LNG = 29.02
ROAD_FACTOR = 1.35
SPEED_KMH = 30.0
AA_FRACTION = 0.15
WEEKEND_TECHS = 2
WEEKEND_RATE_FACTOR = 0.3
MAX_SPAN_DAYS = 186          # ~6 months, mirrors SimulationRunView
SERVICE_MIN = 60  # service duration: callback visit takes 60 min
CALLBACK_SLA_MIN = {"AA": 60, "B": 240}  # SLA response windows: AA=1h, B=4h
DAY_START_MIN = 8 * 60


def _region(lng):
    return "Europe" if float(lng) < BOSPHORUS_LNG else "Asia"


def _poisson(lam):
    if lam <= 0:
        return 0
    L = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= random.random()
        if p <= L:
            return k - 1


def _add_months(d, n):
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def _combine(d, minute):
    h, m = divmod(int(minute), 60)
    h = min(h, 23)
    naive = datetime.combine(d, time(h, m))
    return timezone.make_aware(naive) if timezone.is_naive(naive) else naive


class Command(BaseCommand):
    help = "Window-based Gurobi callback dispatch (callback analog of solve_month)."

    def add_arguments(self, parser):
        parser.add_argument("--start", type=str, required=True)
        parser.add_argument("--end", type=str, default=None)
        parser.add_argument("--months", type=int, default=None, help="1..6 (mutually exclusive with --end)")
        parser.add_argument("--rate", type=float, default=1.5, help="Callbacks per unit per year.")
        parser.add_argument("--weekend-rate", type=float, default=WEEKEND_RATE_FACTOR)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--clear", action="store_true",
                            help="Delete previously persisted CB- callbacks first.")

    # ------------------------------------------------------------------ run
    def handle(self, *args, **opts):
        random.seed(opts["seed"])
        start = date.fromisoformat(opts["start"])

        if opts["end"]:
            end = date.fromisoformat(opts["end"])
        elif opts["months"]:
            m = opts["months"]
            if not (1 <= m <= 6):
                raise CommandError("--months must be between 1 and 6.")
            end = _add_months(start, m) - timedelta(days=1)
        else:
            raise CommandError("Provide --end or --months.")

        if end < start:
            raise CommandError("--end is before --start.")
        if (end - start).days > MAX_SPAN_DAYS:
            raise CommandError(f"window too long (max {MAX_SPAN_DAYS} days).")

        if opts["clear"]:
            self._clear()

        cb_techs = list(Technician.objects.filter(
            tech_role=TechnicianRole.CALLBACK,
            is_active_employee=True,
            is_available=True,
            current_latitude__isnull=False,
            current_longitude__isnull=False,
        ).select_related("group"))
        if not cb_techs:
            raise CommandError("No located callback technicians. Run seed_deployment.")

        self._techs_by_region = {"Europe": [], "Asia": []}
        for t in cb_techs:
            self._techs_by_region[_region(t.current_longitude)].append(t)

        units = list(Unit.objects.filter(is_active=True, latitude__isnull=False)
                     .values("id", "unit_code", "unit_name",
                             "latitude", "longitude", "unit_type"))
        self._units_by_region = {"Europe": [], "Asia": []}
        for u in units:
            self._units_by_region[_region(u["longitude"])].append(u)

        self._exp_per_day = {r: len(self._units_by_region[r]) * opts["rate"] / 365.0
                             for r in ("Europe", "Asia")}

        self._creator = User.objects.filter(is_superuser=True).first() or User.objects.first()
        self._tt_aa = self._task_type("AA")
        self._tt_norm = self._task_type("B")
        self._counter = (Task.objects.filter(task_no__startswith="CB-").count() + 1)
        self._weekend_rate = opts["weekend_rate"]

        self.stdout.write(self.style.SUCCESS(
            f"=== solve_callbacks (GUROBI) | {start} .. {end} | "
            f"rate {opts['rate']}/unit/yr ==="))
        for r in ("Europe", "Asia"):
            self.stdout.write(
                f"  {r}: {len(self._units_by_region[r])} units, "
                f"{len(self._techs_by_region[r])} callback techs, "
                f"~{self._exp_per_day[r]:.1f}/day")

        grand, days = 0, 0
        d = start
        while d <= end:
            grand += self._solve_one_day(d)
            days += 1
            d += timedelta(days=1)

        self.stdout.write(self.style.SUCCESS(
            f"\nDONE. {days} days, {grand} callbacks dispatched by Gurobi."))

    # ------------------------------------------------------------- one day
    def _solve_one_day(self, d):
        is_weekend = d.weekday() >= 5
        period = self._period(d)

        # 1) synthesize today's callbacks as PENDING CALLBACK Tasks
        new_tasks = []
        for r in ("Europe", "Asia"):
            full = self._techs_by_region[r]
            ru = self._units_by_region[r]
            if not full or not ru:
                continue
            lam = self._exp_per_day[r] * (self._weekend_rate if is_weekend else 1.0)
            n = _poisson(lam)
            for _ in range(n):
                u = random.choice(ru)
                is_aa = random.random() < AA_FRACTION
                unit_obj = Unit.objects.get(id=u["id"])
                priority = "AA" if is_aa else "B"
                release_at = _combine(d, DAY_START_MIN)
                task = Task.objects.create(
                    task_no=f"CB-{self._counter:08d}",
                    unit=unit_obj,
                    task_type=(self._tt_aa if is_aa else self._tt_norm),
                    planning_period=period, created_by=self._creator,
                    description=f"Callback ({'AA entrapment' if is_aa else 'B fault'})",
                    status=TaskStatus.PENDING,
                    priority=CallbackPriority.AA if is_aa else CallbackPriority.B,
                    estimated_duration_min=SERVICE_MIN,
                    release_time=release_at,
                    earliest_start=release_at,
                    latest_finish=release_at + timedelta(minutes=CALLBACK_SLA_MIN[priority]),
                    is_active=True)
                self._counter += 1
                new_tasks.append(task)

        if not new_tasks:
            self.stdout.write(f"  {d} {d.strftime('%a')}: no callbacks")
            return 0

        # 2) GUROBI dispatch -- solve_with_gurobi routes CALLBACK tasks into the
        #    breakdown MILP (optimizer_v4.solve_breakdown). Weekend uses the
        #    reduced standby crew (first WEEKEND_TECHS per region).
        techs = []
        for r in ("Europe", "Asia"):
            pool = self._techs_by_region[r]
            techs.extend(pool[:WEEKEND_TECHS] if is_weekend else pool)

        tt_time, tt_dist = {}, {}
        for tech in techs:
            for task in new_tasks:
                u = task.unit
                km = haversine_distance_km(
                    tech.current_latitude, tech.current_longitude,
                    u.latitude, u.longitude) * ROAD_FACTOR
                tt_time[(tech.id, task.id)] = km / SPEED_KMH
                tt_dist[(tech.id, task.id)] = km

        input_data = {
            "tasks": new_tasks, "technicians": techs,
            "technician_task_travel_time": tt_time,
            "technician_task_travel_distance": tt_dist,
        }

        results = solve_with_gurobi(input_data)

        run = OptimizationRun.objects.create(
            planning_period=period, triggered_by=self._creator,
            status=RunStatus.RUNNING, started_at=timezone.now(),
            solver_name="gurobi-breakdown")
        write_optimization_results(run, results)
        run.status = RunStatus.FEASIBLE
        run.finished_at = timezone.now()
        run.summary = f"Gurobi callback dispatch {d.isoformat()}"
        run.save()

        # 3) lay each tech's stops out sequentially on day d, attribute to the
        #    responding tech's group, mark completed/inactive (history).
        scheds = list(Schedule.objects.filter(optimization_run=run)
                      .select_related("task", "technician", "technician__group"))
        by_tech = {}
        for s in scheds:
            by_tech.setdefault(s.technician_id, []).append(s)

        assigned = 0
        with transaction.atomic():
            for _tid, group_scheds in by_tech.items():
                group_scheds.sort(key=lambda s: s.sequence_order or 0)
                clock = DAY_START_MIN
                for s in group_scheds:
                    travel = s.travel_time_min or 0
                    arrive = clock + travel
                    dur = s.task.estimated_duration_min or SERVICE_MIN
                    s.start_time = _combine(d, arrive)
                    s.end_time = _combine(d, arrive + dur)
                    s.save(update_fields=["start_time", "end_time"])
                    clock = arrive + dur

                    if s.technician and s.technician.group:
                        s.task.assigned_group = s.technician.group
                    s.task.status = TaskStatus.COMPLETED
                    s.task.is_active = False
                    s.task.save(update_fields=["assigned_group", "status", "is_active"])
                    assigned += 1

        unassigned = len(new_tasks) - assigned
        crew = "weekend crew" if is_weekend else "full crew"
        self.stdout.write(
            f"  {d} {d.strftime('%a')}: {len(new_tasks)} callbacks ({crew}) "
            f"-> run #{run.id}, {assigned} dispatched, {unassigned} unassigned")
        return assigned

    # ------------------------------------------------------------- helpers
    def _task_type(self, kind):
        priority = "AA" if str(kind).upper() == "AA" else "B"
        code = f"CB-{priority}"
        tt, _ = TaskType.objects.update_or_create(
            code=code,
            defaults={"name": f"Callback {priority}",
                      "operation_type": OperationType.CALLBACK,
                      "required_specialty": SpecialtyType.BOTH,
                      "required_technician_role": TechnicianRole.CALLBACK,
                      "base_duration_min": SERVICE_MIN,
                      "sla_target_min": CALLBACK_SLA_MIN[priority],
                      "is_active": True})
        return tt

    def _period(self, d):
        p, _ = PlanningPeriod.objects.get_or_create(
            start_date=d, end_date=d,
            defaults={"name": f"Cycle {d.isoformat()}", "is_active": True,
                      "created_by": self._creator})
        return p

    def _clear(self):
        cb = Task.objects.filter(task_no__startswith="CB-")
        n = cb.count()
        Schedule.objects.filter(task__in=cb).delete()
        cb.delete()
        self.stdout.write(self.style.WARNING(
            f"Cleared {n} previously persisted callbacks."))
