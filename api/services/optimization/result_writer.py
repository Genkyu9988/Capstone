from api.models import Schedule, TaskStatus


def write_optimization_results(run, results):
    assigned_count = 0
    unassigned_count = 0

    # Aynı run için eski schedule varsa temizle
    Schedule.objects.filter(optimization_run=run).delete()

    for result in results:
        task = result["task"]

        if result.get("technician") is None:
            task.is_unassigned = True
            task.unassigned_reason = result.get("unassigned_reason", "Unassigned")
            task.status = TaskStatus.UNASSIGNED
            task.save()
            unassigned_count += 1
            continue

        Schedule.objects.create(
            task=task,
            technician=result["technician"],
            optimization_run=run,
            start_time=result["start_time"],
            end_time=result["end_time"],
            sequence_order=result["sequence_order"],
            travel_time_min=result.get("travel_time_min"),
            travel_distance_km=result.get("travel_distance_km"),
            source="AUTO",
        )

        task.is_unassigned = False
        task.unassigned_reason = None
        task.status = TaskStatus.ASSIGNED
        task.save()

        assigned_count += 1

    run.assigned_task_count = assigned_count
    run.unassigned_task_count = unassigned_count
    run.save()