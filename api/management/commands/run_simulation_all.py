"""
api/management/commands/run_simulation_all.py
=============================================================================
Admin "Generate for ALL HQs" — ONE background job that generates the entire
city for a window:

    python manage.py run_simulation_all --start 2026-06-22 --end 2026-09-22 \
        [--init] [--skip-callbacks] [--status-file ...] [--log-file ...]

Steps:
  1. (optional --init) clear previous schedules + re-seed maintenance clocks,
     so the whole city starts from a clean, today-anchored state.
  2. solve_month for every maintenance HQ (the 8 maintenance/mixed groups).
  3. solve_callbacks once for the window (callbacks are already city-wide).

It writes the SAME status.json / run.log the web status endpoint already reads,
plus group-level fields (current_group / groups_done / groups_total) so the
admin UI can show "Generating <HQ> (3/8)". Per-day lines from solve_month land
in the log, so the existing date-based progress bar keeps working per group.
=============================================================================
"""
import json
import contextlib

from django.core.management.base import BaseCommand
from django.core.management import call_command

from api.models import (SupervisorGroup, Technician, TechnicianRole,
                        Schedule, LeaveRequest, Task, OptimizationRun)


def _group_type(group):
    roles = set(Technician.objects
                .filter(group=group, is_active_employee=True)
                .values_list("tech_role", flat=True))
    has_m = TechnicianRole.MAINTENANCE in roles
    has_c = TechnicianRole.CALLBACK in roles
    if has_m and has_c:
        return "mixed"
    if has_c and not has_m:
        return "callback"
    return "maintenance"


def _bulk_delete(model, chunk=400):
    """Delete every row of `model` in small batches.

    SQLite caps the number of bound variables per statement (often 999). A bulk
    .all().delete() on a large table -- or the cascading SET_NULL update on
    Task's self-referential follow-up FK -- builds an `id IN (...)` list that
    exceeds that limit ("too many SQL variables"). Deleting <chunk> ids at a
    time stays safely under it.
    """
    while True:
        ids = list(model.objects.values_list("pk", flat=True)[:chunk])
        if not ids:
            break
        model.objects.filter(pk__in=ids).delete()


class Command(BaseCommand):
    help = "Generate schedules for ALL HQs (every maintenance group + callbacks)."

    def add_arguments(self, parser):
        parser.add_argument("--start", required=True)
        parser.add_argument("--end", required=True)
        parser.add_argument("--status-file", default=None)
        parser.add_argument("--log-file", default=None)
        parser.add_argument("--init", action="store_true",
                            help="clear schedules + re-seed maintenance clocks first")
        parser.add_argument("--skip-callbacks", action="store_true")

    def handle(self, *args, **o):
        start = o["start"]
        end = o["end"]
        status_file = o.get("status_file")
        log_file = o.get("log_file")

        maint_groups = [g for g in SupervisorGroup.objects.all().order_by("name")
                        if _group_type(g) in ("maintenance", "mixed")]
        total = len(maint_groups) + (0 if o.get("skip_callbacks") else 1)

        def write_status(state, current=None, done=0, error=None):
            if not status_file:
                return
            try:
                with open(status_file, "w", encoding="utf-8") as fh:
                    json.dump({
                        "group": current or "All HQs",
                        "start": start, "end": end,
                        "state": state, "error": error,
                        "current_group": current,
                        "groups_done": done, "groups_total": total,
                    }, fh)
            except Exception:
                pass

        def log(msg):
            if log_file:
                try:
                    with open(log_file, "a", encoding="utf-8") as fh:
                        fh.write(msg + "\n")
                except Exception:
                    pass
            self.stdout.write(msg)

        def run_capturing(*cmd_args, **cmd_kwargs):
            """Run a management command, capturing its stdout into the log file
            so the web progress parser still sees the per-day date lines."""
            if log_file:
                with open(log_file, "a", encoding="utf-8") as lf, \
                        contextlib.redirect_stdout(lf):
                    call_command(*cmd_args, **cmd_kwargs)
            else:
                call_command(*cmd_args, **cmd_kwargs)

        write_status("RUNNING", current="(starting)")
        try:
            if o.get("init"):
                log("=== Clean slate: clearing schedules, tasks, runs, leave "
                    "+ re-seeding clocks ===")
                # Batched deletes (SQLite ~999-variable cap). Schedule first
                # because it FKs the others. Clearing Task fixes the active-task
                # backlog that was choking solve_group.
                _bulk_delete(Schedule)
                _bulk_delete(Task)
                _bulk_delete(OptimizationRun)
                _bulk_delete(LeaveRequest)   # no leave for now (re-seed later)
                run_capturing("run_maintenance_cycle", init=True)

            done = 0
            for g in maint_groups:
                write_status("RUNNING", current=g.name, done=done)
                log(f"\n=== Maintenance: {g.name} "
                    f"({done + 1}/{len(maint_groups)}) ===")
                run_capturing("solve_month", g.name, start=start, end=end)
                done += 1

            if not o.get("skip_callbacks"):
                write_status("RUNNING", current="Callbacks (all regions)", done=done)
                log("\n=== Callbacks: solve_callbacks ===")
                # NOTE: verify these kwargs match your solve_callbacks arguments
                # (built earlier as --start/--end/--clear). Adjust if renamed.
                run_capturing("solve_callbacks", start=start, end=end, clear=True)
                done += 1

            write_status("DONE", current="(complete)", done=done)
            log(f"\n=== DONE: {done} jobs over {start} .. {end} ===")

        except Exception as exc:
            write_status("FAILED", error=str(exc))
            log(f"\n!!! FAILED: {exc}")
            raise
