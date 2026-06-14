"""
api/services/maintenance_cycle.py
=============================================================================
Single source of truth for COMPLETING a maintenance task and advancing the
unit's maintenance clock.

A worker typically has several tasks in a day (a route). Each unit is completed
independently as the worker reaches it, so completion is PER-TASK:

    complete_task(task, on_date)
        -> sets task.status = COMPLETED
        -> advances that unit's UnitMaintenanceState (A>B>C supersession)

This is called by:
  * the dashboard "mark done" button (real path, one task at a time), and
  * the complete_day simulation command (loops over a day's scheduled tasks).
=============================================================================
"""
from datetime import date as date_cls

from django.utils import timezone

from api.models import UnitMaintenanceState, TaskStatus, MaintenanceType


def complete_task(task, on_date=None):
    """Mark one maintenance task complete and advance its unit's clock.

    Returns the maintenance type completed ('A'/'B'/'C') or None if the task
    is not a maintenance task with a maintenance_type.
    """
    if on_date is None:
        on_date = date_cls.today()

    # set the task itself complete
    task.status = TaskStatus.COMPLETED
    if hasattr(task, "completed_at"):
        task.completed_at = timezone.now()
    task.save(update_fields=["status"] + (["completed_at"] if hasattr(task, "completed_at") else []))

    # figure out the maintenance type from the task's task_type
    mtype = None
    tt = getattr(task, "task_type", None)
    if tt is not None:
        mt = getattr(tt, "maintenance_type", None)
        if mt in (MaintenanceType.A, MaintenanceType.B, MaintenanceType.C):
            mtype = mt

    if mtype is None:
        return None  # not a cyclic maintenance task (e.g. a callback)

    # advance the unit's clock (creates state if missing)
    state, _ = UnitMaintenanceState.objects.get_or_create(unit=task.unit)
    state.complete(mtype, on_date)
    return mtype
