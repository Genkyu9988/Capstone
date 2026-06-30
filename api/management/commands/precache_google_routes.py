from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, List, Tuple

from django.core.management.base import BaseCommand, CommandError

from api.models import Schedule
from api.services.maps.route_geometry import build_route_geometry, google_calls_today


class Command(BaseCommand):
    help = (
        "Precompute and cache Google route geometry per active technician-day. "
        "Live map/mobile can then reuse CACHE without calling Google on every poll."
    )

    def add_arguments(self, parser):
        parser.add_argument("start_date", help="YYYY-MM-DD")
        parser.add_argument("end_date", help="YYYY-MM-DD, inclusive")
        parser.add_argument("--group", help="Supervisor group name, optional")
        parser.add_argument(
            "--role",
            choices=["MAINTENANCE", "CALLBACK", "ALL"],
            default="ALL",
            help="Technician role to precompute. Default: ALL",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Maximum technician-day routes to process in this run. 0 = no limit.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only show how many routes would be processed; do not call Google.",
        )
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            help="Include inactive technicians. Default: only active technicians.",
        )
        parser.add_argument(
            "--verbose-routes",
            action="store_true",
            help="Print every technician-day route result.",
        )

    def _parse_date(self, value: str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            raise CommandError(f"Invalid date {value!r}; expected YYYY-MM-DD")

    def handle(self, *args, **opts):
        start = self._parse_date(opts["start_date"])
        end = self._parse_date(opts["end_date"])
        if end < start:
            raise CommandError("end_date must be >= start_date")

        qs = (
            Schedule.objects
            .filter(start_time__date__gte=start, start_time__date__lte=end)
            .select_related("technician", "technician__group", "task", "task__unit", "task__task_type")
            .order_by("start_time__date", "technician__group__name", "technician__full_name", "sequence_order", "start_time")
        )
        if not opts["include_inactive"]:
            qs = qs.filter(technician__is_active_employee=True)
        if opts["group"]:
            qs = qs.filter(technician__group__name=opts["group"])
        if opts["role"] != "ALL":
            qs = qs.filter(technician__tech_role=opts["role"])

        routes: Dict[Tuple[object, int], List[Schedule]] = defaultdict(list)
        for s in qs:
            if not s.technician_id or not s.task_id or not getattr(s.task, "unit", None):
                continue
            unit = s.task.unit
            if unit.latitude is None or unit.longitude is None:
                continue
            routes[(s.start_time.date(), s.technician_id)].append(s)

        items = sorted(
            routes.items(),
            key=lambda kv: (
                kv[0][0],
                kv[1][0].technician.group.name if kv[1][0].technician.group else "",
                kv[1][0].technician.full_name,
            ),
        )
        if opts["limit"] and opts["limit"] > 0:
            items = items[:opts["limit"]]

        self.stdout.write("GOOGLE ROUTE PRECACHE")
        self.stdout.write("=" * 100)
        self.stdout.write(f"Period: {start} -> {end}")
        self.stdout.write(f"Routes to process: {len(items)} technician-days")
        self.stdout.write(f"Google calls already used today before run: {google_calls_today()}")
        self.stdout.write("=" * 100)

        if opts["dry_run"]:
            by_group = Counter()
            by_role = Counter()
            for (_, _), rows in items:
                tech = rows[0].technician
                by_group[tech.group.name if tech.group else "NO_GROUP"] += 1
                by_role[tech.tech_role] += 1
            self.stdout.write("DRY RUN ONLY. No Google calls were made.")
            self.stdout.write("Routes by group:")
            for name, count in sorted(by_group.items()):
                self.stdout.write(f"  {name}: {count}")
            self.stdout.write("Routes by role:")
            for name, count in sorted(by_role.items()):
                self.stdout.write(f"  {name}: {count}")
            return

        counts = Counter()
        failures = []

        for (day, _tech_id), rows in items:
            tech = rows[0].technician
            first_unit = rows[0].task.unit
            if tech.current_latitude is not None and tech.current_longitude is not None:
                origin = (float(tech.current_latitude), float(tech.current_longitude))
            else:
                origin = (float(first_unit.latitude), float(first_unit.longitude))

            stops = [
                {"lat": float(s.task.unit.latitude), "lng": float(s.task.unit.longitude)}
                for s in rows
            ]

            try:
                geom = build_route_geometry(origin, stops, allow_google_call=True)
                source = geom.get("source") or "NONE"
                counts[source] += 1
                if opts["verbose_routes"]:
                    self.stdout.write(
                        f"{day} | {tech.group.name if tech.group else 'NO_GROUP'} | "
                        f"{tech.full_name} | stops={len(stops)} | {source} | "
                        f"km={geom.get('distance_km')} | min={geom.get('duration_min')}"
                    )
            except Exception as exc:
                counts["ERROR"] += 1
                failures.append((day, tech.full_name, str(exc)))
                self.stderr.write(f"ERROR {day} {tech.full_name}: {exc}")

        self.stdout.write("=" * 100)
        self.stdout.write("Finished route precache.")
        for source, count in sorted(counts.items()):
            self.stdout.write(f"{source}: {count}")
        self.stdout.write(f"Google calls used today after run: {google_calls_today()}")

        if failures:
            self.stdout.write("Failures:")
            for day, name, msg in failures[:20]:
                self.stdout.write(f"  {day} | {name} | {msg[:200]}")
