"""
api/management/commands/solve_callbacks_year.py
=============================================================================
Persist a YEAR of callbacks (breakdowns) to the database, so unit history and
reports can show real callback records -- not just the console simulation.

Each callback becomes:
    Task   (operation_type=CALLBACK, priority=AA or normal)
    Schedule (the responding technician + response timeline)

Dispatch mirrors the simulation: a callback goes to the nearest AVAILABLE
callback tech in the same region. The callback then "belongs" to that tech's
group (attribution by responding tech) -- which is how the unit-history report
scopes callbacks per supervisor.

Weekends use the reduced standby crew (2 techs/region) at lower volume, exactly
like simulate_callbacks.

    python manage.py solve_callbacks_year --start 2026-06-16 --days 365 --rate 1.5

NOTE: this writes a LOT of rows (~30k callbacks/year). Back up db.sqlite3 first.
Use --clear to wipe previously persisted callbacks before regenerating.
=============================================================================
"""
import math
import random
from datetime import date, datetime, timedelta, time

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from api.models import (
    Technician, Unit, Task, TaskType, Schedule, PlanningPeriod,
    SupervisorGroup, OperationType, SpecialtyType, TechnicianRole,
    CallbackPriority, TaskStatus, UnitType,
)

BOSPHORUS_LNG = 29.02
ROAD_FACTOR = 1.35
SPEED_KMH = 30.0
AA_FRACTION = 0.15
WEEKEND_TECHS = 2
WEEKEND_RATE_FACTOR = 0.3
FAULT_LABELS = ["Motor", "Door", "Power", "Other"]


def _km(a, b, c, d):
    return math.sqrt(((a - c) * 111) ** 2 + ((b - d) * 85) ** 2)


def _region(lng):
    return "Europe" if float(lng) < BOSPHORUS_LNG else "Asia"


class Command(BaseCommand):
    help = "Persist a year of callbacks (Task+Schedule) dispatched to nearest callback tech."

    def add_arguments(self, parser):
        parser.add_argument("--start", type=str, required=True)
        parser.add_argument("--days", type=int, default=365)
        parser.add_argument("--rate", type=float, default=1.5,
                            help="Callbacks per unit per year.")
        parser.add_argument("--weekend-rate", type=float, default=WEEKEND_RATE_FACTOR)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--clear", action="store_true",
                            help="Delete previously persisted CB- callbacks first.")

    def handle(self, *args, **opts):
        random.seed(opts["seed"])
        start = date.fromisoformat(opts["start"])
        days = opts["days"]
        rate = opts["rate"]

        if opts["clear"]:
            self._clear()

        cb_techs = list(Technician.objects.filter(
            tech_role=TechnicianRole.CALLBACK,
            current_latitude__isnull=False).select_related("group"))
        if not cb_techs:
            raise CommandError("No located callback technicians. Run seed_deployment.")

        techs_by_region = {"Europe": [], "Asia": []}
        for t in cb_techs:
            techs_by_region[_region(t.current_longitude)].append(t)

        units = list(Unit.objects.filter(is_active=True, latitude__isnull=False)
                     .values("id", "unit_code", "unit_name", "latitude",
                             "longitude", "unit_type"))
        units_by_region = {"Europe": [], "Asia": []}
        for u in units:
            units_by_region[_region(u["longitude"])].append(u)

        exp_per_day = {r: len(units_by_region[r]) * rate / 365.0
                       for r in ("Europe", "Asia")}

        self.stdout.write(self.style.SUCCESS(
            f"=== Persisting callbacks | {start} +{days}d | rate {rate}/unit/yr ==="))
        for r in ("Europe", "Asia"):
            self.stdout.write(
                f"  {r}: {len(units_by_region[r])} units, "
                f"{len(techs_by_region[r])} callback techs, "
                f"~{exp_per_day[r]:.1f}/day")

        # ensure callback task types exist
        tt_aa = self._task_type("AA")
        tt_norm = self._task_type("NORMAL")
        creator = User.objects.filter(is_superuser=True).first() or User.objects.first()

        total = 0
        # monotonic counter guarantees unique task_no across the whole run,
        # continuing past any callbacks already in the DB.
        existing = (Task.objects.filter(task_no__startswith="CB-")
                    .count())
        self._counter = existing + 1
        for day_off in range(days):
            d = start + timedelta(days=day_off)
            is_weekend = d.weekday() >= 5
            period = self._period(d, creator)
            n_written = self._gen_day(
                d, is_weekend, units_by_region, techs_by_region,
                exp_per_day, opts["weekend_rate"], tt_aa, tt_norm,
                period, creator)
            total += n_written
            if day_off % 30 == 0:
                self.stdout.write(f"  {d}: {n_written} callbacks (running {total})")

        self.stdout.write(self.style.SUCCESS(
            f"\nDONE. Persisted {total} callbacks over {days} days."))

    # ------------------------------------------------------------- one day
    def _gen_day(self, d, is_weekend, units_by_region, techs_by_region,
                 exp_per_day, weekend_rate, tt_aa, tt_norm, period, creator):
        written = 0
        rows = []
        for r in ("Europe", "Asia"):
            full = techs_by_region[r]
            units = units_by_region[r]
            if not full or not units:
                continue
            if is_weekend:
                techs = full[:WEEKEND_TECHS]
                lam = exp_per_day[r] * weekend_rate
            else:
                techs = full
                lam = exp_per_day[r]
            n = self._poisson(lam)
            if n == 0 or not techs:
                continue

            free_at = {t.id: 8 * 60 for t in techs}
            pos = {t.id: (float(t.current_latitude), float(t.current_longitude))
                   for t in techs}
            events = []
            for _ in range(n):
                minute = random.randint(8 * 60, 20 * 60)
                u = random.choice(units)
                is_aa = random.random() < AA_FRACTION
                events.append((minute, u, is_aa))
            events.sort(key=lambda e: e[0])

            for minute, u, is_aa in events:
                ulat, ulng = float(u["latitude"]), float(u["longitude"])
                best = None
                for t in techs:
                    tlat, tlng = pos[t.id]
                    travel = _km(ulat, ulng, tlat, tlng) * ROAD_FACTOR / SPEED_KMH * 60
                    ready = max(minute, free_at[t.id])
                    resp = (ready - minute) + travel
                    if best is None or resp < best[0]:
                        best = (resp, travel, t)
                resp, travel, tech = best
                service = 60
                free_at[tech.id] = minute + resp + service
                pos[tech.id] = (ulat, ulng)
                rows.append((d, minute, u, is_aa, tech, travel, service, r))

        if not rows:
            return 0

        with transaction.atomic():
            for (d, minute, u, is_aa, tech, travel, service, region) in rows:
                tt = tt_aa if is_aa else tt_norm
                task_no = f"CB-{self._counter:08d}"
                self._counter += 1
                start_dt = _combine(d, minute + int(travel))  # arrival
                end_dt = _combine(d, minute + int(travel) + service)
                unit_obj = Unit.objects.get(id=u["id"])
                task = Task.objects.create(
                    task_no=task_no,
                    unit=unit_obj, task_type=tt, planning_period=period,
                    created_by=creator, assigned_group=tech.group,
                    description=f"Callback ({'AA entrapment' if is_aa else 'fault'})",
                    status=TaskStatus.COMPLETED,
                    priority=CallbackPriority.AA if is_aa else CallbackPriority.B,
                    estimated_duration_min=service,
                    release_time=_combine(d, minute), is_active=False)
                Schedule.objects.create(
                    task=task, technician=tech,
                    start_time=start_dt, end_time=end_dt,
                    sequence_order=1, travel_time_min=int(travel),
                    source="CALLBACK")
                written += 1
        return written

    # ------------------------------------------------------------- helpers
    def _task_type(self, kind):
        code = f"CB-{kind}"
        tt, _ = TaskType.objects.update_or_create(
            code=code,
            defaults={"name": f"Callback {kind}",
                      "operation_type": OperationType.CALLBACK,
                      "required_specialty": SpecialtyType.BOTH,
                      "required_technician_role": TechnicianRole.CALLBACK,
                      "base_duration_min": 60, "is_active": True})
        return tt

    def _period(self, d, creator):
        p, _ = PlanningPeriod.objects.get_or_create(
            start_date=d, end_date=d,
            defaults={"name": f"Cycle {d.isoformat()}", "is_active": True,
                      "created_by": creator})
        return p

    def _clear(self):
        from api.models import Schedule as S, Task as T
        cb = T.objects.filter(task_no__startswith="CB-")
        n = cb.count()
        S.objects.filter(task__in=cb).delete()
        cb.delete()
        self.stdout.write(self.style.WARNING(f"Cleared {n} previously persisted callbacks."))

    @staticmethod
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


def _combine(d, minute):
    h, m = divmod(int(minute), 60)
    h = min(h, 23)
    naive = datetime.combine(d, time(h, m))
    return timezone.make_aware(naive) if timezone.is_naive(naive) else naive
