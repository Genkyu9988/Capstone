from calendar import monthrange
from datetime import date, datetime
from io import BytesIO

from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Schedule, Task, OperationType, CallbackPriority

try:
    from api.active_day import get_active_date
except Exception:  # pragma: no cover - fallback for older local branches
    def get_active_date():
        return timezone.localdate()


PAGE_SIZE = 50


def _group(request):
    return getattr(request.user, "supervised_group", None)


def _parse_as_of(raw):
    if not raw:
        return get_active_date(), False
    raw = str(raw)
    if raw.lower() == "all":
        return get_active_date(), True
    try:
        return date.fromisoformat(raw[:10]), False
    except Exception:
        return get_active_date(), False


def _month_range(anchor, full=False):
    start = date(anchor.year, anchor.month, 1)
    if full:
        end = date(anchor.year, anchor.month, monthrange(anchor.year, anchor.month)[1])
    else:
        end = anchor
    return start, end


def _active_dt(request, as_of_day, full=False):
    if full:
        return None
    # Prefer the rolled simulator time if available through dashboard/clock modules.
    try:
        from api import sim_clock
        now = sim_clock.now()
        if now:
            if timezone.is_naive(now):
                now = timezone.make_aware(now, timezone.get_current_timezone())
            return now
    except Exception:
        pass
    return timezone.make_aware(datetime(as_of_day.year, as_of_day.month, as_of_day.day, 23, 59))


def _priority(task):
    p = task.priority or ""
    if p:
        return str(p)
    code = getattr(task.task_type, "code", "") or ""
    if "AA" in code:
        return "AA"
    if code.endswith("B") or "CB-B" in code:
        return "B"
    return "B"


def _sla_target_min(priority, task):
    val = getattr(task.task_type, "sla_target_min", None)
    if val:
        return int(val)
    return 60 if priority == "AA" else 240


def _response_min(task, start_time):
    if not task.release_time or not start_time:
        return None
    return max(0, int((start_time - task.release_time).total_seconds() // 60))


def _english_reason(reason):
    if not reason:
        return ""
    r = str(reason)
    translations = {
        "Arıza kapasitesi yetersiz veya max ticket sınırına ulaşıldı":
            "Callback capacity is insufficient or the maximum ticket limit has been reached.",
        "Ariza kapasitesi yetersiz veya max ticket sinirina ulasildi":
            "Callback capacity is insufficient or the maximum ticket limit has been reached.",
    }
    return translations.get(r, r)


def _row_status(s, task, active_dt, full=False):
    if task.is_unassigned:
        return "UNASSIGNED", "Unassigned"
    if not s:
        return "ASSIGNED", "Assigned"
    if full or active_dt is None:
        return "ASSIGNED", "Assigned"
    if s.end_time and s.end_time <= active_dt:
        return "DONE", "Done"
    if s.start_time and s.start_time <= active_dt < s.end_time:
        return "ON_SITE", "On site"
    if s.start_time and s.start_time > active_dt:
        return "ON_PLAN", "On plan"
    return "ASSIGNED", "Assigned"


def _assigned_queryset(group, start, end):
    qs = (Schedule.objects
          .filter(task__task_type__operation_type=OperationType.CALLBACK,
                  start_time__date__gte=start,
                  start_time__date__lte=end)
          .select_related("technician", "technician__group", "task", "task__unit", "task__task_type")
          .order_by("-start_time", "technician__full_name", "sequence_order"))
    if group is not None:
        qs = qs.filter(technician__group=group)
    return qs


def _unassigned_queryset(group, start, end):
    qs = (Task.objects
          .filter(task_type__operation_type=OperationType.CALLBACK,
                  is_active=True,
                  is_unassigned=True,
                  release_time__date__gte=start,
                  release_time__date__lte=end)
          .select_related("unit", "task_type", "assigned_group")
          .order_by("-release_time"))
    if group is not None:
        # Old unassigned callback rows often have assigned_group empty; keep those visible
        # to callback supervisors so backlog is not hidden.
        qs = qs.filter(Q(assigned_group=group) | Q(assigned_group__isnull=True))
    return qs


def _build_rows(request):
    group = _group(request)
    as_of_day, full = _parse_as_of(request.query_params.get("as_of"))
    start, end = _month_range(as_of_day, full=full)
    active_dt = _active_dt(request, as_of_day, full=full)

    assigned = list(_assigned_queryset(group, start, end))
    unassigned = list(_unassigned_queryset(group, start, end))

    rows = []
    summary = {
        "total": 0, "assigned": 0, "unassigned": 0,
        "aa": 0, "b": 0, "sla_met": 0, "sla_total": 0,
        "sla_missed": 0, "response_sum": 0, "response_count": 0,
    }

    for s in assigned:
        task = s.task
        pri = _priority(task)
        resp = _response_min(task, s.start_time)
        target = _sla_target_min(pri, task)
        sla_met = (resp is not None and resp <= target)
        status, status_label = _row_status(s, task, active_dt, full=full)
        duration = int((s.end_time - s.start_time).total_seconds() // 60) if s.start_time and s.end_time else (task.estimated_duration_min or 0)
        travel = int(s.travel_time_min or 0)
        km = float(s.travel_distance_km or 0)

        summary["total"] += 1
        summary["assigned"] += 1
        if pri == "AA": summary["aa"] += 1
        else: summary["b"] += 1
        if resp is not None:
            summary["sla_total"] += 1
            summary["response_sum"] += resp
            summary["response_count"] += 1
            if sla_met: summary["sla_met"] += 1
            else: summary["sla_missed"] += 1

        rows.append({
            "id": s.id,
            "task_id": task.id,
            "task_no": task.task_no,
            "kind": "Callback",
            "unit_name": task.unit.unit_name,
            "unit_code": task.unit.unit_code,
            "type": pri,
            "priority": pri,
            "technician": s.technician.full_name if s.technician_id else None,
            "technician_id": s.technician_id,
            "date": s.start_time.date().isoformat() if s.start_time else "",
            "reported": task.release_time.strftime("%H:%M") if task.release_time else "",
            "reported_date": task.release_time.date().isoformat() if task.release_time else "",
            "start": s.start_time.strftime("%H:%M") if s.start_time else "",
            "end": s.end_time.strftime("%H:%M") if s.end_time else "",
            "response_min": resp,
            "sla_deadline_min": target,
            "sla_met": sla_met,
            "sla_label": "SLA YES" if sla_met else "SLA NO",
            "status": status,
            "status_label": status_label,
            "travel_min": travel,
            "route_km": round(km, 2),
            "duration_min": duration,
            "unassigned_reason": "",
            "action_hint": "View on live map" if status != "DONE" else "History",
        })

    for task in unassigned:
        pri = _priority(task)
        summary["total"] += 1
        summary["unassigned"] += 1
        if pri == "AA": summary["aa"] += 1
        else: summary["b"] += 1
        rows.append({
            "id": f"task-{task.id}",
            "task_id": task.id,
            "task_no": task.task_no,
            "kind": "Callback",
            "unit_name": task.unit.unit_name,
            "unit_code": task.unit.unit_code,
            "type": pri,
            "priority": pri,
            "technician": None,
            "technician_id": None,
            "date": task.release_time.date().isoformat() if task.release_time else "",
            "reported": task.release_time.strftime("%H:%M") if task.release_time else "",
            "reported_date": task.release_time.date().isoformat() if task.release_time else "",
            "start": "",
            "end": "",
            "response_min": None,
            "sla_deadline_min": _sla_target_min(pri, task),
            "sla_met": False,
            "sla_label": "SLA RISK",
            "status": "UNASSIGNED",
            "status_label": "Unassigned",
            "travel_min": None,
            "route_km": None,
            "duration_min": task.estimated_duration_min or 60,
            "unassigned_reason": _english_reason(task.unassigned_reason),
            "action_hint": "Dispatch nearest technician" if pri == "AA" else "Add near backlog / dispatch",
        })

    # Search / filters are applied after summary is computed so cards represent the whole scope.
    priority = (request.query_params.get("priority") or "").strip().upper()
    status = (request.query_params.get("status") or "").strip().upper()
    search = (request.query_params.get("search") or "").strip().lower()

    filtered = rows
    if priority:
        filtered = [r for r in filtered if str(r.get("priority", "")).upper() == priority]
    if status:
        if status == "SLA_MISSED":
            filtered = [r for r in filtered if r.get("status") != "UNASSIGNED" and r.get("sla_met") is False]
        elif status == "SLA_MET":
            filtered = [r for r in filtered if r.get("sla_met") is True]
        elif status == "UNASSIGNED":
            filtered = [r for r in filtered if r.get("status") == "UNASSIGNED"]
        elif status == "ASSIGNED":
            filtered = [r for r in filtered if r.get("status") != "UNASSIGNED"]
        else:
            filtered = [r for r in filtered if r.get("status") == status]
    if search:
        filtered = [r for r in filtered if search in str(r.get("unit_name", "")).lower()
                    or search in str(r.get("unit_code", "")).lower()
                    or search in str(r.get("technician", "")).lower()
                    or search in str(r.get("task_no", "")).lower()]

    try:
        page = max(1, int(request.query_params.get("page", 1)))
    except Exception:
        page = 1
    try:
        page_size = max(10, min(200, int(request.query_params.get("page_size", PAGE_SIZE))))
    except Exception:
        page_size = PAGE_SIZE

    total = len(filtered)
    start_i = (page - 1) * page_size
    page_rows = filtered[start_i:start_i + page_size]

    sla_pct = round(summary["sla_met"] / summary["sla_total"] * 100, 1) if summary["sla_total"] else 0.0
    avg_resp = round(summary["response_sum"] / summary["response_count"], 1) if summary["response_count"] else 0.0
    summary.update({
        "sla_pct": sla_pct,
        "avg_response_min": avg_resp,
        "scope_start": start.isoformat(),
        "scope_end": end.isoformat(),
        "full_schedule": full,
    })

    return page_rows, total, page, page_size, summary


class CallbackIncidentCenterView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows, total, page, page_size, summary = _build_rows(request)
        return Response({
            "title": "Callback Incident Center",
            "total": total,
            "page": page,
            "page_size": page_size,
            "summary": summary,
            "breakdown": {"AA": summary["aa"], "B": summary["b"], "Unassigned": summary["unassigned"], "SLA missed": summary["sla_missed"]},
            "tasks": rows,
        })


class CallbackIncidentExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Export all filtered rows by forcing a large page size after reusing the builder.
        mutable = request.GET.copy()
        mutable["page"] = "1"
        mutable["page_size"] = "20000"
        request._request.GET = mutable
        rows, total, page, page_size, summary = _build_rows(request)

        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Callback Incidents"
        ws.append(["Incident ID", "Unit", "Unit Code", "Priority", "Status", "Technician", "Reported Date", "Reported", "Start", "End", "Response min", "SLA Deadline", "SLA Met", "Travel min", "Route KM", "Duration min", "Unassigned Reason", "Action"])
        for r in rows:
            ws.append([
                r.get("task_no"), r.get("unit_name"), r.get("unit_code"), r.get("priority"), r.get("status_label"), r.get("technician") or "-",
                r.get("reported_date"), r.get("reported"), r.get("start"), r.get("end"), r.get("response_min"), r.get("sla_deadline_min"),
                "YES" if r.get("sla_met") else "NO", r.get("travel_min"), r.get("route_km"), r.get("duration_min"), r.get("unassigned_reason"), r.get("action_hint"),
            ])
        ws2 = wb.create_sheet("Summary")
        for k, v in summary.items():
            ws2.append([k, v])
        bio = BytesIO()
        wb.save(bio)
        bio.seek(0)
        resp = HttpResponse(bio.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = 'attachment; filename="callback_incident_center.xlsx"'
        return resp
