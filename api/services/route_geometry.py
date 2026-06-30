"""
api/services/maps/route_geometry.py
=============================================================================
Google/cached road geometry for supervisor live map and technician mobile map.

Cost-safe design:
  * precompute/call Google with a management command;
  * cache each ordered technician-day route on disk;
  * live map/mobile read cache first and can run in cache-only mode so polling
    does not create repeated Google API calls;
  * if Google is missing/capped/fails, return ROADLIKE_FALLBACK instead of an
    ugly straight line.

Sources returned:
  * GOOGLE_ROADS      real Google Routes API response, newly fetched
  * CACHE             previously cached Google road geometry
  * ROADLIKE_FALLBACK local no-cost route-like fallback, not a real road route
=============================================================================
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from math import asin, atan2, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests
from django.conf import settings

Point = Tuple[float, float]

BOSPHORUS_LNG = 29.02
BRIDGES = {
    "15_JULY": {
        "west": (41.0448, 29.0296),
        "east": (41.0448, 29.0420),
    },
    "FSM": {
        "west": (41.0910, 29.0560),
        "east": (41.0910, 29.0710),
    },
}


def _setting(name: str, default: Any = None) -> Any:
    """Environment variables override Django settings for one-off route jobs."""
    env = os.environ.get(name)
    if env not in (None, ""):
        return env
    value = getattr(settings, name, default)
    return default if value is None else value


def _int_setting(name: str, default: int) -> int:
    try:
        return int(_setting(name, default))
    except Exception:
        return default


def _float_setting(name: str, default: float) -> float:
    try:
        return float(_setting(name, default))
    except Exception:
        return default


def _bool_setting(name: str, default: bool = False) -> bool:
    value = _setting(name, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_point(obj: Any) -> Point:
    if isinstance(obj, dict):
        lat = obj.get("lat", obj.get("latitude"))
        lng = obj.get("lng", obj.get("longitude"))
        return (float(lat), float(lng))
    return (float(obj[0]), float(obj[1]))


def _normalize_points(origin: Any, stops: Iterable[Any]) -> List[Point]:
    pts = [_as_point(origin)]
    for s in stops:
        p = _as_point(s)
        if p[0] is None or p[1] is None:
            continue
        if not pts or abs(pts[-1][0] - p[0]) > 1e-9 or abs(pts[-1][1] - p[1]) > 1e-9:
            pts.append(p)
    return pts


def _haversine_km(a: Point, b: Point) -> float:
    lat1, lng1 = radians(a[0]), radians(a[1])
    lat2, lng2 = radians(b[0]), radians(b[1])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(h))


def _path_distance_km(points: Sequence[Point]) -> float:
    return sum(_haversine_km(points[i - 1], points[i]) for i in range(1, len(points)))


def _duration_min(distance_km: float, kmh: float = 24.0) -> int:
    if distance_km <= 0:
        return 0
    return max(1, int(round((distance_km / kmh) * 60)))


def _cache_dir() -> Path:
    base = Path(getattr(settings, "BASE_DIR", os.getcwd()))
    raw = _setting("ROUTE_GEOMETRY_CACHE_DIR", None)
    path = Path(raw) if raw else base / ".maps_cache" / "route_geometry"
    path.mkdir(parents=True, exist_ok=True)
    return path


def route_cache_key(origin: Any, stops: Iterable[Any]) -> str:
    points = _normalize_points(origin, stops)
    raw = "|".join(f"{lat:.5f},{lng:.5f}" for lat, lng in points)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_key(points: Sequence[Point]) -> str:
    raw = "|".join(f"{lat:.5f},{lng:.5f}" for lat, lng in points)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_google_cache(key: str) -> Optional[Dict[str, Any]]:
    fp = _cache_dir() / f"{key}.json"
    if not fp.exists():
        return None
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
        if data.get("source") in {"GOOGLE_ROADS", "CACHE"} and data.get("points"):
            data["source"] = "CACHE"
            return data
    except Exception:
        return None
    return None


def _write_google_cache(key: str, data: Dict[str, Any]) -> None:
    if data.get("source") != "GOOGLE_ROADS":
        return
    fp = _cache_dir() / f"{key}.json"
    try:
        fp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _counter_path() -> Path:
    return _cache_dir() / "_daily_google_counter.json"


def _google_api_key() -> Optional[str]:
    return _setting("GOOGLE_MAPS_API_KEY", None) or os.environ.get("GOOGLE_MAPS_API_KEY")


def google_calls_today() -> int:
    today = date.today().isoformat()
    fp = _counter_path()
    try:
        data = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else {}
    except Exception:
        data = {}
    return int(data.get(today, 0))


def _can_call_google() -> bool:
    if not _bool_setting("GOOGLE_MAPS_ENABLED", False):
        return False
    if not _google_api_key():
        return False
    cap = _int_setting("GOOGLE_MAPS_DAILY_LIMIT", 300)
    if cap <= 0:
        return False
    return google_calls_today() < cap


def _mark_google_call() -> None:
    today = date.today().isoformat()
    fp = _counter_path()
    try:
        data = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else {}
    except Exception:
        data = {}
    data[today] = int(data.get(today, 0)) + 1
    try:
        fp.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def _decode_polyline(polyline: str) -> List[Point]:
    points: List[Point] = []
    index = lat = lng = 0
    length = len(polyline)
    while index < length:
        shift = result = 0
        while True:
            b = ord(polyline[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if result & 1 else result >> 1
        lat += dlat

        shift = result = 0
        while True:
            b = ord(polyline[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if result & 1 else result >> 1
        lng += dlng
        points.append((lat / 1e5, lng / 1e5))
    return points


def _parse_duration_seconds(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value)
    if text.endswith("s"):
        text = text[:-1]
    try:
        return int(float(text))
    except Exception:
        return None


def _google_route_single(points: Sequence[Point]) -> Dict[str, Any]:
    api_key = _google_api_key()
    if not api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is missing")
    if len(points) < 2:
        raise RuntimeError("At least two points are required")
    if len(points) > 25:
        raise RuntimeError("A single Google route can contain at most 25 points")
    if not _can_call_google():
        raise RuntimeError("Google route call disabled, API key missing, or daily cap reached")

    def loc(p: Point) -> Dict[str, Any]:
        return {"location": {"latLng": {"latitude": p[0], "longitude": p[1]}}}

    payload: Dict[str, Any] = {
        "origin": loc(points[0]),
        "destination": loc(points[-1]),
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "computeAlternativeRoutes": False,
        "languageCode": "tr-TR",
        "units": "METRIC",
    }
    if len(points) > 2:
        payload["intermediates"] = [loc(p) for p in points[1:-1]]

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline",
    }

    _mark_google_call()
    resp = requests.post(
        "https://routes.googleapis.com/directions/v2:computeRoutes",
        json=payload,
        headers=headers,
        timeout=_float_setting("GOOGLE_MAPS_TIMEOUT_SECONDS", 12.0),
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Google Routes HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    routes = data.get("routes") or []
    if not routes:
        raise RuntimeError("Google Routes returned no route")
    route = routes[0]
    encoded = ((route.get("polyline") or {}).get("encodedPolyline"))
    if not encoded:
        raise RuntimeError("Google Routes returned no encoded polyline")

    decoded = _decode_polyline(encoded)
    if len(decoded) < 2:
        raise RuntimeError("Decoded Google polyline is too short")

    distance_m = route.get("distanceMeters")
    duration_s = _parse_duration_seconds(route.get("duration"))
    return {
        "points": [[lat, lng] for lat, lng in decoded],
        "source": "GOOGLE_ROADS",
        "distance_km": round(float(distance_m or 0) / 1000.0, 2) if distance_m is not None else round(_path_distance_km(decoded), 2),
        "duration_min": int(round((duration_s or 0) / 60.0)) if duration_s is not None else _duration_min(_path_distance_km(decoded)),
    }


def _google_route_chunked(points: Sequence[Point]) -> Dict[str, Any]:
    """Google supports a limited number of waypoints; split long days safely."""
    if len(points) <= 25:
        return _google_route_single(points)

    merged: List[List[float]] = []
    total_distance = 0.0
    total_duration = 0
    start = 0
    while start < len(points) - 1:
        chunk = points[start:min(start + 25, len(points))]
        data = _google_route_single(chunk)
        pts = data.get("points") or []
        if not pts:
            raise RuntimeError("Google chunk returned no points")
        if merged and pts:
            pts = pts[1:]
        merged.extend(pts)
        total_distance += float(data.get("distance_km") or 0)
        total_duration += int(data.get("duration_min") or 0)
        if start + 25 >= len(points):
            break
        start += 24  # overlap last point as the next chunk origin

    if len(merged) < 2:
        raise RuntimeError("Chunked Google route produced too few points")
    return {
        "points": merged,
        "source": "GOOGLE_ROADS",
        "distance_km": round(total_distance, 2),
        "duration_min": total_duration,
        "chunked": True,
    }


def _interpolate(a: Point, b: Point, max_step_km: float = 0.35) -> List[Point]:
    km = _haversine_km(a, b)
    n = max(1, int(km / max_step_km))
    return [
        (a[0] + (b[0] - a[0]) * (i / n), a[1] + (b[1] - a[1]) * (i / n))
        for i in range(1, n + 1)
    ]


def _choose_bridge(a: Point, b: Point) -> Dict[str, Point]:
    avg_lat = (a[0] + b[0]) / 2.0
    return BRIDGES["FSM"] if avg_lat >= 41.07 else BRIDGES["15_JULY"]


def _same_side(a: Point, b: Point) -> bool:
    return (a[1] < BOSPHORUS_LNG and b[1] < BOSPHORUS_LNG) or (a[1] >= BOSPHORUS_LNG and b[1] >= BOSPHORUS_LNG)


def _dogleg_points(a: Point, b: Point) -> List[Point]:
    waypoints: List[Point] = []
    if not _same_side(a, b):
        bridge = _choose_bridge(a, b)
        if a[1] < BOSPHORUS_LNG:
            waypoints.extend([bridge["west"], bridge["east"]])
        else:
            waypoints.extend([bridge["east"], bridge["west"]])
    waypoints.append(b)

    out: List[Point] = []
    cur = a
    for wp in waypoints:
        bend1 = (cur[0], wp[1])
        bend2 = (wp[0], cur[1])
        path1 = _haversine_km(cur, bend1) + _haversine_km(bend1, wp)
        path2 = _haversine_km(cur, bend2) + _haversine_km(bend2, wp)
        bend = bend1 if path1 <= path2 else bend2
        for target in [bend, wp]:
            if _haversine_km(cur, target) > 0.03:
                out.extend(_interpolate(cur, target))
            cur = target
    return out


def _roadlike_fallback(points: Sequence[Point], reason: str = "") -> Dict[str, Any]:
    if not points:
        return {"points": [], "source": "ROADLIKE_FALLBACK", "distance_km": 0, "duration_min": 0}
    poly: List[Point] = [points[0]]
    for i in range(1, len(points)):
        leg = _dogleg_points(points[i - 1], points[i])
        for p in leg:
            if abs(poly[-1][0] - p[0]) > 1e-9 or abs(poly[-1][1] - p[1]) > 1e-9:
                poly.append(p)
    distance_km = _path_distance_km(poly) * 1.05
    return {
        "points": [[lat, lng] for lat, lng in poly],
        "source": "ROADLIKE_FALLBACK",
        "distance_km": round(distance_km, 2),
        "duration_min": _duration_min(distance_km),
        "fallback_reason": reason[:300] if reason else "Google disabled/capped/unavailable",
    }


def build_route_geometry(origin: Any, stops: Iterable[Any], *, allow_google_call: bool = True) -> Dict[str, Any]:
    """Build or read route polyline for supervisor/mobile maps.

    If allow_google_call=False, this function is billing-safe for live polling:
    it reads a Google cache hit, otherwise returns ROADLIKE_FALLBACK without
    calling Google.
    """
    points = _normalize_points(origin, stops)
    if len(points) < 2:
        return {
            "points": [[p[0], p[1]] for p in points],
            "source": None,
            "distance_km": 0,
            "duration_min": 0,
        }

    key = _cache_key(points)
    cached = _read_google_cache(key)
    if cached:
        cached["cache_key"] = key
        return cached

    if not allow_google_call:
        data = _roadlike_fallback(points, reason="CACHE_MISS_GOOGLE_NOT_CALLED_ON_LIVE_POLL")
        data["cache_key"] = key
        return data

    if _can_call_google():
        try:
            data = _google_route_chunked(points)
            data["cache_key"] = key
            _write_google_cache(key, data)
            return data
        except Exception as exc:
            data = _roadlike_fallback(points, reason=str(exc))
            data["cache_key"] = key
            return data

    data = _roadlike_fallback(points, reason="GOOGLE_MAPS_ENABLED false, API key missing, or daily cap reached")
    data["cache_key"] = key
    return data
