from datetime import datetime, timedelta

from django.utils import timezone

from api.models import OperationType

from .optimizer_v4 import (
    SolverConfig,
    solve_maintenance_from_records,
    solve_breakdown_from_records,
)


def _region_from_group(technician):
    if technician.group and technician.group.region:
        return technician.group.region
    return "Unknown"


def _region_from_task(task):
    if task.assigned_group and task.assigned_group.region:
        return task.assigned_group.region

    if task.unit.district:
        return task.unit.district

    return "Unknown"


def _role_to_optimizer_role(tech_role):
    if tech_role == "MAINTENANCE":
        return "Maintenance"

    # New model: CALLBACK is the breakdown/emergency role.
    if tech_role == "CALLBACK":
        return "Breakdown"

    # Backward-compat: tolerate any legacy values still in the DB.
    if tech_role == "REPAIR":
        return "Breakdown"

    if tech_role == "BOTH":
        return "Both"

    return "Unknown"


def _specialty_to_optimizer_skill(specialty):
    if specialty == "ELEVATOR":
        return "Elevator"

    if specialty == "ESCALATOR":
        return "Escalator"

    if specialty == "BOTH":
        return "Both"

    return "Unknown"


def _unit_type_to_optimizer_type(unit_type):
    if unit_type == "ELEVATOR":
        return "Elevator"

    if unit_type == "ESCALATOR":
        return "Escalator"

    return "Unknown"

def _is_avm_escalator(unit):
    venue_type = str(getattr(unit, "venue_type", "") or "").strip().lower()

    is_avm = venue_type in [
        "avm",
        "mall",
        "shopping mall",
        "alışveriş merkezi",
        "alisveris merkezi",
    ]

    unit_type = _unit_type_to_optimizer_type(unit.unit_type)

    return unit_type == "Escalator" and is_avm

def _maintenance_package(task):
    mt = task.task_type.maintenance_type

    if mt in ["A", "B", "C"]:
        return mt

    return "C"


def _technicians_to_records(technicians):
    records = []

    for tech in technicians:
        available_hours = (
            tech.daily_capacity_min + tech.max_overtime_min
        ) / 60

        records.append({
            "technician_id": str(tech.id),
            "technician_name": tech.full_name,
            "role": _role_to_optimizer_role(tech.tech_role),
            "skill_type": _specialty_to_optimizer_skill(tech.specialty),
            "region": _region_from_group(tech),
            "available_hours": available_hours,
            "shift_start": tech.work_start.strftime("%H:%M") if tech.work_start else "08:00",
            "shift_end": tech.work_end.strftime("%H:%M") if tech.work_end else "17:00",
            "latitude": float(tech.current_latitude) if tech.current_latitude is not None else None,
            "longitude": float(tech.current_longitude) if tech.current_longitude is not None else None,
        })

    return records


def _maintenance_tasks_to_records(tasks):
    records = []

    for task in tasks:
        unit = task.unit
        unit_type = _unit_type_to_optimizer_type(unit.unit_type)

        records.append({
            "task_id": str(task.id),
            "unit_id": str(unit.id),
            "unit_name": unit.unit_name,
            "task_type": "Maintenance",
            "maintenance_type": _maintenance_package(task),
            "maintenance_package": _maintenance_package(task),
            "unit_type": unit_type,
            "region": _region_from_task(task),
            "service_time": task.estimated_duration_min / 60,
            "required_technicians": 1,
            "planned_date": str(task.planning_period.start_date),
            "latitude": float(unit.latitude) if unit.latitude is not None else None,
            "longitude": float(unit.longitude) if unit.longitude is not None else None,
            "location": unit.address,
            "venue_type": unit.venue_type or "",
            "morning_required": "YES" if _is_avm_escalator(unit) else "NO",
        })

    return records


def _breakdown_tasks_to_records(tasks):
    records = []

    for task in tasks:
        unit = task.unit

        response_limit_hours = 4.0

        if task.priority == "AA":
            response_limit_hours = 1.0

        if task.task_type.sla_target_min:
            response_limit_hours = task.task_type.sla_target_min / 60

        records.append({
            "ticket_id": str(task.id),
            "unit_id": str(unit.id),
            "unit_name": unit.unit_name,
            "task_type": "Breakdown",
            "unit_type": _unit_type_to_optimizer_type(unit.unit_type),
            "region": _region_from_task(task),
            "failure_type": task.priority or "D",
            "created_at": task.release_time.isoformat() if task.release_time else timezone.now().isoformat(),
            "response_limit_hours": response_limit_hours,
            "service_time": task.estimated_duration_min / 60,
            "status": "open",
        })

    return records


def _units_to_records(tasks):
    seen = {}

    for task in tasks:
        unit = task.unit

        if unit.id in seen:
            continue

        seen[unit.id] = {
            "unit_id": str(unit.id),
            "unit_name": unit.unit_name,
            "unit_type": _unit_type_to_optimizer_type(unit.unit_type),
            "region": _region_from_task(task),
            "location": unit.address,
            "latitude": float(unit.latitude) if unit.latitude is not None else None,
            "longitude": float(unit.longitude) if unit.longitude is not None else None,
        }

    return list(seen.values())


def _task_lookup(tasks):
    return {str(task.id): task for task in tasks}


def _technician_lookup(technicians):
    return {str(tech.id): tech for tech in technicians}


def _parse_time_for_task(base_date, value):
    if not value:
        return None

    try:
        parsed = datetime.strptime(str(value), "%H:%M").time()
        return timezone.make_aware(
            datetime.combine(base_date, parsed)
        )
    except Exception:
        return None


def _base_date_from_row(tasks, row):
    base_date = tasks[0].planning_period.start_date if tasks else timezone.now().date()

    work_day = row.get("work_day")

    try:
        if work_day:
            return base_date + timedelta(days=int(work_day) - 1)
    except Exception:
        pass

    return base_date


def _maintenance_result_to_schedule_results(result, tasks, technicians):
    task_map = _task_lookup(tasks)
    tech_map = _technician_lookup(technicians)

    output = []

    for row in result.get("assignments", []):
        task_id = str(row.get("task_id"))
        technician_id = str(row.get("technician_id"))

        task = task_map.get(task_id)
        technician = tech_map.get(technician_id)

        if not task or not technician:
            continue

        schedule_date = _base_date_from_row(tasks, row)

        start_time = _parse_time_for_task(
            schedule_date,
            row.get("estimated_start_time")
        )

        end_time = _parse_time_for_task(
            schedule_date,
            row.get("estimated_end_time")
        )

        if start_time is None:
            start_time = timezone.make_aware(
                datetime.combine(schedule_date, datetime.min.time())
            ).replace(hour=9, minute=0, second=0, microsecond=0)

        if end_time is None:
            end_time = start_time + timedelta(minutes=task.estimated_duration_min)

        output.append({
            "task": task,
            "technician": technician,
            "start_time": start_time,
            "end_time": end_time,
            "sequence_order": row.get("route_order") or 1,
            "travel_time_min": int(round(float(row.get("travel_time", 0)) * 60)),
            "travel_distance_km": 0,
        })

    for row in result.get("unassigned_tasks", []):
        task_id = str(row.get("task_id"))
        task = task_map.get(task_id)

        if task:
            output.append({
                "task": task,
                "technician": None,
                "unassigned_reason": row.get("reason", "Unassigned by Gurobi"),
            })

    return output


def _breakdown_result_to_schedule_results(result, tasks, technicians):
    task_map = _task_lookup(tasks)
    tech_map = _technician_lookup(technicians)

    output = []
    now = timezone.now()

    for row in result.get("assignments", []):
        task_id = str(row.get("ticket_id"))
        technician_id = str(row.get("technician_id"))

        task = task_map.get(task_id)
        technician = tech_map.get(technician_id)

        if not task or not technician:
            continue

        start_time = now
        end_time = start_time + timedelta(minutes=task.estimated_duration_min)

        output.append({
            "task": task,
            "technician": technician,
            "start_time": start_time,
            "end_time": end_time,
            "sequence_order": row.get("dispatch_order") or 1,
            "travel_time_min": int(round(float(row.get("estimated_travel_time", 0)) * 60)),
            "travel_distance_km": 0,
        })

    for row in result.get("unassigned_tasks", []):
        task_id = str(row.get("ticket_id"))
        task = task_map.get(task_id)

        if task:
            output.append({
                "task": task,
                "technician": None,
                "unassigned_reason": row.get("reason", "Unassigned by Gurobi"),
            })

    return output


def _build_technician_to_task_travel_matrix(
    tasks,
    technicians,
    technician_task_travel_time
):
    matrix = {}

    for technician in technicians:
        tech_id = str(technician.id)
        matrix[tech_id] = {}

        for task in tasks:
            task_id = str(task.id)

            travel_time = technician_task_travel_time.get(
                (technician.id, task.id),
                0.25
            )

            matrix[tech_id][task_id] = travel_time

    return matrix


def solve_with_gurobi(input_data):
    tasks = input_data["tasks"]
    technicians = input_data["technicians"]

    technician_task_travel_time = input_data.get(
        "technician_task_travel_time",
        {}
    )

    if not tasks or not technicians:
        return []

    maintenance_tasks = [
        task for task in tasks
        if task.task_type.operation_type == OperationType.MAINTENANCE
    ]

    breakdown_tasks = [
        task for task in tasks
        if task.task_type.operation_type in [
            OperationType.CALLBACK,
            OperationType.FOLLOW_UP,
        ]
    ]

    technician_records = _technicians_to_records(technicians)

    final_results = []

    config = SolverConfig()

    if maintenance_tasks:
        maintenance_task_records = _maintenance_tasks_to_records(
            maintenance_tasks
        )

        maintenance_travel_time_matrix = _build_technician_to_task_travel_matrix(
            maintenance_tasks,
            technicians,
            technician_task_travel_time,
        )

        maintenance_result = solve_maintenance_from_records(
            technician_records=technician_records,
            task_records=maintenance_task_records,
            travel_time_matrix=maintenance_travel_time_matrix,
            config=config,
        )

        final_results.extend(
            _maintenance_result_to_schedule_results(
                maintenance_result,
                maintenance_tasks,
                technicians,
            )
        )

    if breakdown_tasks:
        breakdown_ticket_records = _breakdown_tasks_to_records(
            breakdown_tasks
        )

        unit_records = _units_to_records(breakdown_tasks)

        breakdown_travel_time_matrix = _build_technician_to_task_travel_matrix(
            breakdown_tasks,
            technicians,
            technician_task_travel_time,
        )

        breakdown_result = solve_breakdown_from_records(
            technician_records=technician_records,
            ticket_records=breakdown_ticket_records,
            unit_records=unit_records,
            travel_time_matrix=breakdown_travel_time_matrix,
            config=config,
        )

        final_results.extend(
            _breakdown_result_to_schedule_results(
                breakdown_result,
                breakdown_tasks,
                technicians,
            )
        )

    return final_results