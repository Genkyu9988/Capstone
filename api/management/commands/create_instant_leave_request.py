"""
api/management/commands/create_instant_leave_request.py
=============================================================================
Console helper for the instant/emergency leave demo.

Example:
    python manage.py create_instant_leave_request --technician "Anıl Dinç2" --days 1 --reason "Car crash during route"
    python manage.py create_instant_leave_request --technician "Anıl Dinç2" --end 2026-06-30 --reason "Emergency leave"

Rules:
    * Uses the admin/simulation roll date as the start date.
    * No 14-day notice rule.
    * Maximum interval remains 7 calendar days.
    * Creates a PENDING LeaveRequest; supervisor approves/rejects in dashboard.
=============================================================================
"""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError

from api.models import LeaveRequest, Technician, TechnicianRole
from api.services.leave_rules import (
    get_operating_date,
    parse_iso_date,
    validate_instant_leave_window,
)


class Command(BaseCommand):
    help = "Create an instant/emergency leave request for a maintenance/callback technician."

    def add_arguments(self, parser):
        parser.add_argument("--technician", required=True, help="Technician full name search text.")
        parser.add_argument("--days", type=int, default=1, help="Leave length in days. Max 7.")
        parser.add_argument("--end", default=None, help="Optional end date YYYY-MM-DD.")
        parser.add_argument("--reason", default="Instant emergency leave", help="Reason shown to supervisor.")

    def handle(self, *args, **opts):
        matches = list(
            Technician.objects
            .filter(full_name__icontains=opts["technician"])
            .order_by("id")[:10]
        )
        if not matches:
            raise CommandError(f"No technician found matching '{opts['technician']}'.")
        if len(matches) > 1:
            names = ", ".join(f"#{t.id} {t.full_name}" for t in matches)
            self.stdout.write(self.style.WARNING(f"Multiple matches found, using first: {names}"))

        tech = matches[0]
        if tech.tech_role not in (TechnicianRole.MAINTENANCE, TechnicianRole.CALLBACK):
            raise CommandError("Instant leave requests are supported for MAINTENANCE and CALLBACK technicians only.")
        if not tech.is_active_employee:
            raise CommandError("Technician is inactive/removed; create leave only for active employees.")

        start = get_operating_date()
        if opts.get("end"):
            end = parse_iso_date(opts["end"], field_name="end")
        else:
            days = int(opts.get("days") or 1)
            end = start + timedelta(days=days - 1)

        try:
            validate_instant_leave_window(start, end, today=start)
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
            leave_type="Instant Leave",
            start_date=start,
            end_date=end,
            reason=opts.get("reason") or "Instant emergency leave",
            status=LeaveRequest.LeaveStatus.PENDING,
        )

        self.stdout.write(self.style.SUCCESS(
            f"Instant LeaveRequest #{req.id} created: {tech.full_name} | {start} -> {end} | "
            f"group={tech.group.name if tech.group else '-'} | status=PENDING"
        ))
        self.stdout.write(
            "Open Supervisor Dashboard -> Leave Requests tab to approve/reject. "
            "On approval, same-day remaining tasks and future schedules in the technician role domain will be rebuilt with Gurobi."
        )
