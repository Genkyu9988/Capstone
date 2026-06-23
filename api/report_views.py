"""
api/report_views.py
=============================================================================
Monthly reports for the LOGGED-IN supervisor's group.

This version is operation-aware:
  * maintenance supervisors see MAINTENANCE schedules
  * callback supervisors see CALLBACK schedules
  * ?operation=maintenance or ?operation=callback can override it

Normal tabs are clamped to the operating roll-date.
Full Schedule tabs pass ?as_of=all and show the full generated horizon.
=============================================================================
"""
from collections import defaultdict
from datetime import date

from django.db.models import Min, Max
from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Schedule, OperationType, TechnicianRole
from api.active_day import get_active_date


def _as_of(request):
    """Upper date bound the frontend is allowed to see. Defaults to the
    operating-clock day; ?as_of=all removes the cap for Full Schedule tabs."""
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


def _operation_for_group(request, group):
    """Choose report operation type.

    The existing Monthly Report UI calls the same endpoints for every supervisor.
    Maintenance groups should see maintenance rows; callback-only groups
    (Yusuf Arslan / Can Doğan) should see callback rows.
    """
    raw = (request.query_params.get("operation") or request.query_params.get("type") or "").strip().lower()
    if raw in {"callback", "callbacks", "cb", "breakdown", "repair"}:
        return OperationType.CALLBACK
    if raw in {"maintenance", "maint", "pm"}:
        return OperationType.MAINTENANCE

    roles = set(group.technicians.filter(is_active_employee=True).values_list("tech_role", flat=True))
    has_callback = TechnicianRole.CALLBACK in roles
    has_maintenance = TechnicianRole.MAINTENANCE in roles
    if has_callback and not has_maintenance:
        return OperationType.CALLBACK
    return OperationType.MAINTENANCE


def _group_schedules(group, year=None, month=None, as_of=None, operation_type=OperationType.MAINTENANCE):
    """Schedules for a group, optionally filtered to month and clamped to the
    operating roll-date. Operation type may be MAINTENANCE or CALLBACK."""
    qs = (Schedule.objects
          .filter(technician__group=group,
                  task__task_type__operation_type=operation_type,
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


def _visit_type(task, operation_type):
    if operation_type == OperationType.CALLBACK:
        p = (task.priority or "B").upper()
        # Kept under the old JSON key "maintenance_type" so the existing Flutter
        # monthly report table can render it without a frontend rewrite.
        return f"CB {p}"
    return task.task_type.maintenance_type if task.task_type else None


def _build_report(group, year, month, as_of=None, operation_type=OperationType.MAINTENANCE):
    scheds = list(_group_schedules(group, year, month, as_of, operation_type))

    per_tech = defaultdict(lambda: defaultdict(list))
    tech_name = {}
    for s in scheds:
        t = s.technician
        tech_name[t.id] = t.full_name
        day = s.start_time.date().isoformat()
        per_tech[t.id][day].append({
            "building": s.task.unit.unit_name,
            "unit_code": s.task.unit.unit_code,
            "maintenance_type": _visit_type(s.task, operation_type),
            "operation_type": operation_type,
            "priority": s.task.priority,
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


class ReportMonthsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        group = _supervised_group(request)
        if group is None:
            return Response({"error": "Not a supervisor of any group."}, status=403)

        operation_type = _operation_for_group(request, group)
        rng = (_group_schedules(group, as_of=_as_of(request), operation_type=operation_type)
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
        return Response({"months": months, "operation_type": operation_type})


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

        operation_type = _operation_for_group(request, group)
        technicians = _build_report(group, year, month, _as_of(request), operation_type)
        return Response({
            "group": group.name,
            "operation_type": operation_type,
            "report_type": "callback" if operation_type == OperationType.CALLBACK else "maintenance",
            "year": year,
            "month": month,
            "label": date(year, month, 1).strftime("%B %Y"),
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

        operation_type = _operation_for_group(request, group)
        technicians = _build_report(group, year, month, _as_of(request), operation_type)
        label = date(year, month, 1).strftime("%B_%Y")
        type_label = "callback" if operation_type == OperationType.CALLBACK else "maintenance"

        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill
        except ImportError:
            return Response({"error": "openpyxl not installed. Run: pip install openpyxl"}, status=500)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Summary"
        head_fill = PatternFill("solid", fgColor="1F4E78")
        head_font = Font(bold=True, color="FFFFFF")
        headers = ["Technician", "Days Worked", "Visits", "Total Hours"]
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
        dheaders = ["Technician", "Date", "Start", "End", "Building", "Type", "Minutes", "Travel (min)"]
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
        for col, w in zip("ABCDEFGH", [24, 12, 8, 8, 32, 10, 10, 12]):
            ws2.column_dimensions[col].width = w

        resp = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = f'attachment; filename="{group.code}_{type_label}_report_{label}.xlsx"'
        wb.save(resp)
        return resp
