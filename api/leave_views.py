"""
api/leave_views.py
=============================================================================
Leave request API.

Current demo flow:
    1) Create a PENDING LeaveRequest from console with:
          python manage.py create_leave_request --technician "Ali Aslankan" --start 2026-07-08 --days 7
    2) Supervisor Dashboard calls GET /api/leave-requests/ and shows it.
    3) Supervisor approves/rejects using POST /api/leave-request/<id>/decision/.
    4) On APPROVE, future maintenance/callback schedules are rebuilt with Gurobi from
       the leave start date. The leave technician is excluded only on leave days.

Future mobile flow:
    POST /api/leave-request/ can be called by the technician mobile app.
=============================================================================
"""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import LeaveRequest, Technician, TechnicianRole
from api.services.leave_rules import (
    get_operating_date,
    parse_iso_date,
    validate_leave_window,
    validate_instant_leave_window,
)
from api.services.schedule_rebuild import (
    rebuild_group_future_schedule,
    rebuild_group_instant_leave_schedule,
    rebuild_group_future_callbacks,
    rebuild_group_instant_callback_leave_schedule,
    next_day_from_roll_date,
)


def _serialize(req: LeaveRequest) -> dict:
    tech = req.technician
    return {
        "id": req.id,
        "technician_id": tech.id,
        "technician": tech.full_name,
        "group_id": tech.group_id,
        "group": tech.group.name if tech.group else None,
        "tech_role": tech.tech_role,
        "specialty": tech.specialty,
        "leave_type": req.leave_type,
        "is_instant": _is_instant_leave(req),
        "start_date": req.start_date.isoformat(),
        "end_date": req.end_date.isoformat(),
        "reason": req.reason or "",
        "status": req.status,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "decided_at": req.decided_at.isoformat() if req.decided_at else None,
    }


def _is_instant_leave(req_or_type) -> bool:
    value = getattr(req_or_type, "leave_type", req_or_type) or ""
    return "instant" in str(value).strip().lower() or "emergency" in str(value).strip().lower()


def _supervised_group(request):
    return getattr(request.user, "supervised_group", None)


def _can_manage_request(user, req: LeaveRequest) -> bool:
    if user and user.is_authenticated and (user.is_staff or user.is_superuser):
        return True
    group = getattr(user, "supervised_group", None)
    return bool(group and req.technician.group_id == group.id)


class LeaveRequestCreateView(APIView):
    """Future mobile endpoint; console command is used for the current demo."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data or {}
        tech = getattr(request.user, "technician_profile", None)

        # For console/API testing from a supervisor/admin token, allow technician_id/name.
        if tech is None:
            tech_id = data.get("technician_id")
            tech_name = data.get("technician") or data.get("technician_name")
            if tech_id:
                tech = Technician.objects.filter(id=tech_id).first()
            elif tech_name:
                tech = Technician.objects.filter(full_name__icontains=tech_name).order_by("id").first()

        if tech is None:
            return Response({"error": "Technician could not be resolved."}, status=400)
        if tech.tech_role not in (TechnicianRole.MAINTENANCE, TechnicianRole.CALLBACK):
            return Response({"error": "Leave requests are supported for maintenance and callback technicians."}, status=400)
        if not tech.is_active_employee:
            return Response({"error": "Inactive/removed technicians cannot request leave."}, status=400)

        leave_type = data.get("leave_type") or data.get("type") or "Annual Leave"
        is_instant = _is_instant_leave(leave_type) or bool(data.get("instant"))

        try:
            operating_date = get_operating_date(request)
            if is_instant:
                # Instant leave starts now, on the active roll-date day. Mobile will
                # later call the same endpoint; for now console/dashboard tests can
                # pass leave_type="Instant Leave".
                start = operating_date
                if data.get("end_date") or data.get("end"):
                    end = parse_iso_date(data.get("end_date") or data.get("end"), field_name="end_date")
                else:
                    days = int(data.get("days") or 1)
                    end = start + timedelta(days=days - 1)
                validate_instant_leave_window(start, end, today=operating_date)
                leave_type = "Instant Leave"
            else:
                start = parse_iso_date(data.get("start_date") or data.get("start"), field_name="start_date")
                if data.get("end_date") or data.get("end"):
                    end = parse_iso_date(data.get("end_date") or data.get("end"), field_name="end_date")
                else:
                    days = int(data.get("days") or 1)
                    end = start + timedelta(days=days - 1)
                validate_leave_window(start, end, today=operating_date, enforce_notice=True)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)

        overlapping = LeaveRequest.objects.filter(
            technician=tech,
            status__in=[LeaveRequest.LeaveStatus.PENDING, LeaveRequest.LeaveStatus.APPROVED],
            start_date__lte=end,
            end_date__gte=start,
        ).first()
        if overlapping:
            return Response({
                "error": (
                    f"Overlapping leave request already exists: #{overlapping.id} "
                    f"{overlapping.start_date} to {overlapping.end_date} ({overlapping.status})."
                )
            }, status=400)

        req = LeaveRequest.objects.create(
            technician=tech,
            leave_type=leave_type,
            start_date=start,
            end_date=end,
            reason=data.get("reason") or "",
            status=LeaveRequest.LeaveStatus.PENDING,
        )
        return Response({"request": _serialize(req)}, status=status.HTTP_201_CREATED)


class LeaveRequestListView(APIView):
    """Supervisor dashboard list: pending + approved/rejected history."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = LeaveRequest.objects.select_related("technician", "technician__group").all()

        group = _supervised_group(request)
        if group is not None and not (request.user.is_staff or request.user.is_superuser):
            qs = qs.filter(technician__group=group)
        else:
            # Optional admin/group filter if the endpoint is opened by staff.
            group_id = request.query_params.get("group_id")
            if group_id:
                qs = qs.filter(technician__group_id=group_id)

        qs = qs.order_by(
            "status",        # APPROVED/PENDING/REJECTED alphabetically, but date below keeps it readable
            "start_date",
            "technician__full_name",
        )

        active_today = get_operating_date(request)
        return Response({
            "active_date": active_today.isoformat(),
            "requests": [_serialize(r) for r in qs],
        })


class LeaveRequestDecisionView(APIView):
    """Supervisor approves/rejects/returns a leave request."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk: int):
        req = LeaveRequest.objects.select_related("technician", "technician__group").filter(id=pk).first()
        if req is None:
            return Response({"error": "Leave request not found."}, status=404)
        if not _can_manage_request(request.user, req):
            return Response({"error": "Only the technician's supervisor can decide this leave request."}, status=403)

        decision = str((request.data or {}).get("decision") or "").strip().upper()
        if decision not in {"APPROVE", "REJECT", "RETURN"}:
            return Response({"error": "decision must be APPROVE, REJECT, or RETURN."}, status=400)

        tech = req.technician
        if tech.tech_role not in (TechnicianRole.MAINTENANCE, TechnicianRole.CALLBACK):
            return Response({"error": "This leave rebuild flow supports maintenance and callback technicians only."}, status=400)

        # Always keep the max-window rule. Do not re-check 14-day notice for
        # planned leave here, because a valid request may be approved a few days
        # after it was created. For instant leave, no notice is required.
        try:
            if _is_instant_leave(req):
                # If the supervisor approves the instant request on the same roll
                # date it was created, this validates the emergency interval. If
                # the roll date moved, we still allow approval and rebuild from the
                # current roll datetime below.
                validate_leave_window(req.start_date, req.end_date, today=get_operating_date(request), enforce_notice=False)
            else:
                validate_leave_window(req.start_date, req.end_date, today=get_operating_date(request), enforce_notice=False)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)

        rebuild = None
        with transaction.atomic():
            if decision == "APPROVE":
                req.status = LeaveRequest.LeaveStatus.APPROVED
            elif decision == "REJECT":
                req.status = LeaveRequest.LeaveStatus.REJECTED
            else:
                req.status = LeaveRequest.LeaveStatus.RETURNED
            req.decided_at = timezone.now()
            req.save(update_fields=["status", "decided_at"])

        # On approve/return, rebuild only the matching schedule domain.
        # MAINTENANCE technicians rebuild maintenance tasks; CALLBACK technicians
        # rebuild callback tasks. The two domains are intentionally separate.
        if decision == "APPROVE":
            if tech.tech_role == TechnicianRole.CALLBACK:
                if _is_instant_leave(req):
                    rebuild = rebuild_group_instant_callback_leave_schedule(
                        tech.group,
                        leave_request=req,
                        request=request,
                    )
                    msg = (
                        f"{tech.full_name} instant leave approved. Same-day remaining and future "
                        f"callback schedule rebuilt from {rebuild.get('active_datetime')} "
                        f"to {rebuild.get('end_date')} using Gurobi."
                    )
                else:
                    rebuild = rebuild_group_future_callbacks(
                        tech.group,
                        effective_date=req.start_date,
                        request=request,
                    )
                    msg = (
                        f"{tech.full_name} leave approved. Future callback schedule rebuilt "
                        f"from {req.start_date} to {rebuild.get('end_date')} using Gurobi."
                    )
            else:
                if _is_instant_leave(req):
                    rebuild = rebuild_group_instant_leave_schedule(
                        tech.group,
                        leave_request=req,
                        request=request,
                    )
                    msg = (
                        f"{tech.full_name} instant leave approved. Same-day remaining and future "
                        f"maintenance schedule rebuilt from {rebuild.get('active_datetime')} "
                        f"to {rebuild.get('end_date')} using Gurobi."
                    )
                else:
                    rebuild = rebuild_group_future_schedule(
                        tech.group,
                        effective_date=req.start_date,
                        request=request,
                    )
                    msg = (
                        f"{tech.full_name} leave approved. Future maintenance schedule rebuilt "
                        f"from {req.start_date} to {rebuild.get('end_date')} using Gurobi."
                    )
        elif decision == "RETURN":
            rebuild_from = max(next_day_from_roll_date(request), req.start_date)
            if tech.tech_role == TechnicianRole.CALLBACK:
                rebuild = rebuild_group_future_callbacks(
                    tech.group,
                    effective_date=rebuild_from,
                    request=request,
                )
                msg = (
                    f"{tech.full_name} marked returned. Future callback schedule rebuilt "
                    f"from {rebuild_from} to {rebuild.get('end_date')} using Gurobi."
                )
            else:
                rebuild = rebuild_group_future_schedule(
                    tech.group,
                    effective_date=rebuild_from,
                    request=request,
                )
                msg = (
                    f"{tech.full_name} marked returned. Future maintenance schedule rebuilt "
                    f"from {rebuild_from} to {rebuild.get('end_date')} using Gurobi."
                )
        else:
            msg = f"{tech.full_name} leave request rejected."

        return Response({
            "message": msg,
            "request": _serialize(req),
            "rebuild": rebuild,
        })
