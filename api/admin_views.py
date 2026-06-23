"""
api/admin_views.py
=============================================================================
Admin-only backend. The admin dashboard is a watered-down, read-only spectator
over EVERY supervisor HQ, plus two global controls:

  GET    /api/admin/hqs/            -> all 10 HQs with a summary (type, techs,
                                       how many are working today)
  GET    /api/admin/hq-state/?group_id=<id>
                                    -> read-only live state of ONE HQ: each
                                       technician, their estimated position,
                                       stop count, and the units they're on
  POST   /api/admin/generate/       { "start":"YYYY-MM-DD","end":"YYYY-MM-DD",
                                       "init": true }
                                    -> spawn run_simulation_all (ALL 10 HQs)
  GET    /api/admin/generate/       -> progress (current_group, groups_done/total)
  DELETE /api/admin/generate/       -> cancel the running global generate

Auth: IsAdmin (is_staff OR is_superuser). Create the account once with
`python manage.py createsuperuser`. The admin dashboard logs in via the same
/api/login/ token flow; these endpoints simply reject non-staff tokens.

The observe endpoints reuse the live map's FREE straight-line position helpers
(no Google calls), so opening any number of HQs costs zero API quota.
=============================================================================
"""
import os
import re
import sys
import json
import signal
import subprocess
from datetime import date

from django.conf import settings
from rest_framework.views import APIView
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework import status as http

from api.models import (Technician, SupervisorGroup, TechnicianRole,
                        Schedule, Unit, Task, LeaveRequest)
from api.active_day import get_active_date, get_active_datetime


class IsAdmin(BasePermission):
    message = "Admin access only."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.is_staff or u.is_superuser))


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


def _has_approved_leave(technician, day) -> bool:
    return LeaveRequest.objects.filter(
        technician=technician,
        status=LeaveRequest.LeaveStatus.APPROVED,
        start_date__lte=day,
        end_date__gte=day,
    ).exists()


# =====================================================================
#  OBSERVE: list every HQ
# =====================================================================
class AdminHQListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        active_day = get_active_date(request)
        hqs = []
        for g in SupervisorGroup.objects.all().order_by("name"):
            tech_count = Technician.objects.filter(
                group=g, is_active_employee=True).count()
            active_today = (Schedule.objects
                            .filter(technician__group=g,
                                    start_time__date=active_day)
                            .values("technician").distinct().count())
            hqs.append({
                "id": g.id,
                "name": g.name,
                "type": _group_type(g),
                "tech_count": tech_count,
                "active_today": active_today,
            })
        active_now = get_active_datetime(request)
        return Response({
            "hq_count": len(hqs),
            "active_date": active_day.isoformat(),
            "active_time": active_now.isoformat() if active_now else None,
            "hqs": hqs,
        })


# =====================================================================
#  OBSERVE: one HQ's read-only state
# =====================================================================
class AdminHQStateView(APIView):
    """Read-only snapshot of ONE supervisor: their technicians (with today's
    status off the roll-date clock) and the units they cover. No map / routes."""
    permission_classes = [IsAdmin]

    def get(self, request):
        try:
            gid = int(request.query_params.get("group_id"))
        except (TypeError, ValueError):
            return Response({"error": "group_id required."}, status=400)

        target = SupervisorGroup.objects.filter(id=gid).first()
        if target is None:
            return Response({"error": "Group not found."}, status=404)

        active_day = get_active_date(request)

        techs = (Technician.objects
                 .filter(is_active_employee=True, group=target)
                 .select_related("user")
                 .order_by("full_name"))
        result = []
        working = 0
        for t in techs:
            stops_today = (Schedule.objects
                           .filter(technician=t, start_time__date=active_day)
                           .count())
            on_leave = (not t.is_available) or _has_approved_leave(t, active_day)
            if on_leave:
                status_label = "onLeave"
            elif stops_today:
                status_label = "working"
                working += 1
            else:
                status_label = "available"
            result.append({
                "id": t.id,
                "name": t.full_name,
                "tech_role": t.tech_role,
                "specialty": getattr(t, "specialty", None),
                "on_leave": on_leave,
                "stops_today": stops_today,
                "status": status_label,
            })

        # Units this supervisor covers = the distinct units it holds tasks for
        # (after a generate this spans the whole zone), with an elevator/escalator
        # split so the admin can see the coverage mix.
        unit_ids = list(Task.objects.filter(assigned_group=target)
                        .values_list("unit_id", flat=True).distinct())
        covered = Unit.objects.filter(id__in=unit_ids)
        total = covered.count()
        ele = covered.filter(unit_type="ELEVATOR").count()
        esc = covered.filter(unit_type="ESCALATOR").count()

        return Response({
            "group": target.name,
            "group_type": _group_type(target),
            "active_date": active_day.isoformat(),
            "tech_count": len(result),
            "working_today": working,
            "technicians": result,
            "units_covered": {"total": total, "elevator": ele, "escalator": esc},
        })


# =====================================================================
#  GLOBAL GENERATE (all 10 HQs in one job, via run_simulation_all)
# =====================================================================
ADMIN_JOB_DIR = os.path.join(str(settings.BASE_DIR), ".admin_jobs")
A_STATUS = os.path.join(ADMIN_JOB_DIR, "status.json")
A_LOG = os.path.join(ADMIN_JOB_DIR, "run.log")
A_PID = os.path.join(ADMIN_JOB_DIR, "run.pid")
MAX_SPAN_DAYS = 186


def _read_json(p):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _read_pid():
    try:
        with open(A_PID, encoding="utf-8") as fh:
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


def _clear():
    for p in (A_STATUS, A_PID):
        try:
            os.remove(p)
        except Exception:
            pass


class AdminGenerateView(APIView):
    permission_classes = [IsAdmin]

    # ---------------------------------------------------------- start
    def post(self, request):
        start_raw = request.data.get("start")
        end_raw = request.data.get("end")
        try:
            start = date.fromisoformat(str(start_raw))
            end = date.fromisoformat(str(end_raw))
        except (TypeError, ValueError):
            return Response({"error": "start/end must be YYYY-MM-DD."},
                            status=http.HTTP_400_BAD_REQUEST)
        if end < start:
            return Response({"error": "end is before start."},
                            status=http.HTTP_400_BAD_REQUEST)
        if (end - start).days > MAX_SPAN_DAYS:
            return Response({"error": f"range too long (max {MAX_SPAN_DAYS} days)."},
                            status=http.HTTP_400_BAD_REQUEST)
        init = bool(request.data.get("init", True))

        st = _read_json(A_STATUS)
        if st and st.get("state") == "RUNNING" and _pid_alive(_read_pid()):
            return Response({"error": "A global generate is already running.",
                             "status": st}, status=http.HTTP_409_CONFLICT)

        os.makedirs(ADMIN_JOB_DIR, exist_ok=True)
        _clear()
        with open(A_STATUS, "w", encoding="utf-8") as fh:
            json.dump({"state": "RUNNING", "start": start.isoformat(),
                       "end": end.isoformat(), "group": "(starting)",
                       "error": None}, fh)
        open(A_LOG, "w", encoding="utf-8").close()

        manage_py = os.path.join(str(settings.BASE_DIR), "manage.py")
        cmd = [sys.executable, manage_py, "run_simulation_all",
               "--start", start.isoformat(), "--end", end.isoformat(),
               "--status-file", A_STATUS, "--log-file", A_LOG]
        if init:
            cmd.append("--init")

        kwargs = {"cwd": str(settings.BASE_DIR)}
        if os.name == "nt":
            detached = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            newgrp = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            kwargs["creationflags"] = detached | newgrp
        else:
            kwargs["start_new_session"] = True

        proc = subprocess.Popen(cmd, **kwargs)
        try:
            with open(A_PID, "w", encoding="utf-8") as fh:
                fh.write(str(proc.pid))
        except Exception:
            pass

        return Response({"state": "started", "start": start.isoformat(),
                         "end": end.isoformat(), "init": init},
                        status=http.HTTP_202_ACCEPTED)

    # ---------------------------------------------------------- cancel
    def delete(self, request):
        _kill(_read_pid())
        _clear()
        return Response({"state": "idle", "cancelled": True})

    # ---------------------------------------------------------- status
    def get(self, request):
        st = _read_json(A_STATUS)
        if not st:
            return Response({"state": "idle"})

        state = st.get("state")
        error = st.get("error")
        if state == "RUNNING" and not _pid_alive(_read_pid()):
            state = "FAILED"
            error = "The generate stopped before finishing. Start a new one."

        lines = []
        try:
            with open(A_LOG, encoding="utf-8", errors="replace") as fh:
                lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
        except Exception:
            pass

        done = st.get("groups_done")
        total = st.get("groups_total")
        progress = None
        if isinstance(done, int) and isinstance(total, int) and total:
            progress = min(max(done / total, 0.0), 1.0)
        if state == "DONE":
            progress = 1.0

        return Response({
            "state": state,
            "current_group": st.get("current_group") or st.get("group"),
            "groups_done": done,
            "groups_total": total,
            "start": st.get("start"),
            "end": st.get("end"),
            "error": error,
            "progress": progress,
            "log_tail": lines[-18:],
        })

