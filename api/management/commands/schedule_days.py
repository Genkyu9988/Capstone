"""
api/management/commands/schedule_days.py
=============================================================================
List the days that actually have schedule data, so you can pick one for the
operating clock (set_clock).

    python manage.py schedule_days                 # all groups
    python manage.py schedule_days --group "Ahmet" # just Ahmet Yılmaz's group

Prints each date with how many technicians and how many stops it holds, the
overall range, and a ready-to-paste set_clock command.
=============================================================================
"""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import Schedule


class Command(BaseCommand):
    help = "List available scheduled days (date -> technicians, stops)."

    def add_arguments(self, parser):
        parser.add_argument("--group", type=str, default=None,
                            help="Filter to a supervisor group name (substring).")

    def handle(self, *args, **opts):
        qs = Schedule.objects.exclude(start_time__isnull=True)
        label = "ALL groups"
        if opts["group"]:
            qs = qs.filter(technician__group__name__icontains=opts["group"])
            label = f"group matching '{opts['group']}'"

        by_day = defaultdict(lambda: {"stops": 0, "techs": set()})
        for start_time, tech_id in qs.values_list("start_time", "technician_id").iterator():
            d = timezone.localtime(start_time).date()
            by_day[d]["stops"] += 1
            by_day[d]["techs"].add(tech_id)

        if not by_day:
            self.stdout.write(self.style.WARNING("No scheduled days found."))
            return

        self.stdout.write(self.style.SUCCESS(f"\nAvailable scheduled days ({label}):\n"))
        total_stops = 0
        for d in sorted(by_day):
            info = by_day[d]
            total_stops += info["stops"]
            self.stdout.write(
                f"  {d.isoformat()} {d.strftime('%a')} | "
                f"{len(info['techs']):>3} techs | {info['stops']:>5} stops")

        days = sorted(by_day)
        self.stdout.write(self.style.SUCCESS(
            f"\n{len(by_day)} day(s), {total_stops} stops total. "
            f"Range: {days[0].isoformat()} .. {days[-1].isoformat()}"))
        self.stdout.write(
            "\nPick one and set the clock, e.g.:\n"
            f'  python manage.py set_clock --at "{days[0].isoformat()} 09:00"\n')
