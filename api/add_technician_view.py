"""
api/add_technician_view.py
=============================================================================
Technician management for the LOGGED-IN supervisor's own group.

  POST   /api/technicians/add/              create a technician in my group
  POST   /api/technicians/<id>/remove/      soft-delete (is_active_employee=False)
  POST   /api/technicians/<id>/reactivate/  bring a removed technician back

Soft delete keeps the row (and all schedule/task history) intact -- it only
hides the technician from the active roster. This is separate from LEAVE:
  - leave        -> is_available = False      (temporarily away, still employed)
  - soft delete  -> is_active_employee = False (no longer on the roster)

A supervisor can only add to / remove from THEIR OWN group (scoped by the
auth token). Excel files are never touched -- only the database changes.

Wire in api/urls.py:
    from .add_technician_view import (
        AddTechnicianView, RemoveTechnicianView, ReactivateTechnicianView,
    )
    path("technicians/add/", AddTechnicianView.as_view()),
    path("technicians/<int:pk>/remove/", RemoveTechnicianView.as_view()),
    path("technicians/<int:pk>/reactivate/", ReactivateTechnicianView.as_view()),
=============================================================================
"""
from django.contrib.auth.models import User
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import (
    Technician, UserProfile, UserRole,
    TechnicianRole, SpecialtyType, ExperienceLevel,
)

DEFAULT_PASSWORD = "tech12345"

VALID_ROLES = {TechnicianRole.MAINTENANCE, TechnicianRole.CALLBACK}
VALID_SPECS = {SpecialtyType.ELEVATOR, SpecialtyType.ESCALATOR, SpecialtyType.BOTH}


def _supervised_group(request):
    """The group the logged-in user supervises, or None."""
    return getattr(request.user, "supervised_group", None)


def _group_hq(group):
    """Derive the group's HQ from an existing located technician in it."""
    t = (Technician.objects
         .filter(group=group, current_latitude__isnull=False)
         .first())
    if t is not None:
        return float(t.current_latitude), float(t.current_longitude)
    # Istanbul centre fallback if the group has no located techs yet
    return 41.0700, 29.0100


class AddTechnicianView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        group = _supervised_group(request)
        if group is None:
            return Response(
                {"error": "This account is not a supervisor of any group."},
                status=403)

        full_name = (request.data.get("full_name") or "").strip()
        role = (request.data.get("tech_role") or "").strip().upper()
        spec = (request.data.get("specialty") or "").strip().upper()

        if not full_name:
            return Response({"error": "full_name required"}, status=400)
        if role not in VALID_ROLES:
            return Response(
                {"error": f"tech_role must be one of {sorted(VALID_ROLES)}"},
                status=400)
        if spec not in VALID_SPECS:
            return Response(
                {"error": f"specialty must be one of {sorted(VALID_SPECS)}"},
                status=400)

        # Callback technicians always cover both specialties.
        if role == TechnicianRole.CALLBACK:
            spec = SpecialtyType.BOTH

        # Guard: a single-role group must stay single-role. A maintenance-only
        # HQ cannot gain a callback tech (and vice-versa). Only a MIXED group
        # (already has both) may add either. This mirrors the dashboard UI.
        existing_roles = set(
            Technician.objects.filter(group=group)
            .values_list("tech_role", flat=True)
        )
        has_maint = TechnicianRole.MAINTENANCE in existing_roles
        has_call = TechnicianRole.CALLBACK in existing_roles
        is_mixed = has_maint and has_call
        if not is_mixed and existing_roles:
            only_role = TechnicianRole.MAINTENANCE if has_maint else TechnicianRole.CALLBACK
            if role != only_role:
                return Response({
                    "error": f"This group is {only_role.lower()}-only. "
                             f"You can only add {only_role.lower()} technicians here."
                }, status=400)

        # unique employee code + username (NEW- prefix never clashes with T001..)
        n = Technician.objects.filter(employee_code__startswith="NEW-T").count() + 1
        code = f"NEW-T{n:03d}"
        while Technician.objects.filter(employee_code=code).exists():
            n += 1
            code = f"NEW-T{n:03d}"
        uname = f"new_t{n:03d}"
        while User.objects.filter(username=uname).exists():
            n += 1
            uname = f"new_t{n:03d}"
            code = f"NEW-T{n:03d}"

        parts = full_name.split()
        user = User.objects.create(
            username=uname,
            first_name=parts[0],
            last_name=parts[-1] if len(parts) > 1 else "",
        )
        user.set_password(DEFAULT_PASSWORD)
        user.save()
        UserProfile.objects.update_or_create(
            user=user, defaults={"role": UserRole.TECH})

        hq_lat, hq_lng = _group_hq(group)

        tech = Technician.objects.create(
            user=user,
            employee_code=code,
            full_name=full_name,
            group=group,
            tech_role=role,
            specialty=spec,
            experience_level=ExperienceLevel.JUNIOR,
            is_available=True,
            is_active_employee=True,
            daily_capacity_min=480,
            max_overtime_min=60,
            current_latitude=hq_lat,
            current_longitude=hq_lng,
        )

        return Response({
            "id": tech.id,
            "name": tech.full_name,
            "username": uname,
            "employee_code": code,
            "tech_role": tech.tech_role,
            "specialty": tech.specialty,
            "message": f"{full_name} added to {group.name}.",
        }, status=201)


class RemoveTechnicianView(APIView):
    """Soft delete: hide the technician but keep their history."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        group = _supervised_group(request)
        if group is None:
            return Response(
                {"error": "This account is not a supervisor of any group."},
                status=403)

        tech = Technician.objects.filter(pk=pk).first()
        if tech is None:
            return Response({"error": "Technician not found."}, status=404)

        # scope: a supervisor can only remove techs in their OWN group
        if tech.group_id != group.id:
            return Response(
                {"error": "You can only remove technicians in your own group."},
                status=403)

        tech.is_active_employee = False
        tech.save(update_fields=["is_active_employee"])
        return Response({
            "id": tech.id,
            "name": tech.full_name,
            "is_active_employee": False,
            "message": f"{tech.full_name} removed from the active roster "
                       f"(history kept).",
        })


class ReactivateTechnicianView(APIView):
    """Undo a soft delete: bring a removed technician back onto the roster."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        group = _supervised_group(request)
        if group is None:
            return Response(
                {"error": "This account is not a supervisor of any group."},
                status=403)

        tech = Technician.objects.filter(pk=pk).first()
        if tech is None:
            return Response({"error": "Technician not found."}, status=404)
        if tech.group_id != group.id:
            return Response(
                {"error": "You can only reactivate technicians in your own group."},
                status=403)

        tech.is_active_employee = True
        tech.save(update_fields=["is_active_employee"])
        return Response({
            "id": tech.id,
            "name": tech.full_name,
            "is_active_employee": True,
            "message": f"{tech.full_name} reactivated.",
        })
