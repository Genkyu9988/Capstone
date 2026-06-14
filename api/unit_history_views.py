"""
api/unit_history_views.py
=============================================================================
Per-unit service history for the LOGGED-IN supervisor, scoped to their group
and adapting to the group's type:

    maintenance-only supervisor -> shows A/B/C maintenance history only
    callback-only supervisor    -> shows callback history only
    mixed supervisor            -> shows both

  GET /api/units/history/
      -> summary table: each unit in the supervisor's scope with counts
         (maintenance visits, callbacks) and last-service date. Paginated.
         ?search=<text>  filters by unit name/code
         ?page=<n>&page_size=<n>

  GET /api/units/<unit_id>/history/
      -> full chronological history for one unit (every maintenance + callback
         visit: date, type, technician, times, duration).

  GET /api/units/history/export/
      -> the whole scope as an .xlsx (one row per visit).

"Scope" = units that have at least one task assigned to this supervisor's group
(maintenance tasks for maintenance groups, CB- tasks for callback groups, both
for mixed). Attribution is by assigned_group, which for callbacks = the
responding technician's group.
=============================================================================
"""
from collections import defaultdict

from django.db.models import Q
from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Schedule, Task, Unit, OperationType
from api.active_day import get_active_date
from datetime import date as _date


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
            return _date.fromisoformat(raw)
        except ValueError:
            pass
    return get_active_date()


def _group(request):
    return getattr(request.user, "supervised_group", None)


def _scope_schedules(group, as_of=None):
    """All schedules whose task is assigned to this group (maint + callback),
    optionally clamped to an upper date bound (the operating-clock day)."""
    qs = (Schedule.objects
          .filter(task__assigned_group=group, start_time__isnull=False)
          .select_related("task", "task__unit", "task__task_type",
                          "technician"))
    if as_of is not None:
        qs = qs.filter(start_time__date__lte=as_of)
    return qs


def _op(s):
    tt = s.task.task_type
    return tt.operation_type if tt else None


def _visit(s):
    tt = s.task.task_type
    is_cb = _op(s) == OperationType.CALLBACK
    return {
        "date": s.start_time.date().isoformat(),
        "kind": "Callback" if is_cb else "Maintenance",
        "type": (s.task.priority if is_cb
                 else (tt.maintenance_type if tt else None)),
        "technician": s.technician.full_name if s.technician else None,
        "start": s.start_time.strftime("%H:%M") if s.start_time else None,
        "end": s.end_time.strftime("%H:%M") if s.end_time else None,
        "duration_min": s.task.estimated_duration_min,
        "task_no": s.task.task_no,
    }


class UnitHistorySummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        group = _group(request)
        if group is None:
            return Response({"error": "Not a supervisor of any group."}, status=403)

        search = (request.query_params.get("search") or "").strip()
        try:
            page = max(1, int(request.query_params.get("page", 1)))
            page_size = min(200, max(10, int(request.query_params.get("page_size", 50))))
        except ValueError:
            page, page_size = 1, 50

        scheds = _scope_schedules(group, _as_of(request))

        # aggregate per unit
        per_unit = defaultdict(lambda: {"maint": 0, "callback": 0, "last": None,
                                        "name": "", "code": "", "type": ""})
        for s in scheds:
            u = s.task.unit
            rec = per_unit[u.id]
            rec["name"] = u.unit_name
            rec["code"] = u.unit_code
            rec["type"] = u.unit_type
            if _op(s) == OperationType.CALLBACK:
                rec["callback"] += 1
            else:
                rec["maint"] += 1
            d = s.start_time.date().isoformat()
            if rec["last"] is None or d > rec["last"]:
                rec["last"] = d

        units = [{"id": uid, **rec} for uid, rec in per_unit.items()]
        if search:
            sl = search.lower()
            units = [u for u in units
                     if sl in u["name"].lower() or sl in u["code"].lower()]
        units.sort(key=lambda u: u["name"])

        total = len(units)
        start = (page - 1) * page_size
        page_units = units[start:start + page_size]

        # group type label
        has_m = any(u["maint"] for u in units)
        has_c = any(u["callback"] for u in units)
        gtype = ("mixed" if has_m and has_c
                 else "callback" if has_c else "maintenance")

        return Response({
            "group": group.name,
            "group_type": gtype,
            "total_units": total,
            "page": page,
            "page_size": page_size,
            "units": page_units,
        })


class UnitHistoryDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, unit_id):
        group = _group(request)
        if group is None:
            return Response({"error": "Not a supervisor of any group."}, status=403)

        unit = Unit.objects.filter(id=unit_id).first()
        if unit is None:
            return Response({"error": "Unit not found."}, status=404)

        scheds = _scope_schedules(group, _as_of(request)).filter(task__unit=unit).order_by("start_time")
        visits = [_visit(s) for s in scheds]

        return Response({
            "unit": {
                "id": unit.id,
                "name": unit.unit_name,
                "code": unit.unit_code,
                "type": unit.unit_type,
                "address": unit.address,
            },
            "visit_count": len(visits),
            "visits": visits,
        })


class UnitHistoryExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        group = _group(request)
        if group is None:
            return Response({"error": "Not a supervisor of any group."}, status=403)

        scheds = _scope_schedules(group, _as_of(request)).order_by(
            "task__unit__unit_name", "start_time")

        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill
        except ImportError:
            return Response({"error": "openpyxl not installed."}, status=500)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Unit History"
        head_fill = PatternFill("solid", fgColor="1F4E78")
        head_font = Font(bold=True, color="FFFFFF")
        headers = ["Unit", "Unit Code", "Unit Type", "Date", "Kind", "Type",
                   "Technician", "Start", "End", "Duration (min)"]
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.fill = head_fill
            cell.font = head_font

        row = 2
        for s in scheds:
            u = s.task.unit
            v = _visit(s)
            ws.cell(row=row, column=1, value=u.unit_name)
            ws.cell(row=row, column=2, value=u.unit_code)
            ws.cell(row=row, column=3, value=u.unit_type)
            ws.cell(row=row, column=4, value=v["date"])
            ws.cell(row=row, column=5, value=v["kind"])
            ws.cell(row=row, column=6, value=str(v["type"]))
            ws.cell(row=row, column=7, value=v["technician"])
            ws.cell(row=row, column=8, value=v["start"])
            ws.cell(row=row, column=9, value=v["end"])
            ws.cell(row=row, column=10, value=v["duration_min"])
            row += 1

        for col, w in zip("ABCDEFGHIJ", [30, 14, 12, 12, 12, 8, 24, 8, 8, 14]):
            ws.column_dimensions[col].width = w

        resp = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = (
            f'attachment; filename="{group.code}_unit_history.xlsx"')
        wb.save(resp)
        return resp
