"""
api/management/commands/solve_month.py
=============================================================================
Generate REAL, persisted daily schedules across a date range for ONE group.

This version is SELF-CONTAINED: it computes the group's zone itself (each unit
-> nearest maintenance HQ, Voronoi) and generates that zone's due A/B/C tasks
directly. It does NOT depend on pre-existing MNT- tasks (which earlier cleanup
may have deleted), so it always works.

Each working day, in order:
    1) find this group's zone units that are DUE on day D (A>B>C supersession)
    2) create their tasks (assigned to this group)
    3) solve_group <group>  -> Gurobi writes Schedule rows in a NEW run
    4) capture THAT run's schedules, rebase timestamps onto day D, complete the
       tasks (advance unit clocks) + deactivate them so they aren't re-solved.

Weekends skipped (no planned maintenance on weekends).

    python manage.py solve_month "Ahmet Yılmaz Group" --start 2026-06-14 --end 2026-07-14

NOTE: each day is a full Gurobi solve. Back up db.sqlite3 before long runs.
=============================================================================
"""
import math
from datetime import date, datetime, timedelta, time

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from api.models import (
    SupervisorGroup, Technician, Unit, UnitMaintenanceState,
    Task, TaskType, PlanningPeriod, Schedule, OptimizationRun,
    OperationType, MaintenanceType, SpecialtyType, UnitType,
    TechnicianRole, TaskStatus, LeaveRequest,
)
from api.services.maintenance_cycle import complete_task

DUR = {"A": 240, "B": 120, "C": 45}


def _km(a, b, c, d):
    return math.sqrt(((a - c) * 111) ** 2 + ((b - d) * 85) ** 2)


class Command(BaseCommand):
    help = "Solve and persist a range of daily schedules for one group (self-contained)."

    def add_arguments(self, parser):
        parser.add_argument("group_name", type=str)
        parser.add_argument("--start", type=str, required=True)
        parser.add_argument("--end", type=str, default=None)
        parser.add_argument("--days", type=int, default=None)
        parser.add_argument("--keep-weekends", action="store_true")

    def handle(self, *args, **opts):
        group = SupervisorGroup.objects.filter(name=opts["group_name"]).first()
        if group is None:
            raise CommandError(f"Group '{opts['group_name']}' not found.")

        start = date.fromisoformat(opts["start"])
        if opts["end"]:
            end = date.fromisoformat(opts["end"])
        elif opts["days"]:
            end = start + timedelta(days=opts["days"] - 1)
        else:
            raise CommandError("Provide --end or --days.")
        if end < start:
            raise CommandError("--end is before --start.")

        skip_weekends = not opts["keep_weekends"]

        # ---- compute this group's zone ONCE (Voronoi: nearest maintenance HQ)
        zone_unit_ids = self._compute_zone(group)
        if not zone_unit_ids:
            raise CommandError(
                "Could not compute this group's zone (no maintenance HQ?).")
        self.stdout.write(self.style.SUCCESS(
            f"=== solve_month: {group.name} | {start} .. {end} | "
            f"zone = {len(zone_unit_ids)} units ==="))

        solved_days, grand = 0, 0
        d = start
        while d <= end:
            if skip_weekends and d.weekday() >= 5:
                self.stdout.write(f"  {d} {d.strftime('%a')}: weekend, skipped")
                d += timedelta(days=1)
                continue
            n = self._solve_one_day(group, d, zone_unit_ids)
            solved_days += 1
            grand += n
            d += timedelta(days=1)

        self.stdout.write(self.style.SUCCESS(
            f"\nDONE. {solved_days} working days, {grand} schedule rows for "
            f"{group.name}."))

    # ---------------------------------------------------------------- zone
    def _compute_zone(self, group):
        # maintenance HQs = one (lat,lng) per maintenance group, from a located
        # maintenance technician in that group.
        hqs = {}
        for g in SupervisorGroup.objects.all():
            t = (Technician.objects.filter(
                    group=g, tech_role=TechnicianRole.MAINTENANCE,
                    current_latitude__isnull=False).first())
            if t:
                hqs[g.id] = (float(t.current_latitude), float(t.current_longitude))
        if group.id not in hqs:
            return []

        zone = []
        for u in Unit.objects.filter(is_active=True,
                                     latitude__isnull=False).values(
                                         "id", "latitude", "longitude"):
            la, ln = float(u["latitude"]), float(u["longitude"])
            nearest = min(hqs.items(),
                          key=lambda kv: _km(la, ln, kv[1][0], kv[1][1]))[0]
            if nearest == group.id:
                zone.append(u["id"])
        return set(zone)

    # ------------------------------------------------------------- generate
    def _generate_day_tasks(self, group, d, zone_unit_ids):
        creator = (group.supervisor
                   or User.objects.filter(is_superuser=True).first()
                   or User.objects.first())
        period, _ = PlanningPeriod.objects.get_or_create(
            start_date=d, end_date=d,
            defaults={"name": f"Cycle {d.isoformat()}", "is_active": True,
                      "created_by": creator})

        def get_tt(mtype, specialty):
            code = f"MNT-{mtype}-{'ESC' if specialty == SpecialtyType.ESCALATOR else 'ELEV'}"
            tt, _ = TaskType.objects.update_or_create(
                code=code,
                defaults={"name": f"{mtype} Bakimi",
                          "operation_type": OperationType.MAINTENANCE,
                          "maintenance_type": getattr(MaintenanceType, mtype),
                          "required_specialty": specialty,
                          "required_technician_role": TechnicianRole.MAINTENANCE,
                          "base_duration_min": DUR[mtype], "is_active": True})
            return tt

        states = (UnitMaintenanceState.objects
                  .filter(unit_id__in=zone_unit_ids)
                  .select_related("unit"))
        counts = {"A": 0, "B": 0, "C": 0}
        for st in states:
            mtype = st.due_type(d)
            if mtype is None:
                continue
            unit = st.unit
            specialty = (SpecialtyType.ESCALATOR
                         if unit.unit_type == UnitType.ESCALATOR
                         else SpecialtyType.ELEVATOR)
            tt = get_tt(mtype, specialty)
            Task.objects.update_or_create(
                task_no=f"MNT-{mtype}-{group.code}-{unit.unit_code}-{d.isoformat()}",
                defaults={"unit": unit, "planning_period": period, "task_type": tt,
                          "created_by": creator, "assigned_group": group,
                          "description": f"{mtype} maintenance for {unit.unit_name}",
                          "status": TaskStatus.PENDING, "priority": None,
                          "estimated_duration_min": DUR[mtype],
                          "release_time": timezone.now(), "is_active": True})
            counts[mtype] += 1
        return counts

    # ------------------------------------------------------------- one day
    def _solve_one_day(self, group, d, zone_unit_ids):
        counts = self._generate_day_tasks(group, d, zone_unit_ids)
        total = sum(counts.values())
        if total == 0:
            self.stdout.write(f"  {d} {d.strftime('%a')}: nothing due")
            return 0

        last_run_id = (OptimizationRun.objects.order_by("-id")
                       .values_list("id", flat=True).first() or 0)

        # Date-aware leave: temporarily mark techs whose APPROVED leave covers
        # day d as unavailable, so solve_group (which filters is_available=True)
        # excludes them for THIS day only. The worker keeps working every other
        # day -- their stored flag is restored right after the solve.
        on_leave = list(Technician.objects.filter(
            group=group,
            is_available=True,
            leave_requests__status="APPROVED",
            leave_requests__start_date__lte=d,
            leave_requests__end_date__gte=d,
        ).distinct())
        for t in on_leave:
            t.is_available = False
            t.save(update_fields=["is_available"])

        try:
            try:
                call_command("solve_group", group.name, verbosity=0)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"  {d}: solve skipped ({e})"))
                return 0
        finally:
            # always restore, even if the solve raised
            for t in on_leave:
                t.is_available = True
                t.save(update_fields=["is_available"])

        if on_leave:
            names = ", ".join(t.full_name for t in on_leave)
            self.stdout.write(f"     ({len(on_leave)} on leave: {names})")

        new_run = (OptimizationRun.objects
                   .filter(id__gt=last_run_id).order_by("-id").first())
        if new_run is None:
            self.stdout.write(self.style.WARNING(f"  {d}: no new run"))
            return 0

        day_sched = list(
            Schedule.objects.filter(optimization_run=new_run)
            .select_related("task", "task__unit", "task__task_type"))
        n = 0
        with transaction.atomic():
            for s in day_sched:
                if s.start_time:
                    s.start_time = _combine(d, s.start_time)
                if s.end_time:
                    s.end_time = _combine(d, s.end_time)
                s.save(update_fields=["start_time", "end_time"])
                if s.task and s.task.task_type and \
                        s.task.task_type.operation_type == OperationType.MAINTENANCE:
                    complete_task(s.task, on_date=d)
                if s.task:
                    s.task.is_active = False
                    s.task.save(update_fields=["is_active"])
                n += 1

        self.stdout.write(
            f"  {d} {d.strftime('%a')}: due A={counts['A']} B={counts['B']} "
            f"C={counts['C']} -> run #{new_run.id}, {n} scheduled & completed")
        return n


def _combine(d, dt):
    if hasattr(dt, "hour"):
        t = time(dt.hour, dt.minute, getattr(dt, "second", 0))
    else:
        t = time(8, 0)
    naive = datetime.combine(d, t)
    return timezone.make_aware(naive) if timezone.is_naive(naive) else naive
