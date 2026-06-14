"""
api/leave_views.py
=============================================================================
Leave / time-off approval workflow.

  POST /api/leave-request/                 tech submits  -> creates PENDING
  GET  /api/leave-requests/                supervisor lists requests
  POST /api/leave-request/<id>/decision/   supervisor APPROVE / REJECT / RETURN

Approving sets the technician's is_available = False, which removes them from
dispatch eligibility (the dispatch view already filters is_available=True) and
shows them with an "On Leave" badge on the dashboard. RETURN flips them back
on duty so the demo is repeatable without re-seeding.

Wire up in api/urls.py:
    from .leave_views import (
        LeaveRequestCreateView, LeaveRequestListView, LeaveRequestDecisionView,
    )
    path("leave-request/", LeaveRequestCreateView.as_view()),
    path("leave-requests/", LeaveRequestListView.as_view()),
    path("leave-request/<int:pk>/decision/", LeaveRequestDecisionView.as_view()),
=============================================================================
"""
from datetime import datetime, timedelta, date

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import LeaveRequest


def _parse_date(value):
    if not value:
        return None
    if hasattr(value, "year"):          # already a date
        return value
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _serialize(lr):
    return {
        "id": lr.id,
        "technician": lr.technician.full_name,
        "technician_id": lr.technician.id,
        "leave_type": lr.leave_type,
        "start_date": lr.start_date.isoformat() if lr.start_date else None,
        "end_date": lr.end_date.isoformat() if lr.end_date else None,
        "reason": lr.reason or "",
        "status": lr.status,
        "created_at": lr.created_at.isoformat(),
    }


class LeaveRequestCreateView(APIView):
    """Mobile: the logged-in technician submits a leave request."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        tech = getattr(request.user, "technician_profile", None)
        if tech is None:
            return Response({"error": "No technician profile for this user."}, status=404)

        start = _parse_date(request.data.get("start_date"))
        end = _parse_date(request.data.get("end_date"))
        if start is None or end is None:
            return Response({"error": "start_date and end_date are required (YYYY-MM-DD)."}, status=400)
        if end < start:
            return Response({"error": "end_date cannot be before start_date."}, status=400)

        # Leave must be requested at least 2 weeks (14 days) in advance.
        MIN_ADVANCE_DAYS = 14
        today = timezone.localdate()
        days_ahead = (start - today).days
        if days_ahead < MIN_ADVANCE_DAYS:
            earliest = today + timedelta(days=MIN_ADVANCE_DAYS)
            return Response({
                "error": (f"Leave must be requested at least {MIN_ADVANCE_DAYS} days "
                          f"in advance. The earliest start date you can request is "
                          f"{earliest.isoformat()}."),
                "earliest_start_date": earliest.isoformat(),
                "days_ahead": days_ahead,
            }, status=400)

        lr = LeaveRequest.objects.create(
            technician=tech,
            leave_type=request.data.get("leave_type") or "Medical Leave",
            start_date=start,
            end_date=end,
            reason=request.data.get("reason") or "",
            status="PENDING",
        )
        return Response(_serialize(lr), status=201)


class LeaveRequestListView(APIView):
    """Dashboard: list requests (newest first). ?status=PENDING to filter."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = LeaveRequest.objects.select_related("technician").order_by("-created_at")
        # scope to the logged-in supervisor's own group
        group = getattr(request.user, "supervised_group", None)
        if group is not None:
            qs = qs.filter(technician__group=group)
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter.upper())
        data = [_serialize(lr) for lr in qs[:50]]
        pending_qs = LeaveRequest.objects.filter(status="PENDING")
        if group is not None:
            pending_qs = pending_qs.filter(technician__group=group)
        pending = pending_qs.count()
        return Response({"requests": data, "pending_count": pending})


class LeaveRequestDecisionView(APIView):
    """Dashboard: APPROVE / REJECT a pending request, or RETURN a tech to duty."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        lr = LeaveRequest.objects.select_related("technician").filter(pk=pk).first()
        if lr is None:
            return Response({"error": "Leave request not found."}, status=404)

        # a supervisor may only decide on requests from their own group
        group = getattr(request.user, "supervised_group", None)
        if group is not None and lr.technician.group_id != group.id:
            return Response(
                {"error": "This request belongs to another supervisor's group."},
                status=403)

        decision = (request.data.get("decision") or "").upper()
        tech = lr.technician

        if decision == "APPROVE":
            # The worker keeps working through the advance-notice period. We only
            # record the approval + dates here -- we do NOT flip is_available and
            # do NOT reassign now. The worker is excluded from scheduling ONLY on
            # the actual leave dates, handled per-day by solve_month.
            lr.status = "APPROVED"
        elif decision == "REJECT":
            lr.status = "REJECTED"
        elif decision == "RETURN":
            # bring the technician back on duty (clears any global unavailability)
            lr.status = "RETURNED"
            tech.is_available = True
            tech.save(update_fields=["is_available"])
        else:
            return Response({"error": "decision must be APPROVE, REJECT or RETURN."}, status=400)

        lr.decided_at = timezone.now()
        lr.save()
        payload = _serialize(lr)
        return Response(payload)
