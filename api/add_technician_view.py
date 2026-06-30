"""
api/add_technician_view.py
=============================================================================
Technician management for the LOGGED-IN supervisor's own group.

  POST   /api/technicians/add/              create a technician in my group
  POST   /api/technicians/<id>/remove/      soft-delete (is_active_employee=False)
  POST   /api/technicians/<id>/reactivate/  bring a removed technician back

Soft delete keeps the row (and all schedule/task history) intact -- it only
hides the technician from the active roster. This is separate from LEAVE:
  - leave        -> is_available = False      (temporarily away, still employed)
  - soft delete  -> is_active_employee = False (no longer on the roster)

A supervisor can only add to / remove from THEIR OWN group (scoped by the
auth token). Excel files are never touched -- only the database changes.

Wire in api/urls.py:
    from .add_technician_view import (
        AddTechnicianView, RemoveTechnicianView, ReactivateTechnicianView,
    )
    path("technicians/add/", AddTechnicianView.as_view()),
    path("technicians/<int:pk>/remove/", RemoveTechnicianView.as_view()),
    path("technicians/<int:pk>/reactivate/", ReactivateTechnicianView.as_view()),
=============================================================================
"""
import math
from datetime import date, datetime, time

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.contrib.auth.models import User
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import (
    Technician, UserProfile, UserRole,
    TechnicianRole, SpecialtyType, ExperienceLevel,
    Schedule, OperationType, Task,
)
from api.services.schedule_rebuild import (
    rebuild_group_future_schedule,
    rebuild_group_future_callbacks,
)

DEFAULT_PASSWORD = "tech12345"

VALID_ROLES = {TechnicianRole.MAINTENANCE, TechnicianRole.CALLBACK}
VALID_SPECS = {SpecialtyType.ELEVATOR, SpecialtyType.ESCALATOR, SpecialtyType.BOTH}


def _supervised_group(request):
    """The group the logged-in user supervises, or None."""
    return getattr(request.user, "supervised_group", None)


def _group_hq(group):
    """Derive the group's HQ from an existing located technician in it."""
    t = (Technician.objects
         .filter(group=group, current_latitude__isnull=False)
         .first())
    if t is not None:
        return float(t.current_latitude), float(t.current_longitude)
    # Istanbul centre fallback if the group has no located techs yet
    return 41.0700, 29.0100


def _safe_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_as_of(value):
    """Parse the supervisor roll-date/active-time sent by the web dashboard.

    If the UI does not send it, fall back to now.  The preview must be scoped
    to the roll date; otherwise the same numbers appear for every rolled day.
    """
    if not value:
        return timezone.now()

    dt = parse_datetime(str(value))
    if dt is not None:
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt

    d = parse_date(str(value))
    if d is not None:
        return timezone.make_aware(datetime.combine(d, time.max), timezone.get_current_timezone())

    return timezone.now()


def _period_start_for(as_of_dt):
    d = as_of_dt.date()
    return date(d.year, d.month, 1)


def _unassigned_tasks_for(group, operation, limit=25, as_of_dt=None, period_start=None):
    """Return active unassigned backlog tasks relevant to this supervisor group.

    Scope matters: the supervisor may roll the simulation clock.  Only backlog
    that has been released up to that rolled time should influence the preview
    or the near-backlog placement suggestion.

    Some callback tasks are intentionally left with assigned_group=NULL when the
    optimizer could not place them. For callback supervisors, those NULL backlog
    tasks are still relevant because either callback group can add capacity or
    dispatch a technician. For maintenance, assigned_group-scoped backlog is
    preferred, but NULL backlog is also shown as capacity risk.
    """
    qs = (
        Task.objects
        .filter(
            is_active=True,
            is_unassigned=True,
            task_type__operation_type=operation,
        )
        .filter(Q(assigned_group=group) | Q(assigned_group__isnull=True))
    )

    if period_start is not None:
        qs = qs.filter(release_time__date__gte=period_start)
    if as_of_dt is not None:
        qs = qs.filter(release_time__lte=as_of_dt)

    qs = qs.select_related("unit", "task_type", "assigned_group").order_by("release_time", "id")
    return list(qs[:limit])


def _backlog_location(backlog):
    """Centroid of unassigned task units, used as suggested base for add-near-backlog."""
    pts = []
    for task in backlog:
        unit = getattr(task, "unit", None)
        if unit and unit.latitude is not None and unit.longitude is not None:
            pts.append((float(unit.latitude), float(unit.longitude)))
    if not pts:
        return None, None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def _backlog_payload(backlog):
    aa = 0
    b = 0
    rows = []
    for task in backlog[:10]:
        priority = (task.priority or "").upper()
        if priority == "AA":
            aa += 1
        elif priority == "B":
            b += 1
        unit = getattr(task, "unit", None)
        rows.append({
            "id": task.id,
            "task_no": task.task_no,
            "unit_name": unit.unit_name if unit else "-",
            "priority": priority or (task.task_type.code if task.task_type else ""),
            "reason": task.unassigned_reason or "Unassigned",
            "latitude": float(unit.latitude) if unit and unit.latitude is not None else None,
            "longitude": float(unit.longitude) if unit and unit.longitude is not None else None,
        })
    return {
        "count": len(backlog),
        "aa_count": aa,
        "b_count": b,
        "tasks": rows,
    }


def _maybe_rebuild_future_schedule(group, request, technician_role):
    """Run the correct next-day rebuild after add/remove/reactivate.

    MAINTENANCE technicians rebuild future maintenance schedules with Gurobi.
    CALLBACK technicians rebuild future callback schedules with the callback roster
    solver. The current roll-date day remains frozen; the effect starts from the
    next planning day, which is the realistic demo behavior.
    """
    try:
        if technician_role == TechnicianRole.CALLBACK:
            return rebuild_group_future_callbacks(group, request=request)
        return rebuild_group_future_schedule(group, request=request)
    except Exception as exc:
        return {
            "triggered": False,
            "error": str(exc),
            "reason": "Roster was changed, but future schedule rebuild failed.",
        }


def _rebuild_message(rebuild):
    if not rebuild:
        return ""
    if rebuild.get("triggered"):
        mode = rebuild.get("mode") or "future_roster"
        return (
            f" Future schedule rebuilt from {rebuild.get('effective_date')} "
            f"to {rebuild.get('end_date')} using Gurobi ({mode})."
        )
    if rebuild.get("effective_date"):
        return f" Future schedule rebuild not run: {rebuild.get('reason', 'not required')}"
    return f" {rebuild.get('reason', '')}".rstrip()


class AddTechnicianView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        group = _supervised_group(request)
        if group is None:
            return Response(
                {"error": "This account is not a supervisor of any group."},
                status=403)

        full_name = (request.data.get("full_name") or "").strip()
        role = (request.data.get("tech_role") or "").strip().upper()
        spec = (request.data.get("specialty") or "").strip().upper()

        if not full_name:
            return Response({"error": "full_name required"}, status=400)
        if role not in VALID_ROLES:
            return Response(
                {"error": f"tech_role must be one of {sorted(VALID_ROLES)}"},
                status=400)
        if spec not in VALID_SPECS:
            return Response(
                {"error": f"specialty must be one of {sorted(VALID_SPECS)}"},
                status=400)

        # Callback technicians always cover both specialties.
        if role == TechnicianRole.CALLBACK:
            spec = SpecialtyType.BOTH

        add_mode = (request.data.get("add_mode") or request.data.get("placement_mode") or "NORMAL").strip().upper()
        if add_mode not in {"NORMAL", "BACKLOG"}:
            add_mode = "NORMAL"

        as_of_dt = _parse_as_of(request.data.get("as_of") or request.data.get("active_time"))
        period_start = _period_start_for(as_of_dt)

        # Optional location. Normal add defaults to group HQ. Backlog add defaults
        # to the centroid of relevant unassigned tasks if no explicit location is sent.
        explicit_lat = _safe_float(request.data.get("current_latitude") or request.data.get("latitude"))
        explicit_lng = _safe_float(request.data.get("current_longitude") or request.data.get("longitude"))

        # Guard: a single-role group must stay single-role. A maintenance-only
        # HQ cannot gain a callback tech (and vice-versa). Only a MIXED group
        # (already has both) may add either. This mirrors the dashboard UI.
        existing_roles = set(
            Technician.objects.filter(group=group)
            .values_list("tech_role", flat=True)
        )
        has_maint = TechnicianRole.MAINTENANCE in existing_roles
        has_call = TechnicianRole.CALLBACK in existing_roles
        is_mixed = has_maint and has_call
        if not is_mixed and existing_roles:
            only_role = TechnicianRole.MAINTENANCE if has_maint else TechnicianRole.CALLBACK
            if role != only_role:
                return Response({
                    "error": f"This group is {only_role.lower()}-only. "
                             f"You can only add {only_role.lower()} technicians here."
                }, status=400)

        # unique employee code + username (NEW- prefix never clashes with T001..)
        n = Technician.objects.filter(employee_code__startswith="NEW-T").count() + 1
        code = f"NEW-T{n:03d}"
        while Technician.objects.filter(employee_code=code).exists():
            n += 1
            code = f"NEW-T{n:03d}"
        uname = f"new_t{n:03d}"
        while User.objects.filter(username=uname).exists():
            n += 1
            uname = f"new_t{n:03d}"
            code = f"NEW-T{n:03d}"

        parts = full_name.split()
        user = User.objects.create(
            username=uname,
            first_name=parts[0],
            last_name=parts[-1] if len(parts) > 1 else "",
        )
        user.set_password(DEFAULT_PASSWORD)
        user.save()
        UserProfile.objects.update_or_create(
            user=user, defaults={"role": UserRole.TECH})

        operation = OperationType.CALLBACK if role == TechnicianRole.CALLBACK else OperationType.MAINTENANCE
        placement_note = "Group base location"
        if explicit_lat is not None and explicit_lng is not None:
            hq_lat, hq_lng = explicit_lat, explicit_lng
            placement_note = "Supervisor-selected location"
        elif add_mode == "BACKLOG":
            backlog = _unassigned_tasks_for(group, operation, limit=50, as_of_dt=as_of_dt, period_start=period_start)
            lat, lng = _backlog_location(backlog)
            if lat is not None and lng is not None:
                hq_lat, hq_lng = lat, lng
                placement_note = f"Near unassigned backlog centroid ({len(backlog)} task(s))"
            else:
                hq_lat, hq_lng = _group_hq(group)
                placement_note = "Backlog mode selected, but no backlog location found; used group base"
        else:
            hq_lat, hq_lng = _group_hq(group)

        tech = Technician.objects.create(
            user=user,
            employee_code=code,
            full_name=full_name,
            group=group,
            tech_role=role,
            specialty=spec,
            experience_level=ExperienceLevel.JUNIOR,
            is_available=True,
            is_active_employee=True,
            daily_capacity_min=480,
            max_overtime_min=60,
            current_latitude=hq_lat,
            current_longitude=hq_lng,
        )

        rebuild = _maybe_rebuild_future_schedule(group, request, tech.tech_role)

        return Response({
            "id": tech.id,
            "name": tech.full_name,
            "username": uname,
            "employee_code": code,
            "tech_role": tech.tech_role,
            "specialty": tech.specialty,
            "add_mode": add_mode,
            "placement_note": placement_note,
            "current_latitude": float(tech.current_latitude),
            "current_longitude": float(tech.current_longitude),
            "rebuild": rebuild,
            "message": f"{full_name} added to {group.name}. {placement_note}." + _rebuild_message(rebuild),
        }, status=201)


class RemoveTechnicianView(APIView):
    """Soft delete: hide the technician but keep their history."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        group = _supervised_group(request)
        if group is None:
            return Response(
                {"error": "This account is not a supervisor of any group."},
                status=403)

        tech = Technician.objects.filter(pk=pk).first()
        if tech is None:
            return Response({"error": "Technician not found."}, status=404)

        # scope: a supervisor can only remove techs in their OWN group
        if tech.group_id != group.id:
            return Response(
                {"error": "You can only remove technicians in your own group."},
                status=403)

        old_role = tech.tech_role
        tech.is_active_employee = False
        tech.save(update_fields=["is_active_employee"])

        rebuild = _maybe_rebuild_future_schedule(group, request, old_role)

        return Response({
            "id": tech.id,
            "name": tech.full_name,
            "is_active_employee": False,
            "rebuild": rebuild,
            "message": f"{tech.full_name} removed from the active roster "
                       f"(history kept)." + _rebuild_message(rebuild),
        })


class ReactivateTechnicianView(APIView):
    """Undo a soft delete: bring a removed technician back onto the roster."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        group = _supervised_group(request)
        if group is None:
            return Response(
                {"error": "This account is not a supervisor of any group."},
                status=403)

        tech = Technician.objects.filter(pk=pk).first()
        if tech is None:
            return Response({"error": "Technician not found."}, status=404)
        if tech.group_id != group.id:
            return Response(
                {"error": "You can only reactivate technicians in your own group."},
                status=403)

        tech.is_active_employee = True
        tech.save(update_fields=["is_active_employee"])

        rebuild = _maybe_rebuild_future_schedule(group, request, tech.tech_role)

        return Response({
            "id": tech.id,
            "name": tech.full_name,
            "is_active_employee": True,
            "rebuild": rebuild,
            "message": f"{tech.full_name} reactivated." + _rebuild_message(rebuild),
        })


# -----------------------------------------------------------------------------
# Add/remove impact preview
# -----------------------------------------------------------------------------
class TechnicianChangeImpactPreviewView(APIView):
    """
    Preview-only endpoint for the supervisor UI.

    It does NOT add/remove technicians and it does NOT rebuild the schedule.
    It uses the currently generated schedule for the logged-in supervisor group
    and estimates what the core workforce metrics would look like if the active
    roster count changed by +1 or -1.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        group = _supervised_group(request)
        if group is None:
            return Response(
                {"error": "This account is not a supervisor of any group."},
                status=403,
            )

        action = (request.data.get("action") or "").strip().upper()
        if action not in {"ADD", "REMOVE"}:
            return Response({"error": "action must be ADD or REMOVE"}, status=400)

        add_mode = (request.data.get("add_mode") or request.data.get("placement_mode") or "NORMAL").strip().upper()
        if add_mode not in {"NORMAL", "BACKLOG"}:
            add_mode = "NORMAL"

        tech = None
        technician_id = request.data.get("technician_id")
        if technician_id:
            tech = Technician.objects.filter(pk=technician_id, group=group).first()
            if tech is None:
                return Response({"error": "Technician not found in this group."}, status=404)
            role = tech.tech_role
            spec = tech.specialty
        else:
            role = (request.data.get("tech_role") or "").strip().upper()
            spec = (request.data.get("specialty") or "").strip().upper()
            if role not in VALID_ROLES:
                return Response({"error": f"tech_role must be one of {sorted(VALID_ROLES)}"}, status=400)
            if spec not in VALID_SPECS:
                return Response({"error": f"specialty must be one of {sorted(VALID_SPECS)}"}, status=400)
            if role == TechnicianRole.CALLBACK:
                spec = SpecialtyType.BOTH

        operation = OperationType.CALLBACK if role == TechnicianRole.CALLBACK else OperationType.MAINTENANCE

        as_of_dt = _parse_as_of(request.data.get("as_of") or request.data.get("active_time"))
        period_start = _period_start_for(as_of_dt)

        backlog = _unassigned_tasks_for(group, operation, limit=50, as_of_dt=as_of_dt, period_start=period_start) if action == "ADD" else []
        backlog_lat, backlog_lng = _backlog_location(backlog)
        backlog_info = _backlog_payload(backlog)

        active_qs = Technician.objects.filter(
            group=group,
            is_active_employee=True,
            tech_role=role,
        )
        current_active = active_qs.count()
        proposed_active = current_active + 1 if action == "ADD" else current_active - 1
        proposed_active = max(1, proposed_active)

        schedules = (
            Schedule.objects
            .filter(
                technician__group=group,
                task__task_type__operation_type=operation,
                start_time__date__gte=period_start,
                start_time__lte=as_of_dt,
            )
            .select_related("task", "task__task_type")
            .order_by("start_time")
        )

        total_jobs = schedules.count()
        dates = set()
        service_hours = 0.0
        travel_minutes = 0
        aa_count = 0
        b_count = 0
        sla_total = 0
        sla_met = 0

        for row in schedules:
            if row.start_time:
                dates.add(row.start_time.date())
            if row.start_time and row.end_time:
                service_hours += (row.end_time - row.start_time).total_seconds() / 3600.0
            travel_minutes += int(row.travel_time_min or 0)

            task = row.task
            priority = (task.priority or "").upper() if task else ""
            if priority == "AA":
                aa_count += 1
            elif priority == "B":
                b_count += 1

            if operation == OperationType.CALLBACK and task:
                sla_target = task.task_type.sla_target_min if task.task_type else None
                release_time = getattr(task, "release_time", None)
                if sla_target and release_time and row.start_time:
                    sla_total += 1
                    delay_min = (row.start_time - release_time).total_seconds() / 60.0
                    if delay_min <= float(sla_target):
                        sla_met += 1

        scheduled_days = max(1, len(dates))
        travel_hours = travel_minutes / 60.0
        duty_hours = service_hours + travel_hours

        # For maintenance, service utilization is the cleaner staffing KPI.
        # For callbacks, duty utilization is more realistic because driving is a
        # large part of emergency response work.
        workload_hours = duty_hours if operation == OperationType.CALLBACK else service_hours
        target_hours_per_tech_period = scheduled_days * 8.0 * 0.90
        if target_hours_per_tech_period <= 0:
            target_hours_per_tech_period = 1.0

        current_util = (workload_hours / (current_active * target_hours_per_tech_period) * 100.0) if current_active else 0.0
        proposed_util = (workload_hours / (proposed_active * target_hours_per_tech_period) * 100.0) if proposed_active else 0.0
        current_service_util = (service_hours / (current_active * scheduled_days * 8.0) * 100.0) if current_active else 0.0
        proposed_service_util = (service_hours / (proposed_active * scheduled_days * 8.0) * 100.0) if proposed_active else 0.0
        current_duty_util = (duty_hours / (current_active * scheduled_days * 8.0) * 100.0) if current_active else 0.0
        proposed_duty_util = (duty_hours / (proposed_active * scheduled_days * 8.0) * 100.0) if proposed_active else 0.0

        recommended = math.ceil(workload_hours / target_hours_per_tech_period) if workload_hours else current_active
        if operation == OperationType.CALLBACK and total_jobs:
            # Callback teams need a live SLA/AA buffer; do not size them purely
            # to 90% utilization. This is preview guidance only.
            emergency_buffer = 2 if aa_count else 1
            recommended += emergency_buffer
        recommended = max(1, recommended)

        # The active-count target must be checked before the raw utilization
        # percentage. Example: for callbacks, removing a technician may push
        # duty utilization close to 100%, but that is not "balanced" if the
        # proposed roster is below the recommended SLA/AA buffer.
        delta_to_recommended_now = proposed_active - recommended
        if delta_to_recommended_now < 0:
            risk = "OVERLOAD"
            risk_label = "SLA buffer risk" if operation == OperationType.CALLBACK else "Below target"
            recommendation = (
                f"Projected roster is {abs(delta_to_recommended_now)} technician(s) below the recommended target. "
                "The remaining technicians may look highly utilized, but spare capacity/buffer is too low."
            )
        elif delta_to_recommended_now > 1:
            risk = "UNDERLOAD"
            risk_label = "Above target"
            recommendation = (
                f"Projected roster is {delta_to_recommended_now} technician(s) above the recommended target. "
                "Utilization may become low after rebuild."
            )
        elif proposed_util >= 105:
            risk = "OVERLOAD"
            risk_label = "Likely overloaded"
            recommendation = "Adding capacity or keeping an extra standby technician is safer before rebuilding."
        elif proposed_util < 60:
            risk = "UNDERLOAD"
            risk_label = "Likely underloaded"
            recommendation = "Roster may be too large for the current generated workload."
        elif 70 <= proposed_util <= 102:
            risk = "BALANCED"
            risk_label = "Balanced"
            recommendation = "Projected workload stays in the preferred range."
        else:
            risk = "WATCH"
            risk_label = "Watch"
            recommendation = "Projected workload is acceptable but not ideal; review after rebuilding."

        if operation == OperationType.CALLBACK:
            jobs_per_tech_day_current = total_jobs / (current_active * scheduled_days) if current_active else 0.0
            jobs_per_tech_day_after = total_jobs / (proposed_active * scheduled_days) if proposed_active else 0.0
            aa_per_tech_day_after = aa_count / (proposed_active * scheduled_days) if proposed_active else 0.0
            if action == "REMOVE" and (jobs_per_tech_day_after > 4.5 or aa_per_tech_day_after > 0.8):
                sla_note = "Removing this technician may hurt callback SLA/AA response buffer."
            elif action == "ADD":
                sla_note = "Adding a callback technician should improve SLA buffer after schedule rebuild."
            else:
                sla_note = "Callback SLA should be rechecked after schedule rebuild."
        else:
            jobs_per_tech_day_current = total_jobs / (current_active * scheduled_days) if current_active else 0.0
            jobs_per_tech_day_after = total_jobs / (proposed_active * scheduled_days) if proposed_active else 0.0
            sla_note = "SLA is not a maintenance KPI; focus on utilization, daily load, and route distance."

        sla_pct = (sla_met / sla_total * 100.0) if sla_total else None
        delta_to_optimal = proposed_active - recommended
        if delta_to_optimal > 0:
            optimal_text = f"After this change, about {delta_to_optimal} technician(s) above the workload-based target."
        elif delta_to_optimal < 0:
            optimal_text = f"After this change, about {abs(delta_to_optimal)} more technician(s) may be needed for the target buffer."
        else:
            optimal_text = "After this change, roster size matches the workload-based target."

        placement_note = "Normal add uses the supervisor group base/current roster location."
        if action == "ADD" and add_mode == "BACKLOG":
            if backlog_info["count"] > 0 and backlog_lat is not None:
                if operation == OperationType.CALLBACK:
                    placement_note = (
                        f"Callback backlog add will place the new technician near the centroid of "
                        f"{backlog_info['count']} unassigned callback task(s)."
                    )
                    if backlog_info["aa_count"] > 0:
                        risk = "OVERLOAD"
                        risk_label = "Urgent callback backlog"
                        recommendation = "AA unassigned callbacks exist. Add near backlog or dispatch immediately, then rebuild callback schedule."
                else:
                    placement_note = (
                        f"Maintenance backlog add will place the new technician near the centroid of "
                        f"{backlog_info['count']} unassigned maintenance task(s)."
                    )
            else:
                if operation == OperationType.CALLBACK:
                    placement_note = "Callback backlog add selected, but no unassigned callback location was found; group base will be used."
                else:
                    placement_note = "Maintenance backlog add selected, but no unassigned maintenance task location was found; group base will be used."

        return Response({
            "scope_start": period_start.isoformat(),
            "scope_end": as_of_dt.isoformat(),
            "scope_label": f"{period_start.isoformat()} → {as_of_dt.date().isoformat()}",
            "action": action,
            "group": group.name,
            "role": role,
            "operation_type": operation,
            "specialty": spec,
            "add_mode": add_mode,
            "placement_note": placement_note,
            "suggested_latitude": round(backlog_lat, 6) if backlog_lat is not None else None,
            "suggested_longitude": round(backlog_lng, 6) if backlog_lng is not None else None,
            "unassigned_count": backlog_info["count"],
            "unassigned_aa_count": backlog_info["aa_count"],
            "unassigned_b_count": backlog_info["b_count"],
            "unassigned_tasks": backlog_info["tasks"],
            "current_active": current_active,
            "proposed_active": proposed_active,
            "recommended_active": recommended,
            "delta_to_optimal": delta_to_optimal,
            "optimal_text": optimal_text,
            "scheduled_days": scheduled_days,
            "jobs": total_jobs,
            "service_hours": round(service_hours, 1),
            "travel_hours": round(travel_hours, 1),
            "duty_hours": round(duty_hours, 1),
            "current_utilization_pct": round(current_util, 1),
            "projected_utilization_pct": round(proposed_util, 1),
            "current_service_utilization_pct": round(current_service_util, 1),
            "projected_service_utilization_pct": round(proposed_service_util, 1),
            "current_duty_utilization_pct": round(current_duty_util, 1),
            "projected_duty_utilization_pct": round(proposed_duty_util, 1),
            "jobs_per_tech_day_current": round(jobs_per_tech_day_current, 2),
            "jobs_per_tech_day_after": round(jobs_per_tech_day_after, 2),
            "aa_count": aa_count,
            "b_count": b_count,
            "sla_met": sla_met,
            "sla_total": sla_total,
            "sla_pct": round(sla_pct, 1) if sla_pct is not None else None,
            "sla_note": sla_note,
            "risk": risk,
            "risk_label": risk_label,
            "recommendation": recommendation,
            "note": "Preview only. The database is changed only if the supervisor confirms Add/Remove.",
        })
