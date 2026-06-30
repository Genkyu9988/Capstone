# api/daily_report_views.py
# Dynamic daily operational report for maintenance and callback supervisors.
# Cost-safe: route metrics are read from schedule fields/cache only; Google is never called here.
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import (
    Schedule,
    Task,
    Technician,
    TechnicianRole,
    OperationType,
    SupervisorGroup,
)

try:
    from api.active_day import get_active_datetime
except Exception:  # pragma: no cover
    def get_active_datetime():
        return timezone.now()

try:
    from api.services.maps.route_geometry import build_route_geometry
except Exception:  # pragma: no cover
    build_route_geometry = None


def _group_for_user(user) -> Optional[SupervisorGroup]:
    if not user or not user.is_authenticated:
        return None
    try:
        return user.supervised_group
    except Exception:
        return None


def _group_type(group: Optional[SupervisorGroup]) -> str:
    if not group:
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


def _date_bounds(day: date) -> Tuple[datetime, datetime]:
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    end = timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min), tz)
    return start, end


def _parse_day(raw: str) -> date:
    if raw:
        try:
            return date.fromisoformat(str(raw)[:10])
        except Exception:
            pass
    return timezone.localdate(get_active_datetime())


def _parse_as_of(raw: str, day: date) -> Optional[datetime]:
    """None means full day/static full schedule view.

    For roll-date Daily Report, use the full operating clock timestamp.
    A date-only/midnight value is treated as a legacy frontend value and is
    replaced by the active clock if it is for the same operating day.
    """
    raw = str(raw or "").strip()
    if raw.lower() == "all":
        return None

    def _active_dt():
        active = get_active_datetime()
        if timezone.is_naive(active):
            active = timezone.make_aware(active, timezone.get_current_timezone())
        return active

    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
            local_parsed = timezone.localtime(parsed)
            # Legacy bug guard: activeDate.toIso8601String() sent 00:00, making
            # the first task ON_ROUTE all day. If this happens for today's roll
            # date, use the real operating clock instead.
            if local_parsed.date() == day and local_parsed.hour == 0 and local_parsed.minute == 0 and local_parsed.second == 0:
                try:
                    active = _active_dt()
                    if timezone.localtime(active).date() == day:
                        return active
                except Exception:
                    pass
            return parsed
        except Exception:
            pass
    try:
        return _active_dt()
    except Exception:
        return timezone.make_aware(datetime.combine(day, time.max), timezone.get_current_timezone())


def _hhmm(dt) -> str:
    if not dt:
        return ""
    return timezone.localtime(dt).strftime("%H:%M")


def _ymd(dt) -> str:
    if not dt:
        return ""
    return timezone.localtime(dt).date().isoformat()


def _num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _priority(task: Task) -> str:
    if task.priority:
        return str(task.priority)
    code = (getattr(task.task_type, "code", "") or "").upper()
    if "AA" in code:
        return "AA"
    if "CB-B" in code or code.endswith("B"):
        return "B"
    if getattr(task.task_type, "maintenance_type", None):
        return str(task.task_type.maintenance_type)
    return code.replace("MNT-", "").replace("CB-", "")[:2] or "-"


def _operation(task: Task) -> str:
    try:
        return str(task.task_type.operation_type)
    except Exception:
        return ""


def _is_callback(task: Task) -> bool:
    return _operation(task) == OperationType.CALLBACK


def _is_maintenance(task: Task) -> bool:
    return _operation(task) == OperationType.MAINTENANCE


def _status_for_schedule(s: Schedule, as_of: Optional[datetime], next_ids: set[int]) -> str:
    if as_of is None:
        return "DONE"
    if s.end_time <= as_of:
        return "DONE"
    if s.start_time <= as_of < s.end_time:
        return "ON_SITE"
    if s.id in next_ids:
        return "ON_ROUTE"
    return "ON_PLAN"


def _status_label(status: str) -> str:
    return {
        "DONE": "DONE",
        "ON_SITE": "ON SITE",
        "ON_ROUTE": "ON ROUTE",
        "ON_PLAN": "ON PLAN",
        "UNASSIGNED": "UNASSIGNED",
    }.get(status, status)


def _sla_info(task: Task, start_time) -> Tuple[Optional[int], Optional[bool], Optional[int]]:
    if not _is_callback(task) or not start_time:
        return None, None, None
    release = task.release_time or task.earliest_start
    if not release:
        return None, None, None
    response_min = int(round((start_time - release).total_seconds() / 60.0))
    target = int(task.task_type.sla_target_min or (60 if _priority(task) == "AA" else 240))
    return response_min, response_min <= target, target


def _technician_day_route_metrics(tech: Technician, schedules: List[Schedule]) -> Tuple[float, int, str]:
    """Read cached route metrics for a technician day. Never calls Google."""
    if not schedules:
        return 0.0, 0, ""
    stops = []
    for s in schedules:
        u = s.task.unit
        if u and u.latitude is not None and u.longitude is not None:
            stops.append({"lat": float(u.latitude), "lng": float(u.longitude)})
    origin = None
    if tech.current_latitude is not None and tech.current_longitude is not None:
        origin = {"lat": float(tech.current_latitude), "lng": float(tech.current_longitude)}
    elif stops:
        origin = stops[0]
    if not origin or not stops:
        return 0.0, 0, ""
    if build_route_geometry:
        try:
            geo = build_route_geometry(origin, stops, allow_google_call=False)
            return _num(geo.get("distance_km")), int(_num(geo.get("duration_min"), 0)), str(geo.get("source") or "")
        except Exception:
            pass
    # Last-resort: schedule fields only.
    km = sum(_num(s.travel_distance_km) for s in schedules)
    mins = sum(int(_num(s.travel_time_min)) for s in schedules)
    return km, mins, "SCHEDULE_FIELDS"


class DailyReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        group = _group_for_user(request.user)
        gtype = _group_type(group)
        day = _parse_day(request.query_params.get("date", ""))
        as_of = _parse_as_of(request.query_params.get("as_of", ""), day)
        start, end = _date_bounds(day)
        status_filter = str(request.query_params.get("status", "all") or "all").upper()
        type_filter = str(request.query_params.get("type", request.query_params.get("priority", "all")) or "all").upper()
        search = str(request.query_params.get("search", "") or "").strip()

        schedules_qs = Schedule.objects.filter(start_time__gte=start, start_time__lt=end)
        if group:
            schedules_qs = schedules_qs.filter(technician__group=group)
        if gtype == "callback":
            schedules_qs = schedules_qs.filter(task__task_type__operation_type=OperationType.CALLBACK)
        elif gtype == "maintenance":
            schedules_qs = schedules_qs.filter(task__task_type__operation_type=OperationType.MAINTENANCE)

        if search:
            schedules_qs = schedules_qs.filter(
                Q(task__unit__unit_name__icontains=search)
                | Q(task__unit__unit_code__icontains=search)
                | Q(technician__full_name__icontains=search)
                | Q(task__task_no__icontains=search)
            )

        schedules = list(
            schedules_qs.select_related("task", "task__unit", "task__task_type", "technician", "technician__group")
            .order_by("technician__full_name", "start_time", "sequence_order")
        )

        # Find each technician's next future task for ON_ROUTE status.
        next_ids: set[int] = set()
        if as_of is not None:
            by_tech: Dict[int, List[Schedule]] = {}
            for s in schedules:
                by_tech.setdefault(s.technician_id, []).append(s)
            for tech_id, items in by_tech.items():
                future = [s for s in items if s.start_time > as_of]
                if future:
                    next_ids.add(future[0].id)

        # Route metrics by technician-day, used both for summary and row fallback.
        route_by_tech: Dict[int, Tuple[float, int, str, int]] = {}
        by_tech_all: Dict[int, List[Schedule]] = {}
        for s in schedules:
            by_tech_all.setdefault(s.technician_id, []).append(s)
        for tech_id, items in by_tech_all.items():
            km, mins, source = _technician_day_route_metrics(items[0].technician, items)
            route_by_tech[tech_id] = (km, mins, source, max(len(items), 1))

        rows: List[Dict[str, Any]] = []
        tech_summary: Dict[int, Dict[str, Any]] = {}
        summary = {
            "tasks": 0,
            "assigned": 0,
            "unassigned": 0,
            "done": 0,
            "active": 0,
            "on_route": 0,
            "on_site": 0,
            "on_plan": 0,
            "service_minutes": 0,
            "travel_minutes": 0,
            "route_km": 0.0,
            "technicians": 0,
            "aa": 0,
            "b": 0,
            "sla_met": 0,
            "sla_total": 0,
            "response_total": 0,
            "response_count": 0,
            "a": 0,
            "c": 0,
        }

        for s in schedules:
            task = s.task
            pr = _priority(task)
            if type_filter not in {"", "ALL"} and pr.upper() != type_filter:
                continue
            status = _status_for_schedule(s, as_of, next_ids)
            resp_min, sla_met, sla_target = _sla_info(task, s.start_time)
            if status_filter not in {"", "ALL"}:
                if status_filter in {"SLA_MET", "SLA YES", "SLA_YES"} and sla_met is not True:
                    continue
                if status_filter in {"SLA_MISSED", "SLA NO", "SLA_NO"} and sla_met is not False:
                    continue
                if status_filter not in {"SLA_MET", "SLA YES", "SLA_YES", "SLA_MISSED", "SLA NO", "SLA_NO"} and status != status_filter:
                    continue

            service_min = int(round((s.end_time - s.start_time).total_seconds() / 60.0))
            daily_km, daily_travel, source, n = route_by_tech.get(s.technician_id, (0.0, 0, "", 1))
            row_km = _num(s.travel_distance_km)
            row_travel = int(_num(s.travel_time_min))
            if row_km <= 0 and daily_km > 0:
                row_km = daily_km / n
            if row_travel <= 0 and daily_travel > 0:
                row_travel = int(round(daily_travel / n))

            row = {
                "id": s.id,
                "task_id": task.id,
                "task_no": task.task_no,
                "date": _ymd(s.start_time),
                "unit": task.unit.unit_name,
                "unit_code": task.unit.unit_code,
                "operation": _operation(task),
                "type": pr,
                "technician": s.technician.full_name,
                "technician_id": s.technician_id,
                "start": _hhmm(s.start_time),
                "end": _hhmm(s.end_time),
                "reported": _hhmm(task.release_time) if task.release_time else "",
                "status": status,
                "status_label": _status_label(status),
                "service_min": service_min,
                "travel_min": row_travel,
                "route_km": round(row_km, 1),
                "route_source": source,
                "response_min": resp_min,
                "sla_target_min": sla_target,
                "sla_met": sla_met,
                "unassigned_reason": "",
                "is_unassigned": False,
            }
            rows.append(row)

            summary["tasks"] += 1
            summary["assigned"] += 1
            summary["service_minutes"] += service_min
            summary["travel_minutes"] += row_travel
            summary["route_km"] += row_km
            if status == "DONE":
                summary["done"] += 1
            elif status == "ON_ROUTE":
                summary["on_route"] += 1
                summary["active"] += 1
            elif status == "ON_SITE":
                summary["on_site"] += 1
                summary["active"] += 1
            elif status == "ON_PLAN":
                summary["on_plan"] += 1
            if pr == "AA":
                summary["aa"] += 1
            elif pr == "B":
                summary["b"] += 1
            elif pr == "A":
                summary["a"] += 1
            elif pr == "C":
                summary["c"] += 1
            if sla_met is not None:
                summary["sla_total"] += 1
                if sla_met:
                    summary["sla_met"] += 1
            if resp_min is not None:
                summary["response_total"] += resp_min
                summary["response_count"] += 1

            ts = tech_summary.setdefault(s.technician_id, {
                "technician": s.technician.full_name,
                "role": s.technician.tech_role,
                "specialty": s.technician.specialty,
                "stops": 0,
                "service_minutes": 0,
                "travel_minutes": 0,
                "route_km": 0.0,
                "done": 0,
                "active": 0,
                "rows": [],
            })
            ts["stops"] += 1
            ts["service_minutes"] += service_min
            ts["travel_minutes"] += row_travel
            ts["route_km"] += row_km
            if status == "DONE":
                ts["done"] += 1
            if status in {"ON_ROUTE", "ON_SITE"}:
                ts["active"] += 1
            ts["rows"].append(row)

        # Add unassigned active tasks for the selected day.
        task_day_q = Q(release_time__gte=start, release_time__lt=end) | Q(earliest_start__gte=start, earliest_start__lt=end)
        unassigned_qs = Task.objects.filter(is_active=True, is_unassigned=True).filter(task_day_q)
        if gtype == "callback":
            unassigned_qs = unassigned_qs.filter(task_type__operation_type=OperationType.CALLBACK)
            if group:
                unassigned_qs = unassigned_qs.filter(Q(assigned_group=group) | Q(assigned_group__isnull=True))
        elif gtype == "maintenance":
            unassigned_qs = unassigned_qs.filter(task_type__operation_type=OperationType.MAINTENANCE)
            if group:
                unassigned_qs = unassigned_qs.filter(assigned_group=group)
        elif group:
            unassigned_qs = unassigned_qs.filter(Q(assigned_group=group) | Q(assigned_group__isnull=True))
        if search:
            unassigned_qs = unassigned_qs.filter(
                Q(unit__unit_name__icontains=search)
                | Q(unit__unit_code__icontains=search)
                | Q(task_no__icontains=search)
            )

        for task in unassigned_qs.select_related("unit", "task_type").order_by("release_time", "task_no"):
            pr = _priority(task)
            if type_filter not in {"", "ALL"} and pr.upper() != type_filter:
                continue
            if status_filter not in {"", "ALL", "UNASSIGNED"}:
                continue
            row = {
                "id": None,
                "task_id": task.id,
                "task_no": task.task_no,
                "date": _ymd(task.release_time or task.earliest_start or start),
                "unit": task.unit.unit_name,
                "unit_code": task.unit.unit_code,
                "operation": _operation(task),
                "type": pr,
                "technician": "-",
                "technician_id": None,
                "start": _hhmm(task.release_time or task.earliest_start),
                "end": "",
                "reported": _hhmm(task.release_time),
                "status": "UNASSIGNED",
                "status_label": "UNASSIGNED",
                "service_min": int(task.estimated_duration_min or task.task_type.base_duration_min or 0),
                "travel_min": None,
                "route_km": None,
                "route_source": "",
                "response_min": None,
                "sla_target_min": int(task.task_type.sla_target_min or (60 if pr == "AA" else 240)) if _is_callback(task) else None,
                "sla_met": False if _is_callback(task) else None,
                "unassigned_reason": _translate_reason(task.unassigned_reason or ""),
                "is_unassigned": True,
            }
            rows.append(row)
            summary["tasks"] += 1
            summary["unassigned"] += 1
            if pr == "AA":
                summary["aa"] += 1
            elif pr == "B":
                summary["b"] += 1
            elif pr == "A":
                summary["a"] += 1
            elif pr == "C":
                summary["c"] += 1
            if _is_callback(task):
                summary["sla_total"] += 1

        summary["route_km"] = round(summary["route_km"], 1)
        summary["service_hours"] = round(summary["service_minutes"] / 60.0, 1)
        summary["travel_hours"] = round(summary["travel_minutes"] / 60.0, 1)
        summary["duty_hours"] = round((summary["service_minutes"] + summary["travel_minutes"]) / 60.0, 1)
        summary["technicians"] = len(tech_summary)
        summary["sla_pct"] = round((summary["sla_met"] / summary["sla_total"] * 100.0), 1) if summary["sla_total"] else None
        summary["avg_response_min"] = int(round(summary["response_total"] / summary["response_count"])) if summary["response_count"] else None

        techs = []
        for v in tech_summary.values():
            v["service_hours"] = round(v["service_minutes"] / 60.0, 1)
            v["travel_hours"] = round(v["travel_minutes"] / 60.0, 1)
            v["duty_hours"] = round((v["service_minutes"] + v["travel_minutes"]) / 60.0, 1)
            v["route_km"] = round(v["route_km"], 1)
            techs.append(v)
        techs.sort(key=lambda x: x["technician"])

        # Sort rows chronologically after adding unassigned rows.
        rows.sort(key=lambda r: (r.get("date") or "", r.get("start") or "99:99", r.get("technician") or ""))

        return Response({
            "date": day.isoformat(),
            "as_of": as_of.isoformat() if as_of else "all",
            "group_type": gtype,
            "group_name": group.name if group else "All groups",
            "summary": summary,
            "rows": rows,
            "technicians": techs,
            # Backward compatibility for older frontend cards.
            "total_visits": summary["tasks"],
            "fault_count": summary["tasks"] if gtype == "callback" else 0,
            "faults": rows if gtype == "callback" else [],
        })


def _translate_reason(text: str) -> str:
    if not text:
        return "Capacity or timing constraints prevented assignment."
    lower = text.lower()
    if "kapasite" in lower or "ticket" in lower:
        return "Capacity is insufficient or the maximum ticket limit has been reached."
    if "uzman" in lower or "special" in lower:
        return "No suitable technician specialty was available."
    return text
