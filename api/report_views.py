"""
api/report_views.py
=============================================================================
Monthly maintenance reports for the LOGGED-IN supervisor's group.

  GET /api/reports/months/
  GET /api/reports/monthly/?year=2026&month=6
        &sort=name|hours|buildings|days  &order=asc|desc  &search=<technician>
  GET /api/reports/monthly/export/?year=2026&month=6   (honours sort & search)

Sorting/searching is server-side and backward-compatible: with no params the
output is identical to before (technicians sorted by name).
Scoped to request.user.supervised_group. Read-only.
=============================================================================
"""
from collections import defaultdict
from datetime import date

from django.db.models import Min, Max
from django.http import HttpResponse
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
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return get_active_date()


def _supervised_group(request):
    return getattr(request.user, "supervised_group", None)


def _group_schedules(group, year=None, month=None, as_of=None):
    qs = (Schedule.objects
          .filter(technician__group=group,
                  task__task_type__operation_type=OperationType.MAINTENANCE,
                  start_time__isnull=False)
          .select_related("technician", "task", "task__unit", "task__task_type"))
    if year and month:
        qs = qs.filter(start_time__year=year, start_time__month=month)
    if as_of is not None:
        qs = qs.filter(start_time__date__lte=as_of)
    return qs.order_by("technician__full_name", "start_time", "sequence_order")


def _minutes(s):
    if s.start_time and s.end_time:
        return max(0, int((s.end_time - s.start_time).total_seconds() // 60))
    return 0


def _build_report(group, year, month, as_of=None):
    scheds = list(_group_schedules(group, year, month, as_of))

    per_tech = defaultdict(lambda: defaultdict(list))
    tech_name = {}
    for s in scheds:
        t = s.technician
        tech_name[t.id] = t.full_name
        day = s.start_time.date().isoformat()
        per_tech[t.id][day].append({
            "building": s.task.unit.unit_name,
            "unit_code": s.task.unit.unit_code,
            "maintenance_type": (s.task.task_type.maintenance_type
                                 if s.task.task_type else None),
            "start": s.start_time.strftime("%H:%M"),
            "end": s.end_time.strftime("%H:%M") if s.end_time else None,
            "minutes": _minutes(s),
            "travel_min": s.travel_time_min or 0,
        })

    technicians = []
    for tid, days in per_tech.items():
        total_min = 0
        total_visits = 0
        day_list = []
        for day in sorted(days.keys()):
            visits = days[day]
            day_min = sum(v["minutes"] for v in visits)
            total_min += day_min
            total_visits += len(visits)
            window = f'{visits[0]["start"]}–{visits[-1]["end"] or visits[-1]["start"]}'
            day_list.append({
                "date": day,
                "visits": visits,
                "buildings": len(visits),
                "work_minutes": day_min,
                "window": window,
            })
        technicians.append({
            "id": tid,
            "name": tech_name[tid],
            "days_worked": len(days),
            "buildings_visited": total_visits,
            "total_hours": round(total_min / 60, 1),
            "days": day_list,
        })

    technicians.sort(key=lambda x: x["name"])
    return technicians


# ---- server-side sort + search ---------------------------------------------
# maps the ?sort= value to the technician dict key it orders by
_SORT_KEYS = {
    "name": lambda t: t["name"].lower(),
    "hours": lambda t: t["total_hours"],
    "building": lambda t: t["buildings_visited"],   # accept singular...
    "buildings": lambda t: t["buildings_visited"],  # ...and plural
    "days": lambda t: t["days_worked"],
}


def _sort_search(technicians, request):
    """Filter by ?search=<technician name>, then order by ?sort= & ?order=.
    Defaults: sort=name, order=asc for name / desc for the numeric columns
    (so 'highest hours/days/buildings' is the natural default)."""
    search = (request.query_params.get("search") or "").strip().lower()
    if search:
        technicians = [t for t in technicians if search in t["name"].lower()]

    sort = (request.query_params.get("sort") or "name").lower()
    keyfn = _SORT_KEYS.get(sort, _SORT_KEYS["name"])
    default_order = "asc" if sort == "name" else "desc"
    order = (request.query_params.get("order") or default_order).lower()
    technicians = sorted(technicians, key=keyfn, reverse=(order == "desc"))
    return technicians


class ReportMonthsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        group = _supervised_group(request)
        if group is None:
            return Response({"error": "Not a supervisor of any group."}, status=403)

        rng = (_group_schedules(group, as_of=_as_of(request))
               .aggregate(lo=Min("start_time"), hi=Max("start_time")))
        months = []
        if rng["lo"] and rng["hi"]:
            y, m = rng["lo"].year, rng["lo"].month
            end_y, end_m = rng["hi"].year, rng["hi"].month
            while (y, m) <= (end_y, end_m):
                months.append({"year": y, "month": m,
                               "label": date(y, m, 1).strftime("%B %Y")})
                m += 1
                if m > 12:
                    m = 1
                    y += 1
        return Response({"months": months})


class MonthlyReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        group = _supervised_group(request)
        if group is None:
            return Response({"error": "Not a supervisor of any group."}, status=403)
        try:
            year = int(request.query_params.get("year"))
            month = int(request.query_params.get("month"))
        except (TypeError, ValueError):
            return Response({"error": "year and month required."}, status=400)

        technicians = _build_report(group, year, month, _as_of(request))
        technicians = _sort_search(technicians, request)
        return Response({
            "group": group.name,
            "year": year,
            "month": month,
            "label": date(year, month, 1).strftime("%B %Y"),
            "sort": (request.query_params.get("sort") or "name").lower(),
            "order": (request.query_params.get("order") or "").lower() or None,
            "search": (request.query_params.get("search") or "").strip() or None,
            "technician_count": len(technicians),
            "technicians": technicians,
        })


class MonthlyReportExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        group = _supervised_group(request)
        if group is None:
            return Response({"error": "Not a supervisor of any group."}, status=403)
        try:
            year = int(request.query_params.get("year"))
            month = int(request.query_params.get("month"))
        except (TypeError, ValueError):
            return Response({"error": "year and month required."}, status=400)

        technicians = _build_report(group, year, month, _as_of(request))
        technicians = _sort_search(technicians, request)   # export honours sort/search
        label = date(year, month, 1).strftime("%B_%Y")

        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill
        except ImportError:
            return Response(
                {"error": "openpyxl not installed. Run: pip install openpyxl"},
                status=500)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Summary"
        head_fill = PatternFill("solid", fgColor="1F4E78")
        head_font = Font(bold=True, color="FFFFFF")
        headers = ["Technician", "Days Worked", "Buildings Visited", "Total Hours"]
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.fill = head_fill
            cell.font = head_font
        for r, t in enumerate(technicians, 2):
            ws.cell(row=r, column=1, value=t["name"])
            ws.cell(row=r, column=2, value=t["days_worked"])
            ws.cell(row=r, column=3, value=t["buildings_visited"])
            ws.cell(row=r, column=4, value=t["total_hours"])
        for col, w in zip("ABCD", [28, 14, 18, 14]):
            ws.column_dimensions[col].width = w

        ws2 = wb.create_sheet("Detail")
        dheaders = ["Technician", "Date", "Start", "End", "Building",
                    "Type", "Minutes", "Travel (min)"]
        for col, h in enumerate(dheaders, 1):
            cell = ws2.cell(row=1, column=col, value=h)
            cell.fill = head_fill
            cell.font = head_font
        row = 2
        for t in technicians:
            for day in t["days"]:
                for v in day["visits"]:
                    ws2.cell(row=row, column=1, value=t["name"])
                    ws2.cell(row=row, column=2, value=day["date"])
                    ws2.cell(row=row, column=3, value=v["start"])
                    ws2.cell(row=row, column=4, value=v["end"])
                    ws2.cell(row=row, column=5, value=v["building"])
                    ws2.cell(row=row, column=6, value=v["maintenance_type"])
                    ws2.cell(row=row, column=7, value=v["minutes"])
                    ws2.cell(row=row, column=8, value=v["travel_min"])
                    row += 1
        for col, w in zip("ABCDEFGH", [24, 12, 8, 8, 32, 8, 10, 12]):
            ws2.column_dimensions[col].width = w

        resp = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = (
            f'attachment; filename="{group.code}_report_{label}.xlsx"')
        wb.save(resp)
        return resp
