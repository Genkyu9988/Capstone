"""
api/simulation_run_views.py
=============================================================================
Web "Generate Schedule" control (maintenance, one supervisor group).

    POST   /api/simulation/run/   { "start": "2026-06-18", "end": "2026-07-22" }
           (or legacy { "months": 3 }) -> spawn solve_month over the range (202)
    GET    /api/simulation/run/   -> { state, group, start, end, progress, ... }
    DELETE /api/simulation/run/   -> cancel the running job and reset to idle

Self-healing: the spawned PID is recorded. If the status says RUNNING but that
process is no longer alive (killed / crashed / server restart), it's reported as
a stale FAILED instead of a frozen "RUNNING", and a new run is allowed to start.
=============================================================================
"""
import os
import re
import sys
import json
import signal
import calendar
import subprocess
from datetime import date

from django.conf import settings
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status as http

from .models import SupervisorGroup

JOB_DIR = os.path.join(str(settings.BASE_DIR), ".sim_jobs")
STATUS_FILE = os.path.join(JOB_DIR, "status.json")
LOG_FILE = os.path.join(JOB_DIR, "run.log")
PID_FILE = os.path.join(JOB_DIR, "run.pid")
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

MAX_SPAN_DAYS = 186  # ~6 months; guards against a runaway solve


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _read_pid():
    try:
        with open(PID_FILE, encoding="utf-8") as fh:
            return int(fh.read().strip())
    except Exception:
        return None


def _pid_alive(pid):
    if not pid:
        return False
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                 capture_output=True, text=True, timeout=5)
            return str(pid) in (out.stdout or "")
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _kill(pid):
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=5)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


def _is_really_running():
    """RUNNING in the status file AND the process is still alive."""
    st = _read_json(STATUS_FILE)
    return bool(st and st.get("state") == "RUNNING" and _pid_alive(_read_pid()))


def _add_months(d, n):
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def _clear_files():
    for p in (STATUS_FILE, PID_FILE):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
        except Exception:
            pass


class SimulationRunView(APIView):
    permission_classes = [AllowAny]

    # ---------------------------------------------------------------- start
    def post(self, request):
        start, end, err = self._resolve_range(request)
        if err:
            return Response({"error": err}, status=http.HTTP_400_BAD_REQUEST)

        group = self._resolve_group(request)
        if group is None:
            return Response(
                {"error": "Could not determine the group. Send 'group_id', or sign "
                          "in as a supervisor."},
                status=http.HTTP_400_BAD_REQUEST)

        # only block if a job is *genuinely* still running (not a stale marker)
        if _is_really_running():
            return Response({"error": "A schedule is already being generated.",
                             "status": _read_json(STATUS_FILE)},
                            status=http.HTTP_409_CONFLICT)

        os.makedirs(JOB_DIR, exist_ok=True)
        _clear_files()  # clear any stale marker so we start clean
        with open(STATUS_FILE, "w", encoding="utf-8") as fh:
            json.dump({"group": group.name, "start": start.isoformat(),
                       "end": end.isoformat(), "state": "RUNNING", "error": None}, fh)
        open(LOG_FILE, "w", encoding="utf-8").close()

        manage_py = os.path.join(str(settings.BASE_DIR), "manage.py")
        cmd = [sys.executable, manage_py, "run_simulation_job", group.name,
               "--start", start.isoformat(), "--end", end.isoformat(),
               "--status-file", STATUS_FILE, "--log-file", LOG_FILE]

        kwargs = {"cwd": str(settings.BASE_DIR)}
        if os.name == "nt":
            detached = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            newgrp = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            kwargs["creationflags"] = detached | newgrp
        else:
            kwargs["start_new_session"] = True

        proc = subprocess.Popen(cmd, **kwargs)
        try:
            with open(PID_FILE, "w", encoding="utf-8") as fh:
                fh.write(str(proc.pid))
        except Exception:
            pass

        return Response({"state": "started", "group": group.name,
                         "start": start.isoformat(), "end": end.isoformat(),
                         "days": (end - start).days + 1},
                        status=http.HTTP_202_ACCEPTED)

    # --------------------------------------------------------------- cancel
    def delete(self, request):
        _kill(_read_pid())
        _clear_files()
        return Response({"state": "idle", "cancelled": True}, status=http.HTTP_200_OK)

    # --------------------------------------------------------------- status
    def get(self, request):
        st = _read_json(STATUS_FILE)
        if not st:
            return Response({"state": "idle"}, status=http.HTTP_200_OK)

        state = st.get("state")
        error = st.get("error")
        # stale RUNNING (process gone) -> report as interrupted, not frozen
        if state == "RUNNING" and not _pid_alive(_read_pid()):
            state = "FAILED"
            error = "The previous generation stopped before finishing. Start a new one."

        lines = []
        try:
            with open(LOG_FILE, encoding="utf-8", errors="replace") as fh:
                lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
        except Exception:
            pass

        progress, latest = None, None
        try:
            s = date.fromisoformat(st["start"])
            e = date.fromisoformat(st["end"])
            span = max((e - s).days, 1)
            seen = [m for ln in lines for m in _DATE_RE.findall(ln)]
            if seen:
                latest = max(seen)
                progress = min(max((date.fromisoformat(latest) - s).days / span, 0.0), 1.0)
        except Exception:
            pass
        if state == "DONE":
            progress = 1.0

        return Response({
            "state": state,
            "group": st.get("group"),
            "start": st.get("start"),
            "end": st.get("end"),
            "total_working_days": st.get("total_working_days"),
            "error": error,
            "progress": progress,
            "latest_day": latest,
            "log_tail": lines[-15:],
        }, status=http.HTTP_200_OK)

    # ------------------------------------------------------------------ helpers
    def _resolve_range(self, request):
        start_raw = request.data.get("start")
        end_raw = request.data.get("end")
        if start_raw and end_raw:
            try:
                start = date.fromisoformat(str(start_raw))
                end = date.fromisoformat(str(end_raw))
            except ValueError:
                return None, None, "start/end must be YYYY-MM-DD."
            if end < start:
                return None, None, "end is before start."
            if (end - start).days > MAX_SPAN_DAYS:
                return None, None, f"range too long (max {MAX_SPAN_DAYS} days)."
            return start, end, None

        months = request.data.get("months")
        if months is not None:
            try:
                months = int(months)
            except (TypeError, ValueError):
                return None, None, "months must be an integer."
            if not (1 <= months <= 6):
                return None, None, "months must be between 1 and 6."
            start = date.today()
            return start, _add_months(start, months), None

        return None, None, "Provide a start and end date (YYYY-MM-DD)."

    def _resolve_group(self, request):
        gid = request.data.get("group_id")
        if gid:
            g = SupervisorGroup.objects.filter(id=gid).first()
            if g:
                return g
        name = request.data.get("group")
        if name:
            g = SupervisorGroup.objects.filter(name=name).first()
            if g:
                return g
        user = request.user if (request.user and request.user.is_authenticated) else None
        if user is not None:
            return getattr(user, "supervised_group", None)
        return None
