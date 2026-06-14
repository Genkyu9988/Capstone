"""
api/management/commands/set_clock.py
=============================================================================
Set the operating clock from the console. Run it, answer the prompt, and the
whole live system (phone + supervisor dashboard) operates as that day/time,
ticking forward in real time.

    python manage.py set_clock
        From which date start the day? (YYYY/MM/DD HH:MM) > 2026/07/07 09:43

Non-interactive / scripted:
    python manage.py set_clock --at "2026/07/07 09:43"

Check or clear:
    python manage.py set_clock --status
    python manage.py set_clock --clear
=============================================================================
"""
from datetime import datetime

from django.core.management.base import BaseCommand

from api.sim_clock import set_clock, clear_clock, now, status

FORMATS = [
    "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d", "%Y-%m-%d",
]


class Command(BaseCommand):
    help = "Set the operating clock (which day/time the live system runs as)."

    def add_arguments(self, parser):
        parser.add_argument("--at", type=str, default=None,
                            help='Non-interactive, e.g. --at "2026/07/07 09:43"')
        parser.add_argument("--clear", action="store_true", help="Unset the clock.")
        parser.add_argument("--status", action="store_true", help="Show current clock.")

    def handle(self, *args, **opts):
        if opts["clear"]:
            clear_clock()
            self.stdout.write(self.style.SUCCESS("Operating clock cleared."))
            return
        if opts["status"]:
            self.stdout.write(status())
            return

        raw = opts["at"]
        if not raw:
            raw = input("From which date start the day? (YYYY/MM/DD HH:MM) > ").strip()

        dt = None
        for fmt in FORMATS:
            try:
                dt = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            self.stderr.write(self.style.ERROR(
                "Could not parse that. Example: 2026/07/07 09:43"))
            return

        set_clock(dt)
        self.stdout.write(self.style.SUCCESS(
            f"Operating clock set. Now = {now().isoformat()}, ticking in real time."))
        self.stdout.write("Both the phone and the supervisor dashboard will follow this.")
