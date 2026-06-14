"""
api/management/commands/complete_day.py
=============================================================================
Simulate a finished work-day: mark the day's SCHEDULED maintenance tasks as
completed and advance each unit's maintenance clock.

  * Only tasks that were actually SCHEDULED (have a Schedule row) are completed.
  * Tasks that were never assigned stay PENDING -> they remain due and show as
    OVERDUE on later days (matches "flag units with incomplete maintenance").

This lets you roll the cycle forward day by day:

    python manage.py run_maintenance_cycle --date 2026-06-15
    python manage.py solve_group "Ahmet Yılmaz Group"
    python manage.py complete_day --date 2026-06-15        # advance clocks
    python manage.py run_maintenance_cycle --date 2026-06-16
    ...                                                     # next day's due set differs
=============================================================================
"""
from datetime import date as date_cls

from django.core.management.base import BaseCommand
from django.db.models import Q

from api.models import Schedule, Task, TaskStatus
from api.services.maintenance_cycle import complete_task


class Command(BaseCommand):
    help = "Mark a day's scheduled maintenance tasks complete and advance the cycle."

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, default=None,
                            help="The day to complete YYYY-MM-DD (default today).")
        parser.add_argument("--group", type=str, default=None,
                            help="Optional: only complete tasks for this group name.")

    def handle(self, *args, **opts):
        on_date = (date_cls.fromisoformat(opts["date"]) if opts["date"]
                   else date_cls.today())

        # find scheduled maintenance tasks for that planning day
        sched_qs = Schedule.objects.select_related("task", "task__assigned_group",
                                                   "task__task_type", "task__unit")
        sched_qs = sched_qs.filter(task__planning_period__start_date=on_date)
        if opts["group"]:
            sched_qs = sched_qs.filter(task__assigned_group__name=opts["group"])

        seen = set()
        counts = {"A": 0, "B": 0, "C": 0, "other": 0}
        for s in sched_qs:
            t = s.task
            if t is None or t.id in seen:
                continue
            seen.add(t.id)
            if t.status == TaskStatus.COMPLETED:
                continue
            mtype = complete_task(t, on_date)
            counts[mtype if mtype else "other"] += 1

        total = counts["A"] + counts["B"] + counts["C"]
        self.stdout.write(self.style.SUCCESS(
            f"Completed {on_date}: A={counts['A']} B={counts['B']} C={counts['C']} "
            f"(maintenance total {total}; other {counts['other']}). Unit clocks advanced."))

        # report what stayed undone (still PENDING for that day) = overdue carryover
        undone = (Task.objects.filter(planning_period__start_date=on_date,
                                      status=TaskStatus.PENDING,
                                      task_no__startswith="MNT-").count())
        if undone:
            self.stdout.write(self.style.WARNING(
                f"{undone} maintenance tasks were NOT scheduled/done -> remain due (overdue)."))
