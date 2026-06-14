from api.models import Task, Technician, AvailabilityRequest, TaskStatus, RequestStatus
from api.services.maps.distance_service import get_or_create_unit_distance

def build_optimization_input(planning_period):
    tasks = Task.objects.filter(
        planning_period=planning_period,
        is_active=True
    ).select_related("unit", "task_type", "assigned_group")

    technicians = Technician.objects.filter(
        is_active_employee=True,
        is_available=True
    ).select_related("group")

    approved_requests = AvailabilityRequest.objects.filter(
        status=RequestStatus.APPROVED
    ).select_related("technician")

    return {
        "tasks": list(tasks),
        "technicians": list(technicians),
        "approved_requests": list(approved_requests),
    }
def build_task_to_task_travel_matrix(tasks):
    travel_time = {}
    travel_distance = {}

    for origin_task in tasks:
        for destination_task in tasks:
            if origin_task.id == destination_task.id:
                continue

            data = get_or_create_unit_distance(
                origin_task.unit,
                destination_task.unit,
            )

            travel_time[(origin_task.id, destination_task.id)] = data["duration_seconds"] / 60
            travel_distance[(origin_task.id, destination_task.id)] = data["distance_meters"] / 1000

    return travel_time, travel_distance