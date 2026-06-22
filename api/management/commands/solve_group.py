"""
api/management/commands/solve_group.py
=============================================================================
Offline (no-Google) maintenance solve for ANY supervisor group.

    python manage.py solve_group "Demo Group"
    python manage.py solve_group "Emre Koç Group"

Builds a haversine technician->task travel matrix (so the Routes API is never
called), runs your existing solve_with_gurobi (Gurobi maintenance MILP), and
writes the Schedule routes.
=============================================================================
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
import json

from api.models import (
    SupervisorGroup, Technician, Task, OptimizationRun, RunStatus,
    OperationType, TechnicianRole,
)
from api.services.optimization.solver import solve_with_gurobi
from api.services.optimization.result_writer import write_optimization_results
from api.services.maps.distance_service import haversine_distance_km

ROAD_FACTOR = 1.35
SPEED_KMH = 30.0


class Command(BaseCommand):
    help = "Run the offline maintenance solve for a supervisor group."

    def add_arguments(self, parser):
        parser.add_argument("group_name", type=str, nargs="?", default="Demo Group")
        parser.add_argument("--prior-load", type=str, default="{}")

    def handle(self, *args, **opts):
        name = opts["group_name"]
        group = SupervisorGroup.objects.filter(name=name).first()
        if group is None:
            raise CommandError(f"Group '{name}' not found.")

        techs = list(Technician.objects.filter(
            group=group,
            tech_role=TechnicianRole.MAINTENANCE,
            is_available=True, current_latitude__isnull=False,
        ))
        tasks = list(Task.objects.filter(
            assigned_group=group,
            task_type__operation_type=OperationType.MAINTENANCE,
            is_active=True,
        ).select_related("unit", "task_type", "planning_period", "assigned_group"))

        if not techs:
            raise CommandError("No located maintenance-capable technicians in the group.")
        if not tasks:
            raise CommandError("No maintenance tasks for the group.")

        self.stdout.write(f"Group '{name}': {len(techs)} maintenance-capable techs | {len(tasks)} tasks")

        tt_time, tt_dist = {}, {}
        for tech in techs:
            for task in tasks:
                u = task.unit
                if u.latitude is None or u.longitude is None:
                    continue
                km = haversine_distance_km(
                    tech.current_latitude, tech.current_longitude, u.latitude, u.longitude
                ) * ROAD_FACTOR
                tt_time[(tech.id, task.id)] = km / SPEED_KMH
                tt_dist[(tech.id, task.id)] = km

        prior_load = {}
        try:
            prior_load = {str(k): float(v) for k, v in json.loads(opts.get("prior_load") or "{}").items()}
        except Exception:
            prior_load = {}

        input_data = {
            "tasks": tasks, "technicians": techs,
            "technician_task_travel_time": tt_time,
            "technician_task_travel_distance": tt_dist,
            "prior_technician_load": prior_load,
        }

        self.stdout.write("Running Gurobi maintenance solve...")
        results = solve_with_gurobi(input_data)
        if not results:
            raise CommandError("Solver returned no results.")

        period = tasks[0].planning_period
        creator = group.supervisor or User.objects.filter(is_superuser=True).first()
        run = OptimizationRun.objects.create(
            planning_period=period, triggered_by=creator,
            status=RunStatus.RUNNING, started_at=timezone.now(),
            # Honest label (Req_45 traceability): assignment is the Gurobi
            # maintenance MILP; travel input is haversine (offline / no Google).
            solver_name="gurobi-maintenance",
        )
        write_optimization_results(run, results)
        run.status = RunStatus.FEASIBLE
        run.finished_at = timezone.now()
        run.summary = f"Gurobi maintenance solve for {name} (haversine travel)."
        run.save()

        assigned = sum(1 for r in results if r.get("technician") is not None)
        unassigned = sum(1 for r in results if r.get("technician") is None)
        routed = {r["technician"].id for r in results if r.get("technician")}
        self.stdout.write(self.style.SUCCESS(
            f"Run #{run.id}: assigned {assigned} across {len(routed)} techs, {unassigned} unassigned."))
        self.stdout.write(self.style.SUCCESS("Routes written. Open the simulation map."))
