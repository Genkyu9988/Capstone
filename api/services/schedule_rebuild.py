"""
api/services/schedule_rebuild.py
=============================================================================
Next-day future schedule rebuild after supervisor roster changes.

Business rule:
    Roll date/time is 2026-06-24 15:00.
    Supervisor adds/removes/reactivates a MAINTENANCE technician.

Behavior:
    * The current roll-date day is kept frozen.
    * Starting from the next roll-date day, this supervisor group's already
      generated future maintenance tasks are re-solved with the new active
      maintenance roster.
    * Existing future task demand is preserved. The rebuild changes WHO does
      WHAT, WHEN, and in which ROUTE order. It does not invent a brand-new
      maintenance demand set.
    * The rebuild uses the existing Gurobi path:
          solve_group -> solve_with_gurobi -> result_writer

Why this version does not regenerate clocks:
    In the generated simulation, future Task rows already exist for each future
    day. For a roster change, the safest demo behavior is to keep those future
    tasks and only reassign/re-time them. This avoids the "unit clocks already
    advanced" problem and gives clear proof that Ahmet's future tasks moved to
    other technicians.
=============================================================================
"""
from __future__ import annotations

from contextlib import redirect_stdout
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from io import StringIO
from typing import Dict, Iterable, Optional, Set

from django.core.management import call_command
from django.db import transaction
from django.db.models import Max
from django.contrib.auth.models import User
from django.utils import timezone

from api.models import (
    SupervisorGroup,
    Technician,
    Schedule,
    Task,
    OptimizationRun,
    RunStatus,
    OperationType,
    TechnicianRole,
    TaskStatus,
    LeaveRequest,
)
from api.services.maintenance_cycle import complete_task
from api.services.optimization.solver import solve_with_gurobi
from api.services.optimization.result_writer import write_optimization_results
from api.services.maps.distance_service import haversine_distance_km


def next_day_from_roll_date(request=None) -> date:
    """Return the next planning date after the admin/simulation roll date."""
    try:
        from api.active_day import get_active_date
        active = get_active_date(request) if request is not None else get_active_date()
    except Exception:
        active = timezone.localdate()
    return active + timedelta(days=1)


def _as_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        return value.date()
    return None


def _combine(day: date, dt_value):
    """Place a solver-produced time on the requested simulation day."""
    if dt_value is None:
        t = time(8, 0)
    elif hasattr(dt_value, "hour"):
        t = time(dt_value.hour, dt_value.minute, getattr(dt_value, "second", 0))
    else:
        t = time(8, 0)
    naive = datetime.combine(day, t)
    return timezone.make_aware(naive) if timezone.is_naive(naive) else naive


def _latest_future_date(group: SupervisorGroup, effective_date: date) -> Optional[date]:
    """Find the last future date that belongs to this group's maintenance plan."""
    latest_schedule = (
        Schedule.objects
        .filter(
            technician__group=group,
            task__task_type__operation_type=OperationType.MAINTENANCE,
            start_time__date__gte=effective_date,
        )
        .aggregate(mx=Max("start_time"))
        .get("mx")
    )

    latest_task = (
        Task.objects
        .filter(
            assigned_group=group,
            task_type__operation_type=OperationType.MAINTENANCE,
            planning_period__start_date__gte=effective_date,
        )
        .aggregate(mx=Max("planning_period__start_date"))
        .get("mx")
    )

    dates = [d for d in (_as_date(latest_schedule), _as_date(latest_task)) if d is not None]
    return max(dates) if dates else None


def _future_tasks_by_day(group: SupervisorGroup, effective_date: date, end_date: date) -> Dict[date, Set[int]]:
    """Return existing generated future maintenance task ids grouped by day."""
    out: Dict[date, Set[int]] = defaultdict(set)
    qs = (
        Task.objects
        .filter(
            assigned_group=group,
            task_type__operation_type=OperationType.MAINTENANCE,
            planning_period__start_date__gte=effective_date,
            planning_period__start_date__lte=end_date,
        )
        .select_related("planning_period")
        .values("id", "planning_period__start_date")
    )
    for row in qs:
        d = row["planning_period__start_date"]
        if d is not None:
            out[d].add(row["id"])
    return out


def _active_maintenance_technicians(group: SupervisorGroup) -> int:
    return Technician.objects.filter(
        group=group,
        tech_role=TechnicianRole.MAINTENANCE,
        is_active_employee=True,
        is_available=True,
        current_latitude__isnull=False,
        current_longitude__isnull=False,
    ).count()


def _approved_leave_technicians_for_day(group: SupervisorGroup, day: date):
    """Technicians whose approved leave covers this exact planning day.

    We only toggle technicians that are currently available, then restore them
    after the one-day solve. This keeps leave date-aware instead of making the
    employee globally unavailable for the whole month.
    """
    return list(
        Technician.objects.filter(
            group=group,
            tech_role=TechnicianRole.MAINTENANCE,
            is_active_employee=True,
            is_available=True,
            current_latitude__isnull=False,
            current_longitude__isnull=False,
            leave_requests__status=LeaveRequest.LeaveStatus.APPROVED,
            leave_requests__start_date__lte=day,
            leave_requests__end_date__gte=day,
        ).distinct()
    )


def _set_temporarily_unavailable(techs) -> None:
    for t in techs:
        t.is_available = False
        t.save(update_fields=["is_available"])


def _restore_available(techs) -> None:
    for t in techs:
        t.is_available = True
        t.save(update_fields=["is_available"])


def _delete_future_schedules(group: SupervisorGroup, effective_date: date) -> int:
    qs = Schedule.objects.filter(
        technician__group=group,
        task__task_type__operation_type=OperationType.MAINTENANCE,
        start_time__date__gte=effective_date,
    )
    count = qs.count()
    qs.delete()
    return count


def _cleanup_empty_runs() -> int:
    """Remove OptimizationRun rows that no longer own any Schedule rows."""
    try:
        used = set(
            Schedule.objects
            .exclude(optimization_run_id__isnull=True)
            .values_list("optimization_run_id", flat=True)
        )
        qs = OptimizationRun.objects.exclude(id__in=used)
        count = qs.count()
        qs.delete()
        return count
    except Exception:
        return 0


def _set_tasks_waiting(task_ids: Iterable[int], active: bool) -> int:
    ids = list(task_ids)
    if not ids:
        return 0
    return Task.objects.filter(id__in=ids).update(
        is_active=active,
        status=TaskStatus.PENDING,
        is_unassigned=False,
        unassigned_reason=None,
    )


def _finish_day_tasks(
    day: date,
    task_ids: Iterable[int],
    run_id: int,
    *,
    not_before: Optional[datetime] = None,
) -> int:
    """Rebase new schedules to the day and deactivate the day's tasks.

    For normal future rebuilds the solver's 08:xx/09:xx timestamps are placed on
    the target calendar day.

    For instant leave, the current day may already be in progress. In that case
    not_before is the roll-date time of the emergency approval. We preserve
    already-finished schedule rows and shift the newly solved remaining route so
    that it starts after not_before rather than at 08:00 again.
    """
    ids = set(task_ids)
    scheds = (
        Schedule.objects
        .filter(optimization_run_id=run_id, task_id__in=ids)
        .select_related("task", "task__task_type", "task__unit")
        .order_by("technician_id", "sequence_order")
    )

    if not_before is not None and timezone.is_naive(not_before):
        not_before = timezone.make_aware(not_before)

    day_start = timezone.make_aware(datetime.combine(day, time(8, 0)))

    touched_tasks = set()
    n = 0
    with transaction.atomic():
        for s in scheds:
            if s.start_time:
                rebased_start = _combine(day, s.start_time)
                if not_before is not None and day == not_before.date():
                    rebased_start = not_before + max(rebased_start - day_start, timedelta(0))
                s.start_time = rebased_start

            if s.end_time:
                rebased_end = _combine(day, s.end_time)
                if not_before is not None and day == not_before.date():
                    rebased_end = not_before + max(rebased_end - day_start, timedelta(0))
                s.end_time = rebased_end

            s.save(update_fields=["start_time", "end_time"])

            # Keep UnitMaintenanceState consistent with the planned future day.
            # If multiple technicians are assigned to the same task, complete it once.
            if s.task_id not in touched_tasks:
                touched_tasks.add(s.task_id)
                try:
                    complete_task(s.task, on_date=day)
                except Exception:
                    pass
            n += 1

        # Bound the day. Assigned and unassigned day tasks should not leak into
        # tomorrow's solve_group call.
        Task.objects.filter(id__in=ids).update(is_active=False)

    return n


def rebuild_group_future_schedule(
    group: SupervisorGroup,
    *,
    effective_date: Optional[date] = None,
    end_date: Optional[date] = None,
    request=None,
) -> dict:
    """Re-solve this group's future maintenance tasks from effective_date onward."""
    effective_date = effective_date or next_day_from_roll_date(request)
    end_date = end_date or _latest_future_date(group, effective_date)

    if end_date is None or end_date < effective_date:
        return {
            "triggered": False,
            "reason": "No generated future maintenance schedule exists for this group.",
            "effective_date": effective_date.isoformat(),
            "end_date": None,
        }

    active_techs = _active_maintenance_technicians(group)
    if active_techs == 0:
        return {
            "triggered": False,
            "reason": "No active located maintenance technicians remain for this group.",
            "effective_date": effective_date.isoformat(),
            "end_date": end_date.isoformat(),
            "active_technicians": active_techs,
        }

    tasks_by_day = _future_tasks_by_day(group, effective_date, end_date)
    all_task_ids = sorted({tid for ids in tasks_by_day.values() for tid in ids})
    if not all_task_ids:
        return {
            "triggered": False,
            "reason": "No future maintenance tasks were found to rebuild.",
            "effective_date": effective_date.isoformat(),
            "end_date": end_date.isoformat(),
            "active_technicians": active_techs,
        }

    # Freeze all future tasks first, delete their old schedules, then activate
    # and solve exactly one day at a time.
    _set_tasks_waiting(all_task_ids, active=False)
    deleted_schedules = _delete_future_schedules(group, effective_date)
    deleted_runs = _cleanup_empty_runs()

    total_rows = 0
    solved_days = 0
    log_lines = []

    for day in sorted(tasks_by_day.keys()):
        ids = sorted(tasks_by_day[day])
        if not ids:
            continue

        _set_tasks_waiting(ids, active=True)
        last_run_id = OptimizationRun.objects.order_by("-id").values_list("id", flat=True).first() or 0

        # Date-aware approved leave: only exclude the technician on days inside
        # the approved interval, then restore their availability immediately
        # after this one-day solve.
        on_leave = _approved_leave_technicians_for_day(group, day)
        _set_temporarily_unavailable(on_leave)

        buf = StringIO()
        try:
            with redirect_stdout(buf):
                call_command(
                    "solve_group",
                    group.name,
                    task_ids=",".join(str(i) for i in ids),
                    working_days=1,
                    verbosity=0,
                )
        finally:
            _restore_available(on_leave)
            # Always freeze these tasks again, even if solve_group raises.
            _set_tasks_waiting(ids, active=False)

        if on_leave:
            names = ", ".join(t.full_name for t in on_leave)
            log_lines.append(f"{day}: excluded approved leave technicians: {names}")

        new_run = OptimizationRun.objects.filter(id__gt=last_run_id).order_by("-id").first()
        if new_run is None:
            log_lines.append(f"{day}: no new run was created")
            continue

        rows = _finish_day_tasks(day, ids, new_run.id)
        total_rows += rows
        solved_days += 1
        log_lines.extend([x.strip() for x in buf.getvalue().splitlines() if x.strip()][-3:])
        log_lines.append(f"{day}: rebuilt {rows} schedule rows in run #{new_run.id}")

    return {
        "triggered": True,
        "effective_date": effective_date.isoformat(),
        "end_date": end_date.isoformat(),
        "active_technicians": active_techs,
        "future_tasks": len(all_task_ids),
        "deleted_schedules": deleted_schedules,
        "deleted_empty_runs": deleted_runs,
        "solved_days": solved_days,
        "new_schedule_rows": total_rows,
        "log_tail": log_lines[-15:],
    }


# ---------------------------------------------------------------------------
# Instant leave rebuild
# ---------------------------------------------------------------------------

def _get_active_datetime(request=None) -> datetime:
    """Return the simulation/admin roll datetime, falling back to local now."""
    try:
        from api.active_day import get_active_datetime
        return get_active_datetime(request) if request is not None else get_active_datetime()
    except Exception:
        return timezone.now()


def _remaining_task_ids_after(group: SupervisorGroup, active_dt: datetime) -> Set[int]:
    """Tasks not safely completed at the emergency time.

    A task is considered remaining if its schedule ends after active_dt. This
    includes the current in-progress task and all later tasks. Rows ending before
    active_dt are preserved as the technician/group's work history for the day.
    """
    if timezone.is_naive(active_dt):
        active_dt = timezone.make_aware(active_dt)
    return set(
        Schedule.objects.filter(
            technician__group=group,
            task__task_type__operation_type=OperationType.MAINTENANCE,
            start_time__date=active_dt.date(),
            end_time__gt=active_dt,
        ).values_list("task_id", flat=True).distinct()
    )


def _delete_schedules_for_task_ids(task_ids: Iterable[int]) -> int:
    ids = list(set(task_ids))
    if not ids:
        return 0
    qs = Schedule.objects.filter(task_id__in=ids)
    count = qs.count()
    qs.delete()
    return count


def rebuild_group_instant_leave_schedule(
    group: SupervisorGroup,
    *,
    leave_request: Optional[LeaveRequest] = None,
    active_dt: Optional[datetime] = None,
    end_date: Optional[date] = None,
    request=None,
) -> dict:
    """Emergency/instant leave rebuild.

    Difference from normal planned leave rebuild:
        * planned leave keeps the current roll-date day frozen and rebuilds a
          future interval.
        * instant leave starts immediately at the roll-date clock. It preserves
          already-finished work on the active day, removes the remaining/current
          tasks from that day, and re-solves those remaining tasks plus generated
          future days using Gurobi.

    This function is intentionally console/dashboard friendly: no mobile app is
    required for the current demo.
    """
    active_dt = active_dt or _get_active_datetime(request)
    if timezone.is_naive(active_dt):
        active_dt = timezone.make_aware(active_dt)

    effective_date = active_dt.date()
    latest = _latest_future_date(group, effective_date)
    end_date = end_date or latest

    if end_date is None or end_date < effective_date:
        return {
            "triggered": False,
            "reason": "No generated maintenance schedule exists at/after the instant leave date.",
            "effective_date": effective_date.isoformat(),
            "active_datetime": active_dt.isoformat(),
            "end_date": None,
        }

    active_techs = _active_maintenance_technicians(group)
    if active_techs == 0:
        return {
            "triggered": False,
            "reason": "No active located maintenance technicians remain for this group.",
            "effective_date": effective_date.isoformat(),
            "active_datetime": active_dt.isoformat(),
            "end_date": end_date.isoformat(),
            "active_technicians": active_techs,
        }

    # Current day: only tasks not finished by the accident/emergency time.
    tasks_by_day: Dict[date, Set[int]] = defaultdict(set)
    current_remaining = _remaining_task_ids_after(group, active_dt)
    if current_remaining:
        tasks_by_day[effective_date].update(current_remaining)

    # Future days: full-day rebuild, same as the planned leave behavior.
    if effective_date + timedelta(days=1) <= end_date:
        for d, ids in _future_tasks_by_day(group, effective_date + timedelta(days=1), end_date).items():
            tasks_by_day[d].update(ids)

    all_task_ids = sorted({tid for ids in tasks_by_day.values() for tid in ids})
    if not all_task_ids:
        return {
            "triggered": False,
            "reason": "No remaining/current or future maintenance tasks were found to rebuild.",
            "effective_date": effective_date.isoformat(),
            "active_datetime": active_dt.isoformat(),
            "end_date": end_date.isoformat(),
            "active_technicians": active_techs,
        }

    _set_tasks_waiting(all_task_ids, active=False)

    # Delete only the work we will re-plan. For active day this preserves
    # already-finished rows before the emergency time; for future days all rows
    # are replanned.
    deleted_schedules = _delete_schedules_for_task_ids(all_task_ids)
    deleted_runs = _cleanup_empty_runs()

    total_rows = 0
    solved_days = 0
    log_lines = []

    for day in sorted(tasks_by_day.keys()):
        ids = sorted(tasks_by_day[day])
        if not ids:
            continue

        _set_tasks_waiting(ids, active=True)
        last_run_id = OptimizationRun.objects.order_by("-id").values_list("id", flat=True).first() or 0

        on_leave = _approved_leave_technicians_for_day(group, day)
        _set_temporarily_unavailable(on_leave)

        buf = StringIO()
        try:
            with redirect_stdout(buf):
                call_command(
                    "solve_group",
                    group.name,
                    task_ids=",".join(str(i) for i in ids),
                    working_days=1,
                    verbosity=0,
                )
        finally:
            _restore_available(on_leave)
            _set_tasks_waiting(ids, active=False)

        if on_leave:
            names = ", ".join(t.full_name for t in on_leave)
            log_lines.append(f"{day}: excluded approved/instant leave technicians: {names}")

        new_run = OptimizationRun.objects.filter(id__gt=last_run_id).order_by("-id").first()
        if new_run is None:
            log_lines.append(f"{day}: no new run was created")
            continue

        # On the active day, move the newly solved route after the roll clock.
        # On later days, use the normal 08:00-based daily schedule.
        rows = _finish_day_tasks(
            day,
            ids,
            new_run.id,
            not_before=active_dt if day == effective_date else None,
        )
        total_rows += rows
        solved_days += 1
        log_lines.extend([x.strip() for x in buf.getvalue().splitlines() if x.strip()][-3:])
        log_lines.append(f"{day}: instant-leave rebuilt {rows} schedule rows in run #{new_run.id}")

    return {
        "triggered": True,
        "mode": "instant_leave",
        "effective_date": effective_date.isoformat(),
        "active_datetime": active_dt.isoformat(),
        "end_date": end_date.isoformat(),
        "leave_request_id": leave_request.id if leave_request is not None else None,
        "active_technicians": active_techs,
        "remaining_current_day_tasks": len(current_remaining),
        "future_tasks": len(all_task_ids),
        "deleted_schedules": deleted_schedules,
        "deleted_empty_runs": deleted_runs,
        "solved_days": solved_days,
        "new_schedule_rows": total_rows,
        "log_tail": log_lines[-20:],
    }

# ---------------------------------------------------------------------------
# Callback roster rebuild
# ---------------------------------------------------------------------------
# Callback roster changes use a different rebuild path from maintenance:
#   * keep the already generated callback Task demand
#   * delete future callback Schedule rows for this callback supervisor group
#   * re-run the existing Gurobi breakdown solver day-by-day
#   * lay each technician's callback route out sequentially on that day
# This makes add/remove/reactivate work for Yusuf Arslan / Can Doğan callback
# groups exactly like maintenance, but without synthesizing new callback demand.

CALLBACK_ROAD_FACTOR = 1.35
CALLBACK_SPEED_KMH = 30.0
CALLBACK_DAY_START_MIN = 8 * 60
CALLBACK_SERVICE_MIN = 60


def _minutes_to_time(minutes: float) -> time:
    m = max(0, int(round(minutes)))
    h, mm = divmod(m, 60)
    h = min(h, 23)
    return time(h, mm)


def _latest_future_callback_date(group: SupervisorGroup, effective_date: date) -> Optional[date]:
    latest_schedule = (
        Schedule.objects
        .filter(
            technician__group=group,
            task__task_type__operation_type=OperationType.CALLBACK,
            start_time__date__gte=effective_date,
        )
        .aggregate(mx=Max("start_time"))
        .get("mx")
    )

    latest_task = (
        Task.objects
        .filter(
            assigned_group=group,
            task_type__operation_type=OperationType.CALLBACK,
            planning_period__start_date__gte=effective_date,
        )
        .aggregate(mx=Max("planning_period__start_date"))
        .get("mx")
    )

    dates = [d for d in (_as_date(latest_schedule), _as_date(latest_task)) if d is not None]
    return max(dates) if dates else None


def _callback_tasks_by_day(group: SupervisorGroup, effective_date: date, end_date: date) -> Dict[date, Set[int]]:
    out: Dict[date, Set[int]] = defaultdict(set)
    qs = (
        Task.objects
        .filter(
            assigned_group=group,
            task_type__operation_type=OperationType.CALLBACK,
            planning_period__start_date__gte=effective_date,
            planning_period__start_date__lte=end_date,
        )
        .select_related("planning_period")
        .values("id", "planning_period__start_date")
    )
    for row in qs:
        d = row["planning_period__start_date"]
        if d is not None:
            out[d].add(row["id"])
    return out


def _active_callback_technicians(group: SupervisorGroup) -> int:
    return Technician.objects.filter(
        group=group,
        tech_role=TechnicianRole.CALLBACK,
        is_active_employee=True,
        is_available=True,
        current_latitude__isnull=False,
        current_longitude__isnull=False,
    ).count()


def _approved_callback_leave_technicians_for_day(group: SupervisorGroup, day: date):
    return list(
        Technician.objects.filter(
            group=group,
            tech_role=TechnicianRole.CALLBACK,
            is_active_employee=True,
            is_available=True,
            current_latitude__isnull=False,
            current_longitude__isnull=False,
            leave_requests__status=LeaveRequest.LeaveStatus.APPROVED,
            leave_requests__start_date__lte=day,
            leave_requests__end_date__gte=day,
        ).distinct()
    )


def _delete_future_callback_schedules(group: SupervisorGroup, effective_date: date) -> int:
    qs = Schedule.objects.filter(
        technician__group=group,
        task__task_type__operation_type=OperationType.CALLBACK,
        start_time__date__gte=effective_date,
    )
    count = qs.count()
    qs.delete()
    return count


def _callback_technicians_for_day(group: SupervisorGroup, day: date):
    """Active callback techs, with approved leave excluded for this day."""
    qs = Technician.objects.filter(
        group=group,
        tech_role=TechnicianRole.CALLBACK,
        is_active_employee=True,
        is_available=True,
        current_latitude__isnull=False,
        current_longitude__isnull=False,
    ).select_related("group")

    leave_ids = [t.id for t in _approved_callback_leave_technicians_for_day(group, day)]
    if leave_ids:
        qs = qs.exclude(id__in=leave_ids)
    return list(qs)


def _solve_callback_day(group: SupervisorGroup, day: date, task_ids: Iterable[int]) -> dict:
    ids = sorted(set(int(x) for x in task_ids))
    tasks = list(
        Task.objects
        .filter(id__in=ids, task_type__operation_type=OperationType.CALLBACK)
        .select_related("unit", "task_type", "planning_period", "assigned_group")
        .order_by("id")
    )
    techs = _callback_technicians_for_day(group, day)

    if not tasks:
        return {"run_id": None, "assigned": 0, "unassigned": 0, "reason": "No callback tasks."}

    if not techs:
        Task.objects.filter(id__in=ids).update(
            status=TaskStatus.UNASSIGNED,
            is_unassigned=True,
            unassigned_reason="No active available callback technicians in this group.",
            is_active=False,
        )
        return {"run_id": None, "assigned": 0, "unassigned": len(tasks), "reason": "No active callback technicians."}

    tt_time, tt_dist = {}, {}
    for tech in techs:
        for task in tasks:
            u = task.unit
            if u.latitude is None or u.longitude is None:
                continue
            km = haversine_distance_km(
                tech.current_latitude,
                tech.current_longitude,
                u.latitude,
                u.longitude,
            ) * CALLBACK_ROAD_FACTOR
            tt_time[(tech.id, task.id)] = km / CALLBACK_SPEED_KMH
            tt_dist[(tech.id, task.id)] = km

    input_data = {
        "tasks": tasks,
        "technicians": techs,
        "technician_task_travel_time": tt_time,
        "technician_task_travel_distance": tt_dist,
    }

    results = solve_with_gurobi(input_data)
    period = tasks[0].planning_period
    creator = group.supervisor or User.objects.filter(is_superuser=True).first() or User.objects.first()
    run = OptimizationRun.objects.create(
        planning_period=period,
        triggered_by=creator,
        status=RunStatus.RUNNING,
        started_at=timezone.now(),
        solver_name="gurobi-callback-roster",
    )
    write_optimization_results(run, results)
    run.status = RunStatus.FEASIBLE
    run.finished_at = timezone.now()
    run.summary = f"Gurobi callback roster rebuild for {group.name} on {day.isoformat()}."
    run.save()

    # Lay out callback stops sequentially per technician on the target day.
    scheds = list(
        Schedule.objects
        .filter(optimization_run=run)
        .select_related("task", "technician", "technician__group")
        .order_by("technician_id", "sequence_order", "id")
    )
    by_tech = defaultdict(list)
    for s in scheds:
        by_tech[s.technician_id].append(s)

    assigned = 0
    with transaction.atomic():
        for _tid, group_scheds in by_tech.items():
            clock = CALLBACK_DAY_START_MIN
            for s in group_scheds:
                travel = s.travel_time_min or 0
                arrive = clock + travel
                dur = s.task.estimated_duration_min or CALLBACK_SERVICE_MIN
                s.start_time = _combine(day, _minutes_to_time(arrive))
                s.end_time = _combine(day, _minutes_to_time(arrive + dur))
                s.save(update_fields=["start_time", "end_time"])
                clock = arrive + dur

                if s.technician and s.technician.group:
                    s.task.assigned_group = s.technician.group
                s.task.status = TaskStatus.COMPLETED
                s.task.is_unassigned = False
                s.task.unassigned_reason = None
                s.task.is_active = False
                s.task.save(update_fields=[
                    "assigned_group", "status", "is_unassigned", "unassigned_reason", "is_active"
                ])
                assigned += 1

        # Freeze unassigned callback tasks as historical unassigned rows for reporting.
        Task.objects.filter(id__in=ids).exclude(status=TaskStatus.COMPLETED).update(is_active=False)

    unassigned = len(tasks) - assigned
    return {"run_id": run.id, "assigned": assigned, "unassigned": unassigned}


def rebuild_group_future_callbacks(
    group: SupervisorGroup,
    *,
    effective_date: Optional[date] = None,
    end_date: Optional[date] = None,
    request=None,
) -> dict:
    """Re-solve this callback supervisor group's future callback tasks.

    This is the callback equivalent of rebuild_group_future_schedule(). It is
    used by callback technician add/remove/reactivate. It preserves generated
    callback demand and only changes technician assignments/times from the next
    roll-date day onward.
    """
    effective_date = effective_date or next_day_from_roll_date(request)
    end_date = end_date or _latest_future_callback_date(group, effective_date)

    if end_date is None or end_date < effective_date:
        return {
            "triggered": False,
            "reason": "No generated future callback schedule exists for this group.",
            "effective_date": effective_date.isoformat(),
            "end_date": None,
        }

    active_techs = _active_callback_technicians(group)
    if active_techs == 0:
        return {
            "triggered": False,
            "reason": "No active located callback technicians remain for this group.",
            "effective_date": effective_date.isoformat(),
            "end_date": end_date.isoformat(),
            "active_technicians": active_techs,
        }

    tasks_by_day = _callback_tasks_by_day(group, effective_date, end_date)
    all_task_ids = sorted({tid for ids in tasks_by_day.values() for tid in ids})
    if not all_task_ids:
        return {
            "triggered": False,
            "reason": "No future callback tasks were found to rebuild.",
            "effective_date": effective_date.isoformat(),
            "end_date": end_date.isoformat(),
            "active_technicians": active_techs,
        }

    _set_tasks_waiting(all_task_ids, active=False)
    deleted_schedules = _delete_future_callback_schedules(group, effective_date)
    deleted_runs = _cleanup_empty_runs()

    total_rows = 0
    total_unassigned = 0
    solved_days = 0
    log_lines = []

    for day in sorted(tasks_by_day.keys()):
        ids = sorted(tasks_by_day[day])
        if not ids:
            continue

        _set_tasks_waiting(ids, active=True)
        try:
            result = _solve_callback_day(group, day, ids)
        finally:
            _set_tasks_waiting(ids, active=False)

        total_rows += int(result.get("assigned") or 0)
        total_unassigned += int(result.get("unassigned") or 0)
        if result.get("run_id"):
            solved_days += 1
            log_lines.append(
                f"{day}: callback rebuilt {result.get('assigned')} rows, "
                f"{result.get('unassigned')} unassigned in run #{result.get('run_id')}"
            )
        else:
            log_lines.append(f"{day}: callback rebuild skipped - {result.get('reason')}")

    return {
        "triggered": True,
        "mode": "callback_roster",
        "effective_date": effective_date.isoformat(),
        "end_date": end_date.isoformat(),
        "active_technicians": active_techs,
        "future_tasks": len(all_task_ids),
        "deleted_schedules": deleted_schedules,
        "deleted_empty_runs": deleted_runs,
        "solved_days": solved_days,
        "new_schedule_rows": total_rows,
        "unassigned_tasks": total_unassigned,
        "log_tail": log_lines[-20:],
    }



# ---------------------------------------------------------------------------
# Callback instant/emergency leave rebuild
# ---------------------------------------------------------------------------

def _remaining_callback_task_ids_after(group: SupervisorGroup, active_dt: datetime) -> Set[int]:
    """Callback tasks not safely completed at the emergency time.

    Finished callback rows before active_dt are kept as operational history.
    The current in-progress callback row and all later rows on the active date
    are treated as remaining demand and are re-optimized.
    """
    if timezone.is_naive(active_dt):
        active_dt = timezone.make_aware(active_dt)
    return set(
        Schedule.objects.filter(
            technician__group=group,
            task__task_type__operation_type=OperationType.CALLBACK,
            start_time__date=active_dt.date(),
            end_time__gt=active_dt,
        ).values_list("task_id", flat=True).distinct()
    )


def _shift_callback_run_after(run_id: int, task_ids: Iterable[int], day: date, active_dt: datetime) -> int:
    """Move callback schedules produced for the active day after active_dt.

    _solve_callback_day lays routes from 08:00. For instant leave on an
    already-running day, we keep the route order but shift it so the newly
    planned remaining route begins at/after the current roll datetime.
    """
    ids = set(int(x) for x in task_ids)
    if timezone.is_naive(active_dt):
        active_dt = timezone.make_aware(active_dt)

    day_start = timezone.make_aware(datetime.combine(day, time(8, 0)))
    scheds = (
        Schedule.objects
        .filter(optimization_run_id=run_id, task_id__in=ids)
        .select_related("task", "technician")
        .order_by("technician_id", "sequence_order", "id")
    )

    n = 0
    with transaction.atomic():
        for s in scheds:
            if s.start_time:
                rebased_start = _combine(day, s.start_time)
                rebased_start = active_dt + max(rebased_start - day_start, timedelta(0))
                s.start_time = rebased_start
            if s.end_time:
                rebased_end = _combine(day, s.end_time)
                rebased_end = active_dt + max(rebased_end - day_start, timedelta(0))
                s.end_time = rebased_end
            s.save(update_fields=["start_time", "end_time"])
            n += 1
    return n


def rebuild_group_instant_callback_leave_schedule(
    group: SupervisorGroup,
    *,
    leave_request: Optional[LeaveRequest] = None,
    active_dt: Optional[datetime] = None,
    end_date: Optional[date] = None,
    request=None,
) -> dict:
    """Emergency/instant leave rebuild for CALLBACK technicians.

    Callback technicians remain callback technicians. This function only
    re-optimizes callback tasks for Yusuf Arslan / Can Doğan style callback
    groups. It preserves already-finished current-day callback work, removes
    remaining/current-day callback work plus generated future callback work,
    and re-solves those callback tasks with active callback technicians.
    """
    active_dt = active_dt or _get_active_datetime(request)
    if timezone.is_naive(active_dt):
        active_dt = timezone.make_aware(active_dt)

    effective_date = active_dt.date()
    latest = _latest_future_callback_date(group, effective_date)
    end_date = end_date or latest

    if end_date is None or end_date < effective_date:
        return {
            "triggered": False,
            "reason": "No generated callback schedule exists at/after the instant leave date.",
            "effective_date": effective_date.isoformat(),
            "active_datetime": active_dt.isoformat(),
            "end_date": None,
        }

    active_techs = _active_callback_technicians(group)
    if active_techs == 0:
        return {
            "triggered": False,
            "reason": "No active located callback technicians remain for this group.",
            "effective_date": effective_date.isoformat(),
            "active_datetime": active_dt.isoformat(),
            "end_date": end_date.isoformat(),
            "active_technicians": active_techs,
        }

    tasks_by_day: Dict[date, Set[int]] = defaultdict(set)

    current_remaining = _remaining_callback_task_ids_after(group, active_dt)
    if current_remaining:
        tasks_by_day[effective_date].update(current_remaining)

    if effective_date + timedelta(days=1) <= end_date:
        for d, ids in _callback_tasks_by_day(group, effective_date + timedelta(days=1), end_date).items():
            tasks_by_day[d].update(ids)

    all_task_ids = sorted({tid for ids in tasks_by_day.values() for tid in ids})
    if not all_task_ids:
        return {
            "triggered": False,
            "reason": "No remaining/current or future callback tasks were found to rebuild.",
            "effective_date": effective_date.isoformat(),
            "active_datetime": active_dt.isoformat(),
            "end_date": end_date.isoformat(),
            "active_technicians": active_techs,
        }

    _set_tasks_waiting(all_task_ids, active=False)
    deleted_schedules = _delete_schedules_for_task_ids(all_task_ids)
    deleted_runs = _cleanup_empty_runs()

    total_rows = 0
    total_unassigned = 0
    solved_days = 0
    log_lines = []

    for day in sorted(tasks_by_day.keys()):
        ids = sorted(tasks_by_day[day])
        if not ids:
            continue

        _set_tasks_waiting(ids, active=True)
        try:
            result = _solve_callback_day(group, day, ids)
        finally:
            _set_tasks_waiting(ids, active=False)

        if result.get("run_id") and day == effective_date:
            # Same-day instant leave: keep finished rows as history and shift
            # the newly optimized remaining callback route after the roll clock.
            _shift_callback_run_after(int(result["run_id"]), ids, day, active_dt)

        total_rows += int(result.get("assigned") or 0)
        total_unassigned += int(result.get("unassigned") or 0)
        if result.get("run_id"):
            solved_days += 1
            log_lines.append(
                f"{day}: instant callback leave rebuilt {result.get('assigned')} rows, "
                f"{result.get('unassigned')} unassigned in run #{result.get('run_id')}"
            )
        else:
            log_lines.append(f"{day}: instant callback rebuild skipped - {result.get('reason')}")

    return {
        "triggered": True,
        "mode": "instant_callback_leave",
        "effective_date": effective_date.isoformat(),
        "active_datetime": active_dt.isoformat(),
        "end_date": end_date.isoformat(),
        "leave_request_id": leave_request.id if leave_request is not None else None,
        "active_technicians": active_techs,
        "remaining_current_day_tasks": len(current_remaining),
        "future_tasks": len(all_task_ids),
        "deleted_schedules": deleted_schedules,
        "deleted_empty_runs": deleted_runs,
        "solved_days": solved_days,
        "new_schedule_rows": total_rows,
        "unassigned_tasks": total_unassigned,
        "log_tail": log_lines[-20:],
    }
