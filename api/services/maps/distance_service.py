from math import radians, sin, cos, sqrt, atan2
from django.conf import settings

from api.models import DistanceMatrixCache
from api.services.maps.google_maps import get_route_matrix


def haversine_distance_km(lat1, lng1, lat2, lng2):
    r = 6371

    lat1 = radians(float(lat1))
    lng1 = radians(float(lng1))
    lat2 = radians(float(lat2))
    lng2 = radians(float(lng2))

    dlat = lat2 - lat1
    dlng = lng2 - lng1

    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return r * c


def estimate_mock_distance(origin_unit, destination_unit):
    distance_km = haversine_distance_km(
        origin_unit.latitude,
        origin_unit.longitude,
        destination_unit.latitude,
        destination_unit.longitude,
    )

    road_distance_km = distance_km * 1.35
    duration_hours = road_distance_km / 30
    duration_seconds = int(duration_hours * 3600)

    return {
        "distance_meters": int(road_distance_km * 1000),
        "duration_seconds": max(duration_seconds, 60),
        "from_cache": False,
        "source": "MOCK",
    }


def parse_duration_seconds(duration_text):
    if not duration_text:
        return None

    return int(duration_text.replace("s", ""))


def get_or_create_unit_distance(origin_unit, destination_unit):
    if origin_unit.id == destination_unit.id:
        return {
            "distance_meters": 0,
            "duration_seconds": 0,
            "from_cache": True,
            "source": "SAME_UNIT",
        }

    cached = DistanceMatrixCache.objects.filter(
        origin_unit=origin_unit,
        destination_unit=destination_unit,
        provider="GOOGLE_MAPS",
    ).first()

    if cached:
        return {
            "distance_meters": cached.distance_meters,
            "duration_seconds": cached.duration_seconds,
            "from_cache": True,
            "source": "CACHE",
        }

    if not settings.GOOGLE_MAPS_ENABLED:
        return estimate_mock_distance(origin_unit, destination_unit)

    result = get_route_matrix(
        origins=[(origin_unit.latitude, origin_unit.longitude)],
        destinations=[(destination_unit.latitude, destination_unit.longitude)],
    )

    if not result:
        raise ValueError("Google Maps boş sonuç döndürdü.")

    row = result[0]

    if row.get("status") and row["status"].get("code"):
        raise ValueError(f"Google Maps route error: {row['status']}")

    distance_meters = row.get("distanceMeters")
    duration_seconds = parse_duration_seconds(row.get("duration"))

    if distance_meters is None or duration_seconds is None:
        raise ValueError(f"Distance veya duration alınamadı: {row}")

    DistanceMatrixCache.objects.create(
        origin_unit=origin_unit,
        destination_unit=destination_unit,
        distance_meters=distance_meters,
        duration_seconds=duration_seconds,
        provider="GOOGLE_MAPS",
    )

    return {
        "distance_meters": distance_meters,
        "duration_seconds": duration_seconds,
        "from_cache": False,
        "source": "GOOGLE_MAPS",
    }