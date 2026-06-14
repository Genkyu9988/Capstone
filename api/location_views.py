"""
api/location_views.py
=============================================================================
POST /api/my-location/

The technician's phone app sends its GPS position here every few seconds.
We write it onto current_latitude / current_longitude AND stamp
last_location_at, so the dashboard can tell whose phone is *currently* live
(real GPS) versus whose position must be estimated from the schedule.

Auth: BasicAuthentication (project-wide), same as /api/my-route/.
=============================================================================
"""
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class MyLocationUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        technician = getattr(request.user, "technician_profile", None)
        if technician is None:
            return Response({"error": "Not a technician"}, status=400)

        try:
            lat = float(request.data.get("latitude"))
            lng = float(request.data.get("longitude"))
        except (TypeError, ValueError):
            return Response({"error": "latitude and longitude are required numbers"}, status=400)

        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return Response({"error": "latitude/longitude out of range"}, status=400)

        technician.current_latitude = lat
        technician.current_longitude = lng
        technician.last_location_at = timezone.now()
        technician.save(update_fields=[
            "current_latitude", "current_longitude", "last_location_at",
        ])

        return Response({
            "ok": True,
            "technician": technician.full_name,
            "latitude": lat,
            "longitude": lng,
            "updated_at": technician.last_location_at.isoformat(),
        })
