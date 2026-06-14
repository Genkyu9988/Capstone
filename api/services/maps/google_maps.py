import requests
from django.conf import settings


ROUTES_MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"


def get_route_matrix(origins, destinations):
    if not settings.GOOGLE_MAPS_ENABLED:
        raise RuntimeError("Google Maps disabled. GOOGLE_MAPS_ENABLED=False")

    if not settings.GOOGLE_MAPS_API_KEY:
        raise ValueError("GOOGLE_MAPS_API_KEY .env içinde tanımlı değil.")

    body = {
        "origins": [
            {
                "waypoint": {
                    "location": {
                        "latLng": {
                            "latitude": float(lat),
                            "longitude": float(lng),
                        }
                    }
                }
            }
            for lat, lng in origins
        ],
        "destinations": [
            {
                "waypoint": {
                    "location": {
                        "latLng": {
                            "latitude": float(lat),
                            "longitude": float(lng),
                        }
                    }
                }
            }
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

    response = requests.post(
        ROUTES_MATRIX_URL,
        json=body,
        headers=headers,
        timeout=20,
    )

    response.raise_for_status()
    return response.json()