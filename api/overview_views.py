"""
api/overview_views.py
=============================================================================
Four supervisor-facing views, each scoped to request.user.supervised_group.
All now support server-side sorting (?sort= & ?order=), backward-compatible:
with no sort param each view keeps its original default ordering.

  Maintenance Overview  GET /api/overview/maintenance/
      ?type=A|B|C  ?status=  ?search=  ?sort=date|unit|type|tech|status  ?order=
      default sort = date desc (newest first).
  Repair / Callback     GET /api/overview/callbacks/   (?priority= ?search= ?sort= ?order=)
  Monthly Log           GET /api/overview/monthly-log/?year=&month=  ?sort= ?order=
      default sort = date asc (chronological).
  Daily Report          GET /api/overview/daily-report/?date=  ?technician_id=
      ?sort=technician|stops  ?order=   (sorts the per-technician list)
=============================================================================
"""
from datetime import date as date_cls

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Schedule, OperationType
from api.active_day import get_active_date


def _as_of(request):
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


# ---- shared row sorter ------------------------------------------------------
_ROW_SORT_KEYS = {
    "date": lambda r: ((r["date"] or ""), (r["start"] or "")),
    "unit": lambda r: (r["unit_name"] or "").lower(),
    "type": lambda r: str(r["type"] or ""),
    "tech": lambda r: (r["technician"] or "").lower(),
    "technician": lambda r: (r["technician"] or "").lower(),
    "status": lambda r: str(r["status"] or ""),
}


def _sort_rows(rows, request, default_sort, default_order):
    sort = (request.query_params.get("sort") or default_sort).lower()
    keyfn = _ROW_SORT_KEYS.get(sort)
    if keyfn is None:
        return rows  # unknown sort -> leave the queryset's own order
    order = (request.query_params.get("order") or default_order).lower()
    return sorted(rows, key=keyfn, reverse=(order == "desc"))


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

        rows = _sort_rows(rows, request, default_sort="date", default_order="desc")
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

        rows = _sort_rows(rows, request, default_sort="date", default_order="desc")
        page_rows, total, page, size = _paginate(rows, request)
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
        search = (request.query_params.get("search") or "").strip().lower()
        if search:
            rows = [r for r in rows
                    if search in r["unit_name"].lower()
                    or search in r["unit_code"].lower()
                    or (r["technician"] and search in r["technician"].lower())]

        rows = _sort_rows(rows, request, default_sort="date", default_order="asc")
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

        ceiling = _as_of(request)
        day_str = request.query_params.get("date")
        if day_str:
            try:
                day = date_cls.fromisoformat(day_str)
            except ValueError:
                return Response({"error": "date must be YYYY-MM-DD."}, status=400)
        else:
            day = ceiling if ceiling is not None else date_cls.today()
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

        faults = []
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
                 for name, stops in by_tech.items()]

        # sort the per-technician list: ?sort=technician|stops  ?order=
        sort = (request.query_params.get("sort") or "technician").lower()
        if sort == "stops":
            order = (request.query_params.get("order") or "desc").lower()
            techs.sort(key=lambda x: x["stops"], reverse=(order == "desc"))
        else:
            order = (request.query_params.get("order") or "asc").lower()
            techs.sort(key=lambda x: x["technician"].lower(), reverse=(order == "desc"))

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
