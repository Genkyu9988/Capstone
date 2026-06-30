
# api/monthly_log_views.py
# Enhanced Monthly Log endpoint for both roll-date and full schedule scopes.
from __future__ import annotations

from datetime import datetime, date, time
from decimal import Decimal
from typing import Any, Dict, List

from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.active_day import get_active_datetime
from api.models import (
    Schedule,
    Task,
    Technician,
    TechnicianRole,
    OperationType,
    SupervisorGroup,
)


def _parse_month_bounds(year: int, month: int):
    start = timezone.make_aware(datetime(year, month, 1, 0, 0), timezone.get_current_timezone())
    if month == 12:
        end = timezone.make_aware(datetime(year + 1, 1, 1, 0, 0), timezone.get_current_timezone())
    else:
        end = timezone.make_aware(datetime(year, month + 1, 1, 0, 0), timezone.get_current_timezone())
    return start, end


def _group_for_user(user):
    if not user or not user.is_authenticated:
        return None
    try:
        return user.supervised_group
    except Exception:
        return None


def _group_type(group: SupervisorGroup | None) -> str:
    if group is None:
        return "mixed"
    roles = set(
        Technician.objects.filter(group=group, is_active_employee=True)
        .values_list("tech_role", flat=True)
    )
    if TechnicianRole.CALLBACK in roles and TechnicianRole.MAINTENANCE in roles:
        return "mixed"
    if TechnicianRole.CALLBACK in roles:
        return "callback"
    return "maintenance"


def _dt_iso_or_empty(dt):
    return dt.isoformat() if dt else ""


def _hhmm(dt):
    if not dt:
        return ""
    return timezone.localtime(dt).strftime("%H:%M")


def _ymd(dt):
    if not dt:
        return ""
    return timezone.localtime(dt).date().isoformat()


def _safe_decimal(v) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except Exception:
        return 0.0


def _priority_of(task) -> str:
    if getattr(task, "priority", None):
        return str(task.priority)
    tt = task.task_type
    if getattr(tt, "maintenance_type", None):
        return str(tt.maintenance_type)
    code = getattr(tt, "code", "") or ""
    for x in ["AA", "A", "B", "C", "D"]:
        if code.endswith(x) or f"-{x}" in code:
            return x
    return code or "-"


def _sla_limit_min(task) -> int | None:
    tt = task.task_type
    if getattr(tt, "sla_target_min", None):
        return int(tt.sla_target_min)
    pr = _priority_of(task)
    if pr == "AA":
        return 60
    if pr == "B":
        return 240
    return None


def _task_kind(task) -> str:
    op = str(task.task_type.operation_type)
    if op == OperationType.CALLBACK:
        return "Callback"
    if op == OperationType.MAINTENANCE:
        return "Maintenance"
    return op.title()


def _status_for_schedule(s, now, first_future_by_tech) -> str:
    if not now:
        return "ON PLAN"
    if s.end_time <= now:
        return "DONE"
    if s.start_time <= now < s.end_time:
        return "ON SITE"
    if s.id == first_future_by_tech.get(s.technician_id):
        return "ON ROUTE"
    return "ON PLAN"


def _status_label(status: str) -> str:
    return {
        "DONE": "Done",
        "ON SITE": "On site",
        "ON ROUTE": "On route",
        "ON PLAN": "On plan",
        "UNASSIGNED": "Unassigned",
        "SLA MISSED": "SLA missed",
    }.get(status, status.title())



def _empty_summary() -> Dict[str, Any]:
    return {
        "total": 0,
        "assigned": 0,
        "unassigned": 0,
        "done": 0,
        "on_site": 0,
        "on_route": 0,
        "on_plan": 0,
        "maintenance": 0,
        "callback": 0,
        "aa": 0,
        "b": 0,
        "sla_met": 0,
        "sla_total": 0,
        "sla_missed": 0,
        "response_minutes_sum": 0,
        "response_count": 0,
        "service_minutes": 0,
        "travel_minutes": 0,
        "route_km": 0.0,
    }


def _summary_from_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build summary from the same rows that are currently shown in the UI.

    This prevents the cards from staying at 0 or showing a different scope when
    status/type/search filters are active.
    """
    summary = _empty_summary()
    for r in rows:
        op = str(r.get("operation") or "")
        pr = str(r.get("priority") or r.get("type") or "")
        status = str(r.get("status") or "").upper().replace(" ", "_")

        summary["total"] += 1
        if status == "UNASSIGNED":
            summary["unassigned"] += 1
        else:
            summary["assigned"] += 1

        if status == "DONE" or status == "COMPLETED":
            summary["done"] += 1
        elif status == "ON_SITE":
            summary["on_site"] += 1
        elif status == "ON_ROUTE":
            summary["on_route"] += 1
        elif status == "ON_PLAN":
            summary["on_plan"] += 1

        if op == str(OperationType.CALLBACK):
            summary["callback"] += 1
            if pr == "AA":
                summary["aa"] += 1
            elif pr == "B":
                summary["b"] += 1
            if r.get("sla_met") is True:
                summary["sla_total"] += 1
                summary["sla_met"] += 1
            elif r.get("sla_met") is False:
                summary["sla_total"] += 1
                summary["sla_missed"] += 1
            if r.get("response_min") is not None:
                summary["response_minutes_sum"] += int(r.get("response_min") or 0)
                summary["response_count"] += 1
        elif op == str(OperationType.MAINTENANCE):
            summary["maintenance"] += 1

        summary["service_minutes"] += int(r.get("duration_min") or 0)
        summary["travel_minutes"] += int(r.get("travel_min") or 0)
        try:
            summary["route_km"] += float(r.get("route_km") or 0)
        except Exception:
            pass

    summary["route_km"] = round(summary["route_km"], 1)
    summary["travel_hours"] = round(summary["travel_minutes"] / 60.0, 1)
    summary["service_hours"] = round(summary["service_minutes"] / 60.0, 1)
    summary["sla_pct"] = round((summary["sla_met"] / summary["sla_total"] * 100), 1) if summary["sla_total"] else None
    summary["avg_response_min"] = round(summary["response_minutes_sum"] / summary["response_count"], 1) if summary["response_count"] else None
    return summary


class MonthlyLogView(APIView):
    """Chronological monthly work/event log.

    Scope rules:
    - normal top tab: month start -> current roll datetime
    - Full · Monthly Log: whole selected month/generated scope (`as_of=all`)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            year = int(request.query_params.get("year"))
            month = int(request.query_params.get("month"))
        except Exception:
            today = timezone.localdate()
            year, month = today.year, today.month

        page = max(1, int(request.query_params.get("page") or 1))
        page_size = min(200, max(20, int(request.query_params.get("page_size") or 100)))
        search = (request.query_params.get("search") or "").strip()
        status_filter = (request.query_params.get("status") or "").strip().upper()
        priority_filter = (request.query_params.get("priority") or "").strip().upper()
        as_of = (request.query_params.get("as_of") or "").strip().lower()

        group = _group_for_user(request.user)
        gtype = _group_type(group)
        month_start, month_end = _parse_month_bounds(year, month)
        now = get_active_datetime(request)
        if as_of != "all" and now:
            # roll-date view: only show generated work up to the rolled time
            scope_end = min(month_end, now)
        else:
            scope_end = month_end

        schedules = (
            Schedule.objects.select_related(
                "task", "task__unit", "task__task_type", "technician", "technician__group"
            )
            .filter(start_time__gte=month_start, start_time__lt=scope_end)
        )
        if group is not None:
            schedules = schedules.filter(technician__group=group)
        if gtype == "callback":
            schedules = schedules.filter(task__task_type__operation_type=OperationType.CALLBACK)
        elif gtype == "maintenance":
            schedules = schedules.filter(task__task_type__operation_type=OperationType.MAINTENANCE)

        if search:
            schedules = schedules.filter(
                Q(task__unit__unit_name__icontains=search) |
                Q(task__unit__unit_code__icontains=search) |
                Q(technician__full_name__icontains=search) |
                Q(task__task_no__icontains=search)
            )

        # First future task per technician for ON ROUTE status.
        first_future_by_tech: Dict[int, int] = {}
        if now:
            future = schedules.filter(start_time__gt=now).order_by("technician_id", "start_time", "sequence_order")
            for s in future:
                first_future_by_tech.setdefault(s.technician_id, s.id)

        rows: List[Dict[str, Any]] = []
        summary = _empty_summary()

        for s in schedules.order_by("start_time", "sequence_order"):
            task = s.task
            unit = task.unit
            op = str(task.task_type.operation_type)
            kind = _task_kind(task)
            pr = _priority_of(task)
            status = _status_for_schedule(s, now, first_future_by_tech)
            duration = int((s.end_time - s.start_time).total_seconds() // 60) if s.end_time and s.start_time else (task.estimated_duration_min or 0)
            travel = int(s.travel_time_min or 0)
            km = _safe_decimal(s.travel_distance_km)
            response_min = None
            sla_met = None
            sla_deadline_min = None
            if op == OperationType.CALLBACK:
                release = task.release_time or task.earliest_start
                sla_deadline_min = _sla_limit_min(task)
                if release and s.start_time:
                    response_min = max(0, int((s.start_time - release).total_seconds() // 60))
                    if sla_deadline_min:
                        sla_met = response_min <= sla_deadline_min
                        summary["sla_total"] += 1
                        if sla_met:
                            summary["sla_met"] += 1
                        else:
                            summary["sla_missed"] += 1
                    summary["response_minutes_sum"] += response_min
                    summary["response_count"] += 1

            if op == OperationType.CALLBACK:
                summary["callback"] += 1
                if pr == "AA":
                    summary["aa"] += 1
                elif pr == "B":
                    summary["b"] += 1
            elif op == OperationType.MAINTENANCE:
                summary["maintenance"] += 1

            summary["assigned"] += 1
            summary["service_minutes"] += duration
            summary["travel_minutes"] += travel
            summary["route_km"] += km
            key = status.lower().replace(" ", "_")
            if key in summary:
                summary[key] += 1

            rows.append({
                "id": s.id,
                "task_id": task.id,
                "task_no": task.task_no,
                "unit_name": unit.unit_name,
                "unit_code": unit.unit_code,
                "kind": kind,
                "operation": op,
                "type": pr,
                "priority": pr,
                "technician": s.technician.full_name if s.technician else None,
                "technician_id": s.technician_id,
                "date": _ymd(s.start_time),
                "start": _hhmm(s.start_time),
                "end": _hhmm(s.end_time),
                "reported": _hhmm(task.release_time),
                "reported_date": _ymd(task.release_time),
                "duration_min": duration,
                "travel_min": travel,
                "route_km": round(km, 2),
                "response_min": response_min,
                "sla_deadline_min": sla_deadline_min,
                "sla_met": sla_met,
                "status": status,
                "status_label": _status_label(status),
                "unassigned_reason": "",
            })

        # Add visible backlog/unassigned rows. For callback with no group assigned,
        # show it to callback supervisors because it still belongs to callback capacity.
        unassigned = Task.objects.select_related("unit", "task_type", "assigned_group").filter(
            is_active=True,
            is_unassigned=True,
            release_time__gte=month_start,
            release_time__lt=scope_end,
        )
        if gtype == "callback":
            unassigned = unassigned.filter(task_type__operation_type=OperationType.CALLBACK).filter(
                Q(assigned_group=group) | Q(assigned_group__isnull=True)
            )
        elif gtype == "maintenance":
            unassigned = unassigned.filter(task_type__operation_type=OperationType.MAINTENANCE).filter(
                Q(assigned_group=group) | Q(assigned_group__isnull=True)
            )
        elif group is not None:
            unassigned = unassigned.filter(Q(assigned_group=group) | Q(assigned_group__isnull=True))
        if search:
            unassigned = unassigned.filter(
                Q(unit__unit_name__icontains=search) |
                Q(unit__unit_code__icontains=search) |
                Q(task_no__icontains=search)
            )

        for task in unassigned.order_by("release_time", "task_no"):
            unit = task.unit
            op = str(task.task_type.operation_type)
            kind = _task_kind(task)
            pr = _priority_of(task)
            if op == OperationType.CALLBACK:
                summary["callback"] += 1
                if pr == "AA": summary["aa"] += 1
                if pr == "B": summary["b"] += 1
            if op == OperationType.MAINTENANCE:
                summary["maintenance"] += 1
            summary["unassigned"] += 1
            rows.append({
                "id": f"task-{task.id}",
                "task_id": task.id,
                "task_no": task.task_no,
                "unit_name": unit.unit_name,
                "unit_code": unit.unit_code,
                "kind": kind,
                "operation": op,
                "type": pr,
                "priority": pr,
                "technician": None,
                "date": _ymd(task.release_time),
                "start": _hhmm(task.release_time),
                "end": "",
                "reported": _hhmm(task.release_time),
                "reported_date": _ymd(task.release_time),
                "duration_min": int(task.estimated_duration_min or 0),
                "travel_min": 0,
                "route_km": 0,
                "response_min": None,
                "sla_deadline_min": _sla_limit_min(task),
                "sla_met": None,
                "status": "UNASSIGNED",
                "status_label": "Unassigned",
                "unassigned_reason": _translate_reason(task.unassigned_reason or ""),
            })

        # Post filters on computed fields.
        if priority_filter:
            rows = [r for r in rows if str(r.get("priority", "")).upper() == priority_filter]
        if status_filter:
            if status_filter == "SLA_NO":
                rows = [r for r in rows if r.get("sla_met") is False]
            elif status_filter == "SLA_YES":
                rows = [r for r in rows if r.get("sla_met") is True]
            else:
                def _norm_status(row):
                    st = str(row.get("status", "")).upper().replace(" ", "_")
                    return "DONE" if st == "COMPLETED" else st
                rows = [r for r in rows if _norm_status(r) == status_filter]

        rows.sort(key=lambda r: (r.get("date") or "", r.get("start") or "", r.get("unit_name") or ""))
        # Rebuild summary AFTER search/status/priority filters so cards and rows match.
        summary = _summary_from_rows(rows)

        total = len(rows)
        start_i = (page - 1) * page_size
        end_i = start_i + page_size
        return Response({
            "group_type": gtype,
            "group_name": group.name if group else "All groups",
            "scope": "full" if as_of == "all" else "roll-date",
            "scope_start": month_start.date().isoformat(),
            "scope_end": (scope_end.date().isoformat() if scope_end else ""),
            "active_time": now.isoformat() if now else None,
            "total": total,
            "page": page,
            "page_size": page_size,
            "summary": summary,
            "log": rows[start_i:end_i],
        })


def _translate_reason(reason: str) -> str:
    text = reason or ""
    if "Arıza kapasitesi" in text or "max ticket" in text:
        return "Callback capacity is insufficient or the maximum ticket limit has been reached."
    return text
