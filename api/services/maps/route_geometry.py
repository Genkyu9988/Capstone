"""
api/services/maps/route_geometry.py
=============================================================================
DRAWABLE ROUTE GEOMETRY for the demo map (the "moving pin" layer).

This is the ONLY place in the project that calls Google Routes computeRoutes,
so the daily cap enforced here guarantees the showcase can never exceed a tiny
number of paid calls per day.

For one ordered route (depot -> stop1 -> ... -> stopN):

  * If GOOGLE_MAPS_ENABLED is True AND we are under the daily cap:
        - call computeRoutes ONCE -> real road polyline (curved, follows streets)
        - decode it to [[lat, lng], ...] points
        - cache it on disk keyed by the ordered coordinates, so the SAME route
          never costs a second call (refreshes, re-demos, re-solves = free).
  * Otherwise (Google off, cap hit, or any error):
        - fall back to straight legs between depot and stops + a haversine
          distance estimate. Zero cost, never breaks.

Because every selected technician = exactly ONE computeRoutes call (then cached),
showing 5 technicians costs at most 5 calls the first time and 0 thereafter.

Does NOT touch google_maps.py (your matrix call) — fully self-contained.
=============================================================================
"""
import os
import json
import hashlib
import datetime
from math import radians, sin, cos, sqrt, atan2

import requests
from django.conf import settings

COMPUTE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# Hard ceiling on computeRoutes calls per calendar day. Override in settings.py
# with GOOGLE_MAPS_DAILY_LIMIT. Showing N technicians needs at most N calls/day
# (then cached forever), so even a small cap is plenty.
DAILY_CAP = getattr(settings, "GOOGLE_MAPS_DAILY_LIMIT", 50)


# --------------------------------------------------------------------------- #
# On-disk cache + daily counter (no DB migration needed)
# --------------------------------------------------------------------------- #
def _cache_dir():
    base = getattr(settings, "BASE_DIR", None)
    d = os.path.join(str(base), ".route_geometry_cache") if base else ".route_geometry_cache"
    os.makedirs(d, exist_ok=True)
    return d


def _poly_cache_path():
    return os.path.join(_cache_dir(), "polylines.json")


def _counter_path():
    return os.path.join(_cache_dir(), "daily_calls.json")


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as exc:  # cache failure must never break a request
        print(f"[route_geometry] cache write failed: {exc}")


def _calls_today():
    data = _load_json(_counter_path())
    today = datetime.date.today().isoformat()
    return int(data.get(today, 0)) if data.get("day") == today else 0


def _increment_today():
    today = datetime.date.today().isoformat()
    data = _load_json(_counter_path())
    count = int(data.get(today, 0)) if data.get("day") == today else 0
    _save_json(_counter_path(), {"day": today, today: count + 1})


def _route_key(coords):
    raw = ";".join(f"{lat:.5f},{lng:.5f}" for lat, lng in coords)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #
def _haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    lat1, lng1, lat2, lng2 = map(radians, [float(lat1), float(lng1), float(lat2), float(lng2)])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return r * 2 * atan2(sqrt(a), sqrt(1 - a))


def decode_polyline(encoded):
    """Decode a Google encoded polyline string into [[lat, lng], ...]."""
    points, index, lat, lng = [], 0, 0, 0
    length = len(encoded)
    while index < length:
        for is_lat in (True, False):
            shift, result = 0, 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if (result & 1) else (result >> 1)
            if is_lat:
                lat += delta
            else:
                lng += delta
        points.append([lat / 1e5, lng / 1e5])
    return points


def _straight_geometry(coords, source="STRAIGHT_MOCK"):
    """Straight legs between consecutive coords + haversine*1.35 road estimate."""
    total_km = sum(
        _haversine_km(coords[i - 1][0], coords[i - 1][1], coords[i][0], coords[i][1])
        for i in range(1, len(coords))
    )
    road_km = total_km * 1.35
    return {
        "points": [[float(lat), float(lng)] for lat, lng in coords],
        "distance_km": round(road_km, 2),
        "duration_min": int(road_km / 30 * 60),  # ~30 km/h urban
        "source": source,
    }


# --------------------------------------------------------------------------- #
# Google computeRoutes (the single paid call, capped + cached)
# --------------------------------------------------------------------------- #
def _call_compute_routes(coords):
    """One computeRoutes call for depot -> stops (order preserved). Increments
    the daily counter BEFORE the request so a failure still consumes a slot."""
    if not settings.GOOGLE_MAPS_API_KEY:
        raise ValueError("GOOGLE_MAPS_API_KEY is not set.")

    origin = coords[0]
    destination = coords[-1]
    intermediates = coords[1:-1]

    def waypoint(c):
        return {"location": {"latLng": {"latitude": float(c[0]), "longitude": float(c[1])}}}

    body = {
        "origin": waypoint(origin),
        "destination": waypoint(destination),
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "polylineQuality": "OVERVIEW",
        "optimizeWaypointOrder": False,  # Gurobi already chose the order
    }
    if intermediates:
        body["intermediates"] = [waypoint(c) for c in intermediates]

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline",
    }

    _increment_today()  # count before sending
    resp = requests.post(COMPUTE_ROUTES_URL, json=body, headers=headers, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    routes = data.get("routes") or []
    if not routes:
        raise ValueError(f"computeRoutes returned no routes: {data}")

    route = routes[0]
    encoded = (route.get("polyline") or {}).get("encodedPolyline")
    if not encoded:
        raise ValueError("computeRoutes returned no polyline.")

    points = decode_polyline(encoded)
    distance_km = round((route.get("distanceMeters") or 0) / 1000.0, 2)
    duration_str = route.get("duration") or "0s"
    duration_min = int(int(str(duration_str).replace("s", "")) / 60)

    return {"points": points, "distance_km": distance_km, "duration_min": duration_min}


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def build_route_geometry(depot, ordered_stops):
    """
    depot: (lat, lng). ordered_stops: list of dicts with 'lat'/'lng' (already
    ordered by Gurobi). Returns:
        {points: [[lat,lng],...], distance_km, duration_min, source}
    where source is GOOGLE_ROADS | CACHE | STRAIGHT_MOCK | STRAIGHT_CAP |
    STRAIGHT_ERROR | EMPTY.
    """
    coords = [(float(depot[0]), float(depot[1]))] + [
        (float(s["lat"]), float(s["lng"])) for s in ordered_stops
    ]

    if len(coords) < 2:
        return {"points": [[coords[0][0], coords[0][1]]] if coords else [],
                "distance_km": 0.0, "duration_min": 0, "source": "EMPTY"}

    key = _route_key(coords)
    cache = _load_json(_poly_cache_path())
    if key in cache:
        cached = cache[key]
        return {**cached, "source": "CACHE"}

    if not getattr(settings, "GOOGLE_MAPS_ENABLED", False):
        return _straight_geometry(coords, source="STRAIGHT_MOCK")

    if _calls_today() >= DAILY_CAP:
        print(f"[route_geometry] daily cap ({DAILY_CAP}) reached -> straight legs.")
        return _straight_geometry(coords, source="STRAIGHT_CAP")

    try:
        geom = _call_compute_routes(coords)
        cache[key] = geom            # cache the real geometry forever
        _save_json(_poly_cache_path(), cache)
        return {**geom, "source": "GOOGLE_ROADS"}
    except Exception as exc:
        print(f"[route_geometry] Google failed ({exc}) -> straight legs.")
        return _straight_geometry(coords, source="STRAIGHT_ERROR")
