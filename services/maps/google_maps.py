"""
api/services/maps/google_maps.py
Calls Google's Routes API (computeRouteMatrix) for real road travel times.

SAFETY: every Google call in the whole project passes through get_route_matrix.
A persistent, per-calendar-day counter (stored in a small JSON file) HARD-STOPS
calls once GOOGLE_MAPS_DAILY_LIMIT is reached -- guaranteeing the project never
exceeds a tiny number of calls per day, keeping usage inside the free tier.

If the limit is hit, the call raises RuntimeError; callers that use
distance_service will simply fall back to the haversine MOCK (no crash, no cost).
"""
import json
import os
from datetime import date

import requests
from django.conf import settings


ROUTES_MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"

# the counter file lives next to this module
_COUNTER_PATH = os.path.join(os.path.dirname(__file__), "_daily_call_count.json")


def _read_counter():
    try:
        with open(_COUNTER_PATH, "r") as f:
            data = json.load(f)
        return data.get("date"), int(data.get("count", 0))
    except Exception:
        return None, 0


def _write_counter(day_str, count):
    try:
        with open(_COUNTER_PATH, "w") as f:
            json.dump({"date": day_str, "count": count}, f)
    except Exception:
        pass  # never let counter I/O break a request


def _calls_made_today():
    today = date.today().isoformat()
    saved_date, count = _read_counter()
    if saved_date != today:
        return 0  # new day -> counter resets
    return count


def _increment_today():
    today = date.today().isoformat()
    saved_date, count = _read_counter()
    count = (count + 1) if saved_date == today else 1
    _write_counter(today, count)
    return count


def remaining_calls_today():
    limit = getattr(settings, "GOOGLE_MAPS_DAILY_LIMIT", 100)
    return max(0, limit - _calls_made_today())


def get_route_matrix(origins, destinations):
    if not settings.GOOGLE_MAPS_ENABLED:
        raise RuntimeError("Google Maps disabled. GOOGLE_MAPS_ENABLED=False")

    if not settings.GOOGLE_MAPS_API_KEY:
        raise ValueError("GOOGLE_MAPS_API_KEY is not set in .env")

    # ---- HARD DAILY CAP (project-wide free-tier guard) ----
    limit = getattr(settings, "GOOGLE_MAPS_DAILY_LIMIT", 100)
    if _calls_made_today() >= limit:
        raise RuntimeError(
            f"Google Maps daily call limit reached ({limit}). "
            f"Refusing the call to stay within free tier. Resets tomorrow.")

    body = {
        "origins": [
            {"waypoint": {"location": {"latLng": {
                "latitude": float(lat), "longitude": float(lng)}}}}
            for lat, lng in origins
        ],
        "destinations": [
            {"waypoint": {"location": {"latLng": {
                "latitude": float(lat), "longitude": float(lng)}}}}
            for lat, lng in destinations
        ],
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
    }

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": "originIndex,destinationIndex,duration,distanceMeters,status",
    }

    # count the call BEFORE making it, so a failure still consumes quota slot
    # (prevents retry loops from bypassing the cap)
    _increment_today()

    response = requests.post(ROUTES_MATRIX_URL, json=body, headers=headers, timeout=20)
    response.raise_for_status()
    return response.json()
