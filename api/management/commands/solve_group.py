"""
api/management/commands/solve_group.py
=============================================================================
Offline (no-Google) maintenance solve for ANY supervisor group.

    python manage.py solve_group "Demo Group"
    python manage.py solve_group "Ahmet Yılmaz Group" --task-ids 1,2,3

Important for the web simulation / roster-change rebuild:
    solve_month and schedule_rebuild solve ONE calendar day at a time.
    Therefore this command uses working_days=1 by default. This prevents the
    optimizer from spreading one day's tasks across internal work_day 1, 2, 3...
    and then collapsing those internal days back onto the same calendar date,
    which caused overlapping tasks for the same technician.
=============================================================================
"""
import json

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api.models import (
    SupervisorGroup,
    Technician,
    Task,
    OptimizationRun,
    RunStatus,
    OperationType,
    TechnicianRole,
)
from api.services.maps.distance_service import haversine_distance_km
from api.services.optimization.optimizer_v4 import SolverConfig, solve_maintenance_from_records
from api.services.optimization.result_writer import write_optimization_results
from api.services.optimization.solver import (
    _technicians_to_records,
    _maintenance_tasks_to_records,
    _build_technician_to_task_travel_matrix,
    _maintenance_result_to_schedule_results,
)

ROAD_FACTOR = 1.35
SPEED_KMH = 30.0


class Command(BaseCommand):
    help = "Run the offline maintenance solve for a supervisor group."

    def add_arguments(self, parser):
        parser.add_argument("group_name", type=str, nargs="?", default="Demo Group")
        parser.add_argument("--prior-load", type=str, default="{}")
        parser.add_argument(
            "--task-ids",
            type=str,
            default="",
            help="Optional comma-separated Task ids. Used by next-day roster rebuild to solve one day only.",
        )
        parser.add_argument(
            "--working-days",
            type=int,
            default=1,
            help=(
                "Internal optimizer work-day horizon. Keep this at 1 for daily "
                "solve_month / roster rebuild so one calendar day's tasks cannot "
                "be spread over multiple internal days and overlap after rebasing."
            ),
        )

    def handle(self, *args, **opts):
        name = opts["group_name"]
        group = SupervisorGroup.objects.filter(name=name).first()
        if group is None:
            raise CommandError(f"Group '{name}' not found.")

        working_days = int(opts.get("working_days") or 1)
        if working_days < 1:
            raise CommandError("--working-days must be >= 1")

        techs = list(Technician.objects.filter(
            group=group,
            tech_role=TechnicianRole.MAINTENANCE,
            is_active_employee=True,
            is_available=True,
            current_latitude__isnull=False,
            current_longitude__isnull=False,
        ))

        task_qs = Task.objects.filter(
            assigned_group=group,
            task_type__operation_type=OperationType.MAINTENANCE,
            is_active=True,
        )

        raw_task_ids = (opts.get("task_ids") or "").strip()
        if raw_task_ids:
            try:
                ids = [int(x) for x in raw_task_ids.split(",") if x.strip()]
            except ValueError:
                raise CommandError("--task-ids must be a comma-separated list of integer ids.")
            task_qs = task_qs.filter(id__in=ids)

        tasks = list(task_qs.select_related("unit", "task_type", "planning_period", "assigned_group"))

        if not techs:
            raise CommandError("No located maintenance-capable technicians in the group.")
        if not tasks:
            raise CommandError("No maintenance tasks for the group.")

        self.stdout.write(
            f"Group '{name}': {len(techs)} maintenance-capable techs | "
            f"{len(tasks)} tasks | optimizer working_days={working_days}"
        )

        # Haversine technician -> task travel matrix. Values are HOURS.
        tt_time = {}
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
                ) * ROAD_FACTOR
                tt_time[(tech.id, task.id)] = km / SPEED_KMH

        try:
            prior_load = {str(k): float(v) for k, v in json.loads(opts.get("prior_load") or "{}").items()}
        except Exception:
            prior_load = {}

        technician_records = _technicians_to_records(techs)
        maintenance_task_records = _maintenance_tasks_to_records(tasks)
        maintenance_travel_time_matrix = _build_technician_to_task_travel_matrix(
            tasks,
            techs,
            tt_time,
        )

        # Critical fix: daily solves must have a 1-day internal horizon.
        # Otherwise the optimizer may place some tasks on internal work_day=2/3,
        # while solve_month/schedule_rebuild later rebases every result to the
        # same calendar date, producing overlaps in reports and maps.
        config = SolverConfig(working_days_per_month=working_days)

        self.stdout.write("Running Gurobi maintenance solve...")
        maintenance_result = solve_maintenance_from_records(
            technician_records=technician_records,
            task_records=maintenance_task_records,
            travel_time_matrix=maintenance_travel_time_matrix,
            config=config,
            prior_load=prior_load,
        )

        results = _maintenance_result_to_schedule_results(
            maintenance_result,
            tasks,
            techs,
        )
        if not results:
            raise CommandError("Solver returned no results.")

        period = tasks[0].planning_period
        creator = group.supervisor or User.objects.filter(is_superuser=True).first()
        run = OptimizationRun.objects.create(
            planning_period=period,
            triggered_by=creator,
            status=RunStatus.RUNNING,
            started_at=timezone.now(),
            solver_name="gurobi-maintenance",
        )
        write_optimization_results(run, results)
        run.status = RunStatus.FEASIBLE
        run.finished_at = timezone.now()
        run.summary = f"Gurobi maintenance solve for {name} (haversine travel, {working_days} day horizon)."
        run.save()

        assigned = sum(1 for r in results if r.get("technician") is not None)
        unassigned = sum(1 for r in results if r.get("technician") is None)
        routed = {r["technician"].id for r in results if r.get("technician")}
        self.stdout.write(self.style.SUCCESS(
            f"Run #{run.id}: assigned {assigned} across {len(routed)} techs, {unassigned} unassigned."
        ))
        self.stdout.write(self.style.SUCCESS("Routes written. Open the simulation map."))
