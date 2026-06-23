"""
api/management/commands/create_leave_request.py
=============================================================================
Console helper for demo/testing until the mobile leave request form is added.

Example:
    python manage.py create_leave_request --technician "Ali Aslankan" --start 2026-07-08 --days 7 --reason "Annual leave demo"

The command creates a PENDING LeaveRequest. The supervisor dashboard then shows
it under Leave Requests, where the supervisor can Approve or Reject it.
=============================================================================
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError

from api.models import LeaveRequest, Technician, TechnicianRole
from api.services.leave_rules import (
    get_operating_date,
    parse_iso_date,
    validate_leave_window,
)


class Command(BaseCommand):
    help = "Create a pending maintenance/callback technician leave request from the console."

    def add_arguments(self, parser):
        parser.add_argument("--technician", required=True, help="Technician full name or partial name.")
        parser.add_argument("--start", required=True, help="Leave start date, YYYY-MM-DD.")
        parser.add_argument("--end", default="", help="Leave end date, YYYY-MM-DD. Optional if --days is used.")
        parser.add_argument("--days", type=int, default=1, help="Inclusive leave length in days. Max 7.")
        parser.add_argument("--type", default="Annual Leave", help="Leave type label.")
        parser.add_argument("--reason", default="", help="Reason shown to supervisor.")

    def handle(self, *args, **opts):
        tech_qs = Technician.objects.filter(full_name__icontains=opts["technician"]).order_by("id")
        matches = list(tech_qs[:5])
        if not matches:
            raise CommandError(f"No technician found matching '{opts['technician']}'.")
        if len(matches) > 1:
            names = ", ".join(f"#{t.id} {t.full_name}" for t in matches)
            self.stdout.write(self.style.WARNING(f"Multiple matches found, using first: {names}"))
        tech = matches[0]

        if tech.tech_role not in (TechnicianRole.MAINTENANCE, TechnicianRole.CALLBACK):
            raise CommandError("Leave requests are supported for MAINTENANCE and CALLBACK technicians only.")
        if not tech.is_active_employee:
            raise CommandError("Technician is inactive/removed; create leave only for active employees.")

        start = parse_iso_date(opts["start"], field_name="start")
        if opts.get("end"):
            end = parse_iso_date(opts["end"], field_name="end")
        else:
            days = int(opts.get("days") or 1)
            end = start + timedelta(days=days - 1)

        today = get_operating_date()
        try:
            validate_leave_window(start, end, today=today, enforce_notice=True)
        except ValueError as e:
            raise CommandError(str(e))

        overlapping = LeaveRequest.objects.filter(
            technician=tech,
            status__in=[
                LeaveRequest.LeaveStatus.PENDING,
                LeaveRequest.LeaveStatus.APPROVED,
            ],
            start_date__lte=end,
            end_date__gte=start,
        ).first()
        if overlapping:
            raise CommandError(
                f"Overlapping leave request already exists: #{overlapping.id} "
                f"{overlapping.start_date} to {overlapping.end_date} ({overlapping.status})."
            )

        req = LeaveRequest.objects.create(
            technician=tech,
            leave_type=opts.get("type") or "Annual Leave",
            start_date=start,
            end_date=end,
            reason=opts.get("reason") or "",
            status=LeaveRequest.LeaveStatus.PENDING,
        )

        self.stdout.write(self.style.SUCCESS(
            f"LeaveRequest #{req.id} created: {tech.full_name} | {start} -> {end} | "
            f"group={tech.group.name if tech.group else '-'} | status=PENDING"
        ))
        self.stdout.write(
            "Open Supervisor Dashboard -> Leave Requests tab to approve/reject."
        )
