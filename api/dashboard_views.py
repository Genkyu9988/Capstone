"""
api/dashboard_views.py
=============================================================================
GET /api/dashboard/state/   (scoped to the LOGGED-IN supervisor's group)

Live Map data for the active day (operating clock, api/active_day):
  * planned stops per technician,
  * a traffic-aware timeline (arrival/depart per stop),
  * a POSITION (gps if a phone reports, else estimated along the route + clock),
  * REAL GOOGLE ROAD GEOMETRY for the first N technicians (cost-capped), so
    their route line follows actual streets and their estimated dot moves
    along the road. Everyone else uses free straight lines.

COST CONTROL (the 5-6-per-supervisor decision):
  * Only the first LIVE_MAP_ROAD_TECH_LIMIT technicians (default 6) get a
    Google call, and it's keyed on their STOPS (stable all day) -> at most N
    computeRoutes calls the first time, 0 on every poll after (disk cache).
  * route_geometry.py enforces GOOGLE_MAPS_DAILY_LIMIT and falls back to
    straight legs if Google is off / capped / errors. Never bills past the cap.
=============================================================================
"""
from datetime import datetime, timedelta, time
from math import radians, sin, cos, asin, sqrt

from django.conf import settings
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Schedule, Technician
from api.active_day import get_active_date, get_active_datetime
from api.services.maps.route_geometry import build_route_geometry

# ----- travel model ---------------------------------------------------------
ROAD_FACTOR = 1.35
MEDIUM_TRAFFIC_KMH = 22.0
DEFAULT_SERVICE_MIN = 30
DAY_START_HOUR = 9
LIVE_WINDOW_SEC = 120
# how many technicians per supervisor get real Google road geometry
ROAD_TECH_LIMIT = getattr(settings, "LIVE_MAP_ROAD_TECH_LIMIT", 6)


def _haversine_km(lat1, lng1, lat2, lng2):
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(a))


def _travel_min(a, b):
    km = _haversine_km(a[0], a[1], b[0], b[1]) * ROAD_FACTOR
    return (km / MEDIUM_TRAFFIC_KMH) * 60.0


def _build_timeline(stops, start, day_start):
    timeline = []
    pos = start
    t = day_start
    for s in stops:
        node = (s["latitude"], s["longitude"])
        tr = _travel_min(pos, node) if pos is not None else 0.0
        arrival = t + timedelta(minutes=tr)
        depart = arrival + timedelta(minutes=(s.get("duration_min") or DEFAULT_SERVICE_MIN))
        timeline.append((arrival, depart))
        pos = node
        t = depart
    return timeline


# ---- straight-line position (free techs) -----------------------------------
def _position_at(stops, start, timeline, day_start, now):
    if not stops:
        return start
    if start is None:
        start = (stops[0]["latitude"], stops[0]["longitude"])
    if now <= day_start:
        return start
    prev = start
    prev_time = day_start
    for i, s in enumerate(stops):
        arrival, depart = timeline[i]
        node = (s["latitude"], s["longitude"])
        if prev_time <= now < arrival:
            span = (arrival - prev_time).total_seconds()
            frac = (now - prev_time).total_seconds() / span if span > 0 else 1.0
            return (prev[0] + (node[0] - prev[0]) * frac,
                    prev[1] + (node[1] - prev[1]) * frac)
        if arrival <= now < depart:
            return node
        prev = node
        prev_time = depart
    return prev


# ---- road-snapped position (the road techs) --------------------------------
def _cumulative(poly):
    cum = [0.0]
    for i in range(1, len(poly)):
        cum.append(cum[-1] + _haversine_km(poly[i - 1][0], poly[i - 1][1], poly[i][0], poly[i][1]))
    return cum


def _point_at_distance(poly, cum, d):
    if d <= 0:
        return poly[0]
    if d >= cum[-1]:
        return poly[-1]
    for i in range(1, len(cum)):
        if cum[i] >= d:
            seg = cum[i] - cum[i - 1]
            t = (d - cum[i - 1]) / seg if seg > 0 else 0.0
            a, b = poly[i - 1], poly[i]
            return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
    return poly[-1]


def _nearest_cum(poly, cum, lat, lng):
    best_d, best_c = 1e18, 0.0
    for i, p in enumerate(poly):
        dd = _haversine_km(p[0], p[1], lat, lng)
        if dd < best_d:
            best_d, best_c = dd, cum[i]
    return best_c


def _road_position_at(poly, stops, timeline, day_start, now):
    """Move the dot ALONG the road polyline, synced to the stop timeline."""
    if not poly or not stops:
        return (poly[0][0], poly[0][1]) if poly else None
    cum = _cumulative(poly)
    if now <= day_start:
        return (poly[0][0], poly[0][1])
    stop_cum = [_nearest_cum(poly, cum, s["latitude"], s["longitude"]) for s in stops]
    prev_cum = 0.0
    prev_time = day_start
    for i in range(len(stops)):
        arrival, depart = timeline[i]
        target_cum = stop_cum[i]
        if prev_time <= now < arrival:           # traveling toward stop i
            span = (arrival - prev_time).total_seconds()
            frac = (now - prev_time).total_seconds() / span if span > 0 else 1.0
            p = _point_at_distance(poly, cum, prev_cum + (target_cum - prev_cum) * frac)
            return (p[0], p[1])
        if arrival <= now < depart:              # at stop i
            p = _point_at_distance(poly, cum, target_cum)
            return (p[0], p[1])
        prev_cum = target_cum
        prev_time = depart
    return (poly[-1][0], poly[-1][1])


class DemoDashboardStateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        group = getattr(request.user, "supervised_group", None)
        if group is None:
            return Response(
                {"error": "This account is not a supervisor of any group."},
                status=403,
            )

        active_day = get_active_date(request)
        active_now = get_active_datetime(request)
        real_now = timezone.now()
        day_start = timezone.make_aware(datetime.combine(active_day, time(DAY_START_HOUR, 0)))

        techs = (
            Technician.objects
            .filter(is_active_employee=True, group=group)
            .select_related("user", "group")
            .order_by("full_name")
        )

        result = []
        road_used = 0          # how many Google-road technicians we've spent
        for t in techs:
            schedules = list(
                Schedule.objects
                .filter(technician=t, start_time__date=active_day)   # ONE DAY
                .select_related("task", "task__unit", "task__task_type")
                .order_by("sequence_order")
            )

            stops = [{
                "stop_number": s.sequence_order,
                "task_no": s.task.task_no,
                "task_type": s.task.task_type.name if s.task.task_type else "",
                "priority": s.task.priority or "NORMAL",
                "unit_name": s.task.unit.unit_name,
                "latitude": float(s.task.unit.latitude),
                "longitude": float(s.task.unit.longitude),
                "duration_min": s.task.estimated_duration_min,
            } for s in schedules]

            start = None
            if t.current_latitude is not None and t.current_longitude is not None:
                start = (float(t.current_latitude), float(t.current_longitude))

            timeline = _build_timeline(stops, start, day_start)

            # per-stop state + eta + the stop they're heading to
            next_idx = None
            for i, s in enumerate(stops):
                arrival, depart = timeline[i]
                if active_now > depart:
                    s["state"] = "done"
                elif arrival <= active_now <= depart:
                    s["state"] = "current"
                else:
                    s["state"] = "upcoming"
                s["eta"] = arrival.isoformat()
                if next_idx is None and active_now < depart:
                    next_idx = i
            next_stop = stops[next_idx] if next_idx is not None else None

            # ---- real Google road geometry for the first N techs with stops -- #
            route_polyline = None
            geometry_source = None
            if stops and road_used < ROAD_TECH_LIMIT:
                # keyed on the STOPS (stable all day) -> cache-stable, <=N calls
                depot_geom = (stops[0]["latitude"], stops[0]["longitude"])
                rest = [{"lat": s["latitude"], "lng": s["longitude"]} for s in stops[1:]]
                geom = build_route_geometry(depot_geom, rest)
                route_polyline = geom.get("points")
                geometry_source = geom.get("source")
                road_used += 1

            # ---- position --------------------------------------------------- #
            is_live = (
                t.last_location_at is not None
                and (real_now - t.last_location_at).total_seconds() <= LIVE_WINDOW_SEC
            )
            if is_live and start is not None:
                display_lat, display_lng = start                 # measured GPS
                position_source = "gps"
            elif route_polyline and len(route_polyline) >= 2:
                pos = _road_position_at(route_polyline, stops, timeline, day_start, active_now)
                display_lat = pos[0] if pos else None
                display_lng = pos[1] if pos else None
                position_source = "estimated_road"
            else:
                pos = _position_at(stops, start, timeline, day_start, active_now)
                display_lat = pos[0] if pos else None
                display_lng = pos[1] if pos else None
                position_source = "estimated"

            on_leave = not t.is_available
            if on_leave:
                status_label = "onLeave"
            elif not stops:
                status_label = "available"
            elif next_stop is None:
                status_label = "done"
            elif next_stop["state"] == "current":
                status_label = "onSite"
            else:
                status_label = "enRoute"

            result.append({
                "id": t.id,
                "username": t.user.username if t.user else None,
                "name": t.full_name,
                "tech_role": t.tech_role,
                "specialty": t.specialty,
                "on_leave": on_leave,
                "current_latitude": float(t.current_latitude) if t.current_latitude is not None else None,
                "current_longitude": float(t.current_longitude) if t.current_longitude is not None else None,
                "display_latitude": display_lat,
                "display_longitude": display_lng,
                "position_source": position_source,
                "is_live": is_live,
                "route_polyline": route_polyline,      # [[lat,lng],...] real road, or None
                "geometry_source": geometry_source,    # GOOGLE_ROADS / CACHE / STRAIGHT_* / None
                "stop_count": len(stops),
                "stops": stops,
                "status": status_label,
                "next_stop_number": next_stop["stop_number"] if next_stop else None,
                "next_unit_name": next_stop["unit_name"] if next_stop else None,
                "next_latitude": next_stop["latitude"] if next_stop else None,
                "next_longitude": next_stop["longitude"] if next_stop else None,
            })

        return Response({
            "technicians": result,
            "group": group.name,
            "active_date": active_day.isoformat(),
            "active_time": active_now.isoformat(),
            "road_techs_shown": road_used,
            "fetched_at": real_now.isoformat(),
        })
