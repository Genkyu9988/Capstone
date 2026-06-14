"""
api/overview_views.py
=============================================================================
Four supervisor-facing views, each scoped to request.user.supervised_group:

  Maintenance Overview      GET /api/overview/maintenance/
      All maintenance tasks (A/B/C) for the group. Filter by ?type=A|B|C,
      ?status=, ?search=, paginated. Shows unit, type, tech, date, status.

  Repair / Callback Module  GET /api/overview/callbacks/
      All callback tasks for the group. Filter by ?priority=AA|A|B|C|D,
      ?search=, paginated. Shows unit, priority, responding tech, date.

  Monthly Tracking & Logs   GET /api/overview/monthly-log/?year=&month=
      Every task (maintenance + callback) in a month as a chronological log:
      who went where at what time. Paginated.

  Supervisor Reporting      GET /api/overview/daily-report/?date=YYYY-MM-DD
                            GET /api/overview/daily-report/?technician_id=<id>&date=
      Today's (or a date's) faults/breakdowns + locations a technician visited.
=============================================================================
"""
from datetime import date as date_cls

from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Schedule, Task, Technician, OperationType
from api.active_day import get_active_date


def _as_of(request):
    """Upper date bound the frontend is allowed to see. Defaults to the
    operating-clock day; the console can widen it with ?as_of=YYYY-MM-DD, or
    remove the cap entirely with ?as_of=all."""
    raw = (request.query_params.get("as_of")
           if hasattr(request, "query_params") else None)
    if raw:
        if raw.lower() == "all":
            return None
        try:
            return date_cls.fromisoformat(raw)
        except ValueError:
            pass
    return get_active_date()


def _group(request):
    return getattr(request.user, "supervised_group", None)


def _paginate(items, request, default=50):
    try:
        page = max(1, int(request.query_params.get("page", 1)))
        size = min(200, max(10, int(request.query_params.get("page_size", default))))
    except ValueError:
        page, size = 1, default
    total = len(items)
    start = (page - 1) * size
    return items[start:start + size], total, page, size


def _sched_row(s):
    tt = s.task.task_type
    is_cb = tt and tt.operation_type == OperationType.CALLBACK
    return {
        "task_no": s.task.task_no,
        "unit_name": s.task.unit.unit_name,
        "unit_code": s.task.unit.unit_code,
        "kind": "Callback" if is_cb else "Maintenance",
        "type": (s.task.priority if is_cb
                 else (tt.maintenance_type if tt else None)),
        "technician": s.technician.full_name if s.technician else None,
        "date": s.start_time.date().isoformat() if s.start_time else None,
        "start": s.start_time.strftime("%H:%M") if s.start_time else None,
        "end": s.end_time.strftime("%H:%M") if s.end_time else None,
        "status": s.task.status,
    }


# ===================================================== Maintenance Overview
class MaintenanceOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        group = _group(request)
        if group is None:
            return Response({"error": "Not a supervisor."}, status=403)

        qs = (Schedule.objects
              .filter(task__assigned_group=group,
                      task__task_type__operation_type=OperationType.MAINTENANCE,
                      start_time__isnull=False)
              .select_related("task", "task__unit", "task__task_type", "technician")
              .order_by("-start_time"))

        mtype = request.query_params.get("type")
        if mtype:
            qs = qs.filter(task__task_type__maintenance_type=mtype.upper())
        status_f = request.query_params.get("status")
        if status_f:
            qs = qs.filter(task__status=status_f.upper())

        as_of = _as_of(request)
        if as_of is not None:
            qs = qs.filter(start_time__date__lte=as_of)

        rows = [_sched_row(s) for s in qs]
        search = (request.query_params.get("search") or "").strip().lower()
        if search:
            rows = [r for r in rows
                    if search in r["unit_name"].lower()
                    or search in r["unit_code"].lower()
                    or (r["technician"] and search in r["technician"].lower())]

        page_rows, total, page, size = _paginate(rows, request)
        return Response({"group": group.name, "total": total, "page": page,
                         "page_size": size, "tasks": page_rows})


# ===================================================== Repair / Callback
class CallbackOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        group = _group(request)
        if group is None:
            return Response({"error": "Not a supervisor."}, status=403)

        qs = (Schedule.objects
              .filter(task__assigned_group=group,
                      task__task_type__operation_type=OperationType.CALLBACK,
                      start_time__isnull=False)
              .select_related("task", "task__unit", "task__task_type", "technician")
              .order_by("-start_time"))

        priority = request.query_params.get("priority")
        if priority:
            qs = qs.filter(task__priority=priority.upper())

        as_of = _as_of(request)
        if as_of is not None:
            qs = qs.filter(start_time__date__lte=as_of)

        rows = [_sched_row(s) for s in qs]
        search = (request.query_params.get("search") or "").strip().lower()
        if search:
            rows = [r for r in rows
                    if search in r["unit_name"].lower()
                    or search in r["unit_code"].lower()
                    or (r["technician"] and search in r["technician"].lower())]

        page_rows, total, page, size = _paginate(rows, request)
        # quick priority breakdown for the header
        breakdown = {}
        for r in rows:
            breakdown[r["type"]] = breakdown.get(r["type"], 0) + 1
        return Response({"group": group.name, "total": total, "page": page,
                         "page_size": size, "breakdown": breakdown,
                         "tasks": page_rows})


# ===================================================== Monthly Tracking & Logs
class MonthlyLogView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        group = _group(request)
        if group is None:
            return Response({"error": "Not a supervisor."}, status=403)
        try:
            year = int(request.query_params.get("year"))
            month = int(request.query_params.get("month"))
        except (TypeError, ValueError):
            return Response({"error": "year and month required."}, status=400)

        qs = (Schedule.objects
              .filter(task__assigned_group=group,
                      start_time__year=year, start_time__month=month,
                      start_time__isnull=False)
              .select_related("task", "task__unit", "task__task_type", "technician")
              .order_by("start_time", "sequence_order"))

        as_of = _as_of(request)
        if as_of is not None:
            qs = qs.filter(start_time__date__lte=as_of)

        rows = [_sched_row(s) for s in qs]
        page_rows, total, page, size = _paginate(rows, request, default=100)
        return Response({"group": group.name, "year": year, "month": month,
                         "total": total, "page": page, "page_size": size,
                         "log": page_rows})


# ===================================================== Supervisor Reporting
class DailyReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        group = _group(request)
        if group is None:
            return Response({"error": "Not a supervisor."}, status=403)

        ceiling = _as_of(request)   # operating-clock day (or console override)
        day_str = request.query_params.get("date")
        if day_str:
            try:
                day = date_cls.fromisoformat(day_str)
            except ValueError:
                return Response({"error": "date must be YYYY-MM-DD."}, status=400)
        else:
            # default to the operating day, NOT the real device date
            day = ceiling if ceiling is not None else date_cls.today()
        # never reveal a day past the operating clock
        if ceiling is not None and day > ceiling:
            day = ceiling

        base = (Schedule.objects
                .filter(task__assigned_group=group,
                        start_time__date=day, start_time__isnull=False)
                .select_related("task", "task__unit", "task__task_type", "technician"))

        tech_id = request.query_params.get("technician_id")
        if tech_id:
            base = base.filter(technician_id=tech_id)

        scheds = list(base.order_by("technician__full_name", "start_time"))

        # faults/breakdowns today = callbacks today
        faults = []
        # locations visited, grouped by technician
        by_tech = {}
        for s in scheds:
            row = _sched_row(s)
            if row["kind"] == "Callback":
                faults.append(row)
            t = row["technician"] or "Unassigned"
            by_tech.setdefault(t, []).append({
                "unit_name": row["unit_name"],
                "unit_code": row["unit_code"],
                "kind": row["kind"],
                "type": row["type"],
                "start": row["start"],
                "end": row["end"],
            })

        techs = [{"technician": name, "stops": len(stops), "locations": stops}
                 for name, stops in sorted(by_tech.items())]

        # determine group type from what this group actually does, so the
        # frontend can hide the faults section for maintenance-only HQs.
        has_m = Schedule.objects.filter(
            task__assigned_group=group,
            task__task_type__operation_type=OperationType.MAINTENANCE).exists()
        has_c = Schedule.objects.filter(
            task__assigned_group=group,
            task__task_type__operation_type=OperationType.CALLBACK).exists()
        gtype = ("mixed" if has_m and has_c
                 else "callback" if has_c else "maintenance")

        return Response({
            "group": group.name,
            "group_type": gtype,
            "date": day.isoformat(),
            "total_visits": len(scheds),
            "fault_count": len(faults),
            "faults": faults,
            "technicians": techs,
        })
