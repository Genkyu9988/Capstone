"""
api/me_view.py
=============================================================================
GET /api/me/   ->  the logged-in technician's real profile, for the mobile
Profile tab. Authenticated with the same Basic Auth the mobile already uses.

Returns the attributes that actually drive the optimizer (specialty, role,
capacity, region) plus a live "today" workload summary, so the profile
explains *why* this technician gets the jobs they get.

Wire it up in api/urls.py:
    from .me_view import MeView
    path("me/", MeView.as_view()),
=============================================================================
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Schedule

REGION_THRESHOLD = 29.02


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tech = getattr(request.user, "technician_profile", None)
        if tech is None:
            return Response({"error": "No technician profile for this user."}, status=404)

        # Region from the depot longitude (Bosphorus split ~29.02 E).
        lng = float(tech.current_longitude) if tech.current_longitude is not None else 28.97
        region = "ASIA" if lng >= REGION_THRESHOLD else "EUROPE"

        # Live "today" workload from the schedule.
        scheds = list(
            Schedule.objects.filter(technician=tech).select_related("task")
        )
        planned_min = sum((s.task.estimated_duration_min or 0) for s in scheds)

        supervisor_name = None
        if tech.group and tech.group.supervisor:
            sup = tech.group.supervisor
            supervisor_name = (sup.get_full_name() or sup.username)

        return Response({
            "full_name": tech.full_name,
            "employee_code": tech.employee_code,
            "tech_role": tech.tech_role,                 # MAINTENANCE / REPAIR / BOTH
            "specialty": tech.specialty,                 # ELEVATOR / ESCALATOR / BOTH
            "experience_level": tech.experience_level,
            "phone": tech.phone,
            "work_start": tech.work_start.strftime("%H:%M") if tech.work_start else None,
            "work_end": tech.work_end.strftime("%H:%M") if tech.work_end else None,
            "daily_capacity_min": tech.daily_capacity_min,
            "max_overtime_min": tech.max_overtime_min,
            "is_available": tech.is_available,
            "region": region,
            "supervisor": supervisor_name,
            "group": tech.group.name if tech.group else None,
            "today_stops": len(scheds),
            "today_planned_min": planned_min,
        })
