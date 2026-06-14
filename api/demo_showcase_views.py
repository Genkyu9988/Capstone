"""
api/demo_showcase_views.py
=============================================================================
GET /api/demo/showcase-routes/

Reads the Ahmet Yilmaz group's EXISTING month schedule (already solved by
`solve_group "Ahmet Yilmaz Group"`), picks ONE day, and renders only a limited
number of technicians on the map -- so the paid Google calls stay tiny.

Query params (all optional):
    group  : substring of the SupervisorGroup name   (default "Ahmet")
    date   : YYYY-MM-DD                               (default: busiest day)
    limit  : how many technicians to show             (default 5)

Cost model:
    * Stop ORDER for each shown tech: free (Gurobi haversine TSP, routing.py).
    * Road GEOMETRY for each shown tech: at most ONE Google computeRoutes call,
      then cached forever (route_geometry.py). Unselected techs = 0 calls.

So showing 5 technicians costs <= 5 Google calls the first time, 0 after that.
=============================================================================
"""
from collections import defaultdict
from datetime import datetime

from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Schedule
from .services.optimization.routing import optimal_open_route
from .services.maps.route_geometry import build_route_geometry

DEFAULT_GROUP = "Ahmet"     # icontains match -> "Ahmet Yilmaz Group"
DEFAULT_LIMIT = 5
DEFAULT_MAX_STOPS = 8       # stops per shown technician (realistic day + under Google's waypoint cap)
DEFAULT_DEPOT = (41.0082, 28.9784)  # Istanbul centre, used if a tech has no home pin


def _depot(tech):
    lat = float(tech.current_latitude) if tech.current_latitude is not None else DEFAULT_DEPOT[0]
    lng = float(tech.current_longitude) if tech.current_longitude is not None else DEFAULT_DEPOT[1]
    return (lat, lng)


class ShowcaseRoutesView(APIView):
    permission_classes = [AllowAny]  # demo endpoint; tighten before production

    def get(self, request):
        group_q = request.query_params.get("group", DEFAULT_GROUP)
        date_str = request.query_params.get("date")
        try:
            limit = max(1, int(request.query_params.get("limit", DEFAULT_LIMIT)))
        except (TypeError, ValueError):
            limit = DEFAULT_LIMIT
        try:
            # Cap stops per technician: keeps each route a realistic daily route
            # AND under Google computeRoutes' waypoint limit (~25). 0 = no cap.
            max_stops = int(request.query_params.get("max_stops", DEFAULT_MAX_STOPS))
        except (TypeError, ValueError):
            max_stops = DEFAULT_MAX_STOPS

        schedules = list(
            Schedule.objects.filter(technician__group__name__icontains=group_q)
            .select_related("technician", "task", "task__unit", "task__task_type")
        )
        if not schedules:
            return Response(
                {"error": f"No schedules found for a group matching '{group_q}'. "
                          f"Run solve_group first."},
                status=404,
            )

        # ---- pick the day -------------------------------------------------- #
        by_day = defaultdict(list)
        for s in schedules:
            if s.start_time:
                by_day[s.start_time.date()].append(s)

        if not by_day:
            return Response({"error": "Schedules exist but have no start_time set."}, status=400)

        if date_str:
            try:
                chosen_day = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                return Response({"error": "date must be YYYY-MM-DD."}, status=400)
            day_schedules = by_day.get(chosen_day, [])
            if not day_schedules:
                return Response(
                    {"error": f"No schedules on {chosen_day} for '{group_q}'.",
                     "available_days": sorted(d.isoformat() for d in by_day)},
                    status=404,
                )
        else:
            chosen_day, day_schedules = max(by_day.items(), key=lambda kv: len(kv[1]))

        # ---- group that day's stops by technician, rank by stop count ------ #
        by_tech = defaultdict(list)
        for s in day_schedules:
            by_tech[s.technician].append(s)

        ranked = sorted(by_tech.items(), key=lambda kv: len(kv[1]), reverse=True)
        selected = ranked[:limit]

        # ---- build routes for the selected few ----------------------------- #
        routes = []
        google_calls = 0
        for tech, tech_scheds in selected:
            depot = _depot(tech)
            stops = [{
                "lat": float(s.task.unit.latitude),
                "lng": float(s.task.unit.longitude),
                "is_aa": (s.task.priority or "").upper() == "AA",
                "unit_name": s.task.unit.unit_name,
                "task_no": s.task.task_no,
                "task_type": s.task.task_type.name,
                "duration_min": s.task.estimated_duration_min,
                "start_time": s.start_time.isoformat() if s.start_time else None,
            } for s in tech_scheds]

            # FREE: optimal visit order (AA first), haversine Gurobi TSP
            ordered, plan_km = optimal_open_route(depot, stops)

            # Cap to a realistic daily route (also keeps us under Google's
            # computeRoutes waypoint limit). AA stops are first, so they survive.
            if max_stops > 0 and len(ordered) > max_stops:
                ordered = ordered[:max_stops]

            # Road geometry (real if Google on + under cap, else straight legs)
            geom = build_route_geometry(depot, ordered)
            if geom["source"] == "GOOGLE_ROADS":
                google_calls += 1

            routes.append({
                "technician_id": tech.id,
                "technician_name": tech.full_name,
                "tech_role": tech.tech_role,
                "specialty": tech.specialty,
                "depot": {"lat": depot[0], "lng": depot[1]},
                "stop_count": len(ordered),
                "has_aa": any(s["is_aa"] for s in ordered),
                "planned_km_haversine": round(plan_km, 2),
                "road_distance_km": geom["distance_km"],
                "road_duration_min": geom["duration_min"],
                "geometry_source": geom["source"],
                "polyline": geom["points"],  # [[lat,lng], ...] -> the drawable path
                "stops": [{
                    "sequence": i + 1,
                    "task_no": s["task_no"],
                    "task_type": s["task_type"],
                    "unit_name": s["unit_name"],
                    "lat": s["lat"],
                    "lng": s["lng"],
                    "is_aa": s["is_aa"],
                    "duration_min": s["duration_min"],
                } for i, s in enumerate(ordered)],
            })

        return Response({
            "group": group_q,
            "date": chosen_day.isoformat(),
            "limit": limit,
            "max_stops": max_stops,
            "technicians_available_that_day": len(by_tech),
            "technicians_shown": len(routes),
            "google_calls_this_request": google_calls,
            "note": (
                "Only the shown technicians can consume Google calls; the rest of "
                "the fleet is intentionally omitted. Each shown route is one "
                "computeRoutes call at most, then cached (0 calls on refresh)."
            ),
            "routes": routes,
            "fetched_at": timezone.now().isoformat(),
        })
