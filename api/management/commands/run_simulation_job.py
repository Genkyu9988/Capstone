"""
api/management/commands/run_simulation_job.py
=============================================================================
Internal background wrapper around `solve_month` for the web "Run Simulation"
button. It records a tiny JSON status file and a log file so the dashboard can
poll progress WITHOUT querying the database (which would otherwise contend with
solve_month's SQLite writes during the run).

Spawned as a detached subprocess by SimulationRunView. It can also be run by
hand, but normally you just click the button.

    python manage.py run_simulation_job "Ahmet Yılmaz Group" \
        --start 2026-07-01 --end 2026-10-01 \
        --status-file .sim_jobs/status.json --log-file .sim_jobs/run.log
=============================================================================
"""
import json
import traceback
from datetime import date, timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand


def _write_status(path, data):
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except Exception:
        pass


def _working_days(start, end):
    n, d = 0, start
    while d <= end:
        if d.weekday() < 5:          # Mon-Fri
            n += 1
        d += timedelta(days=1)
    return n


class Command(BaseCommand):
    help = "Internal: run solve_month and record status/log for the web UI."

    def add_arguments(self, parser):
        parser.add_argument("group_name", type=str)
        parser.add_argument("--start", required=True)
        parser.add_argument("--end", required=True)
        parser.add_argument("--status-file", required=True)
        parser.add_argument("--log-file", required=True)

    def handle(self, *args, **o):
        status_path = o["status_file"]
        log_path = o["log_file"]
        group = o["group_name"]
        start = o["start"]
        end = o["end"]

        try:
            twd = _working_days(date.fromisoformat(start), date.fromisoformat(end))
        except Exception:
            twd = None

        base = {"group": group, "start": start, "end": end, "total_working_days": twd}
        _write_status(status_path, {**base, "state": "RUNNING", "error": None})

        log = open(log_path, "w", encoding="utf-8")
        try:
            # solve_month writes via self.stdout -> goes into our log file
            call_command("solve_month", group, start=start, end=end, stdout=log)
            log.flush()
            _write_status(status_path, {**base, "state": "DONE", "error": None})
        except Exception as exc:
            log.write("\n[run_simulation_job] FAILED:\n")
            log.write(traceback.format_exc())
            log.flush()
            _write_status(status_path, {**base, "state": "FAILED", "error": str(exc)[:1000]})
        finally:
            log.close()
