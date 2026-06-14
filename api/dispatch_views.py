"""
api/dispatch_views.py   (GUROBI DISPATCH VERSION)
=============================================================================
POST /api/dispatch-task/    Supervisor creates a fault. We:
    1. filter eligible technicians (role + specialty + SAME REGION)
    2. for each candidate, use the Gurobi route solver to measure how much
       extra travel the new stop adds to their day (cheapest-insertion)
    3. assign to the technician whose route grows the least
    4. re-solve that technician's whole route (AA forced to the front) and
       rewrite their schedule so the map polyline reshapes
    -> returns who won and the per-candidate scoreboard.

GET  /api/dashboard/state/  All active technicians + their current routes.

Region is derived from longitude (Bosphorus ~29.02E), matching seed_demo_fleet.
=============================================================================
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    PlanningPeriod, Schedule, Task, TaskStatus, TaskType, Technician, Unit,
)
from .services.maps.distance_service import haversine_distance_km
from .services.optimization.routing import optimal_open_route

REGION_THRESHOLD = 29.02


def region_of(lng):
    return "ASIA" if float(lng) >= REGION_THRESHOLD else "EUROPE"


# fault_type -> what kind of task / technician we need + the priority it implies.
# Priority is a property of the fault type (an entrapment is always an emergency),
# so the supervisor no longer chooses it separately.
FAULT_PROFILES = {
    "Entrapment":  dict(role="CALLBACK",      specialty="ELEVATOR",  unit_type="ELEVATOR",  op="CALLBACK",    tt_code="ELEV-CALL", duration=60, priority="AA"),
    "Motor Jam":   dict(role="CALLBACK",      specialty="ELEVATOR",  unit_type="ELEVATOR",  op="CALLBACK",    tt_code="ELEV-CALL", duration=90, priority="NORMAL"),
    "Door Sensor": dict(role="CALLBACK",      specialty="ELEVATOR",  unit_type="ELEVATOR",  op="CALLBACK",    tt_code="ELEV-CALL", duration=45, priority="NORMAL"),
    "Routine":     dict(role="MAINTENANCE", specialty="ESCALATOR", unit_type="ESCALATOR", op="MAINTENANCE", tt_code="ESC-MAINT", duration=45, priority="NORMAL"),
    "Other":       dict(role="CALLBACK",      specialty="ELEVATOR",  unit_type="ELEVATOR",  op="CALLBACK",    tt_code="ELEV-CALL", duration=60, priority="NORMAL"),
}


def _depot(tech):
    return (
        float(tech.current_latitude) if tech.current_latitude is not None else 41.0082,
        float(tech.current_longitude) if tech.current_longitude is not None else 28.9784,
    )


def _current_tasks(tech):
    return [
        s.task
        for s in Schedule.objects.filter(technician=tech)
        .select_related("task", "task__unit")
        .order_by("sequence_order")
    ]


def _stops_from_tasks(tasks):
    return [{
        "id": t.id,
        "lat": float(t.unit.latitude),
        "lng": float(t.unit.longitude),
        "is_aa": (t.priority or "").upper() == "AA",
        "payload": t,
    } for t in tasks]


def _rewrite_route(tech, tasks):
    """Re-solve the technician's route over `tasks` and rewrite Schedule rows."""
    depot = _depot(tech)
    ordered, _km = optimal_open_route(depot, _stops_from_tasks(tasks))
    Schedule.objects.filter(technician=tech).delete()
    start = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
    for seq, s in enumerate(ordered, start=1):
        task = s["payload"]
        end = start + timedelta(minutes=task.estimated_duration_min)
        Schedule.objects.create(
            task=task, technician=tech, start_time=start, end_time=end,
            sequence_order=seq, source="DISPATCH",
        )
        start = end + timedelta(minutes=15)
    return ordered


def _eligible_for_task(task, exclude_tech_id):
    """Available technicians who can do this task (skill + region), minus one."""
    tt = task.task_type
    req_role = tt.required_technician_role
    req_spec = tt.required_specialty
    task_region = region_of(task.unit.longitude)
    out = []
    for t in (Technician.objects
              .filter(is_active_employee=True, is_available=True)
              .exclude(id=exclude_tech_id)
              .select_related("user")):
        role_ok = t.tech_role == req_role
        spec_ok = t.specialty in (req_spec, "BOTH")
        region_ok = region_of(t.current_longitude if t.current_longitude is not None else 28.97) == task_region
        if role_ok and spec_ok and region_ok:
            out.append(t)
    return out


def reassign_technician_tasks(leaving_tech):
    """
    Redistribute a leaving technician's tasks to the best eligible remaining
    technicians (Gurobi cheapest-insertion), then empty the leaving tech's
    route. Returns a per-task summary for logging / the API response.
    """
    orphan_tasks = _current_tasks(leaving_tech)
    # Empty the leaving technician's route first so there's no double-booking.
    Schedule.objects.filter(technician=leaving_tech).delete()

    summary = []
    for task in orphan_tasks:
        candidates = _eligible_for_task(task, exclude_tech_id=leaving_tech.id)
        if not candidates:
            summary.append({"task": task.task_no, "assigned_to": None, "added_km": None})
            print(f"[REASSIGN] {task.task_no}: no eligible technician left -> unserved")
            continue

        is_aa = (task.priority or "").upper() == "AA"
        new_stop = {
            "id": task.id, "lat": float(task.unit.latitude),
            "lng": float(task.unit.longitude), "is_aa": is_aa, "payload": None,
        }
        best = None
        for cand in candidates:
            depot = _depot(cand)
            cur = _current_tasks(cand)
            cur_stops = _stops_from_tasks(cur)
            _, cur_km = optimal_open_route(depot, cur_stops)
            _, new_km = optimal_open_route(depot, cur_stops + [new_stop])
            added = max(new_km - cur_km, 0.0)
            if best is None or added < best[1]:
                best = (cand, added, cur)

        winner, added, winner_tasks = best
        _rewrite_route(winner, winner_tasks + [task])
        summary.append({"task": task.task_no, "assigned_to": winner.full_name, "added_km": round(added, 2)})
        print(f"[REASSIGN] {task.task_no} -> {winner.full_name} (+{added:.2f} km)")

    return summary


class DispatchTaskView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        # 1. Parse
        try:
            lat = float(request.data.get("latitude"))
            lng = float(request.data.get("longitude"))
        except (TypeError, ValueError):
            return Response({"error": "latitude/longitude required"}, status=400)
        fault_type = request.data.get("fault_type") or "Other"
        description = request.data.get("description") or ""
        profile = FAULT_PROFILES.get(fault_type, FAULT_PROFILES["Other"])
        priority = profile["priority"]          # derived from fault type, not the supervisor
        fault_region = region_of(lng)
        is_aa = priority == "AA"

        # 2. Active planning period
        today = timezone.now().date()
        period = (
            PlanningPeriod.objects.filter(start_date__lte=today, end_date__gte=today, is_active=True).first()
            or PlanningPeriod.objects.filter(is_active=True).order_by("-start_date").first()
        )
        if not period:
            return Response({"error": "No active PlanningPeriod. Seed first."}, status=400)

        task_type = TaskType.objects.filter(code=profile["tt_code"]).first()
        if not task_type:
            return Response({"error": f"TaskType {profile['tt_code']} not found. Run seed_demo_fleet.py."}, status=400)

        # 3. Eligible technicians: skill + region
        eligible = [
            t for t in Technician.objects.filter(is_active_employee=True, is_available=True).select_related("user")
            if t.tech_role == profile["role"]
            and t.specialty in (profile["specialty"], "BOTH")
            and region_of(t.current_longitude if t.current_longitude is not None else 28.97) == fault_region
        ]
        if not eligible:
            return Response(
                {"error": f"No eligible technician in region {fault_region}", "rules": profile},
                status=400,
            )

        # 4. Cheapest-insertion: for each candidate, Gurobi-route their day with
        #    the new stop and measure the added travel.
        new_stop = {"id": -1, "lat": lat, "lng": lng, "is_aa": is_aa, "payload": None}
        scoreboard = []
        best = None
        for tech in eligible:
            depot = _depot(tech)
            cur_tasks = _current_tasks(tech)
            cur_stops = _stops_from_tasks(cur_tasks)
            _, cur_km = optimal_open_route(depot, cur_stops)
            _, new_km = optimal_open_route(depot, cur_stops + [new_stop])
            added = max(new_km - cur_km, 0.0)
            scoreboard.append((tech, added, cur_tasks))
            if best is None or added < best[1]:
                best = (tech, added, cur_tasks)

        chosen, chosen_added, chosen_tasks = best
        print(f"[DISPATCH] {fault_type}/{priority} @({lat:.3f},{lng:.3f}) region={fault_region}")
        for tech, added, _ in scoreboard:
            mark = "  <-- chosen" if tech.id == chosen.id else ""
            print(f"   {tech.full_name:18s} +{added:6.2f} km{mark}")

        # 5. Create the unit + task
        unit = self._find_or_create_unit(lat, lng, profile["unit_type"])
        task = Task.objects.create(
            task_no=f"DISP-{int(timezone.now().timestamp())}",
            unit=unit, task_type=task_type, planning_period=period,
            created_by=request.user,
            description=description or f"{fault_type} dispatched via dashboard",
            priority=("AA" if is_aa else "B") if profile["op"] == "CALLBACK" else None,
            estimated_duration_min=profile["duration"],
            status=TaskStatus.ASSIGNED, is_active=True,
        )

        # 6. Re-solve the winner's route WITH the new task -> reshapes the map
        _rewrite_route(chosen, chosen_tasks + [task])

        return Response({
            "assigned_to": {
                "id": chosen.id, "name": chosen.full_name,
                "username": chosen.user.username if chosen.user else None,
                "tech_role": chosen.tech_role, "specialty": chosen.specialty,
            },
            "task": {
                "id": task.id, "task_no": task.task_no, "priority": task.priority or "NORMAL",
                "estimated_duration_min": task.estimated_duration_min,
                "unit": {"name": unit.unit_name, "latitude": float(unit.latitude), "longitude": float(unit.longitude)},
            },
            "reason": (
                f"Region {fault_region}: {len(eligible)} eligible technician(s). "
                f"Gurobi re-routed each candidate's day; {chosen.full_name} had the "
                f"smallest added travel (+{chosen_added:.2f} km)."
                + (" AA emergency placed first in the route." if is_aa else "")
            ),
            "scoreboard": [
                {"name": t.full_name, "km_from_dispatch": round(added, 2)}
                for (t, added, _) in sorted(scoreboard, key=lambda r: r[1])
            ],
        }, status=status.HTTP_201_CREATED)

    def _find_or_create_unit(self, lat, lng, unit_type):
        for u in Unit.objects.filter(unit_type=unit_type, is_active=True):
            if haversine_distance_km(u.latitude, u.longitude, lat, lng) < 0.05:
                return u
        return Unit.objects.create(
            unit_code=f"DISP-U-{int(timezone.now().timestamp())}",
            unit_name=f"Dispatched {unit_type.lower()} ({lat:.4f}, {lng:.4f})",
            unit_type=unit_type, address=f"({lat:.4f}, {lng:.4f})",
            latitude=lat, longitude=lng, notes=f"Region: {region_of(lng)}",
        )


class DashboardStateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        techs = (
            Technician.objects.filter(is_active_employee=True)
            .select_related("user")
        )
        result = []
        for t in techs:
            schedules = list(
                Schedule.objects.filter(technician=t)
                .select_related("task", "task__unit", "task__task_type")
                .order_by("sequence_order")
            )
            stops = [{
                "stop_number": s.sequence_order,
                "task_no": s.task.task_no,
                "task_type": s.task.task_type.name,
                "priority": s.task.priority or "NORMAL",
                "unit_name": s.task.unit.unit_name,
                "latitude": float(s.task.unit.latitude),
                "longitude": float(s.task.unit.longitude),
                "start_time": s.start_time.isoformat() if s.start_time else None,
                "duration_min": s.task.estimated_duration_min,
            } for s in schedules]

            has_aa = any(s["priority"] == "AA" for s in stops)
            on_leave = not t.is_available
            status_label = "onLeave" if on_leave else ("available" if not stops else ("enRoute" if has_aa else "onSite"))

            result.append({
                "id": t.id,
                "username": t.user.username if t.user else None,
                "name": t.full_name,
                "tech_role": t.tech_role,
                "specialty": t.specialty,
                "on_leave": on_leave,
                "current_latitude": float(t.current_latitude) if t.current_latitude is not None else None,
                "current_longitude": float(t.current_longitude) if t.current_longitude is not None else None,
                "stop_count": len(stops),
                "stops": stops,
                "status": status_label,
            })

        return Response({"technicians": result, "fetched_at": timezone.now().isoformat()})
