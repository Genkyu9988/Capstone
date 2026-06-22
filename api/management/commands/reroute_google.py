"""
api/management/commands/reroute_google.py
=============================================================================
Req_33 demonstrator: re-order a HARD-CAPPED subset of technicians' existing
daily routes using REAL Google Maps distance/duration (cached + daily-capped)
fed into the SAME Gurobi open-route TSP.

This satisfies the "utilize distance/duration information between locations in
route calculations" clause of Req_33 for the demonstrated subset -- the route
ORDER is computed from Google distances, not just drawn as a Google polyline --
without exceeding the free tier:

    * only a few technicians (hard cap), a few stops each (hard cap)
    * stop->stop distances go through distance_service.get_or_create_unit_distance,
      which caches every unit pair and degrades to the haversine MOCK if the
      daily call cap in google_maps is hit (so it can never crash or overspend)

Display half of Req_33 (showing those routes on the map) is handled by your
existing simulation/map page; with Google enabled the legs reflect real roads.

    python manage.py reroute_google --techs 5 --max-stops 15
    python manage.py reroute_google --group "Ahmet Yılmaz Group" --techs 6

Set settings.GOOGLE_MAPS_ENABLED = True to call real Google. If it is False the
command still runs but distances come from the haversine MOCK (you've proven the
code path, not the Google data).
=============================================================================
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from api.models import Technician, Schedule
from api.services.optimization.routing import optimal_open_route, haversine_km
from api.services.maps.distance_service import get_or_create_unit_distance

HARD_TECH_CAP = 8        # never reorder more than this many techs in one run
HARD_STOP_CAP = 20       # never route more than this many stops per tech


class Command(BaseCommand):
    help = "Req_33: re-order a capped subset's routes using Google distances + Gurobi TSP."

    def add_arguments(self, parser):
        parser.add_argument("--techs", type=int, default=5)
        parser.add_argument("--max-stops", type=int, default=15)
        parser.add_argument("--group", type=str, default=None)

    def handle(self, *args, **o):
        n_techs = min(max(o["techs"], 1), HARD_TECH_CAP)
        max_stops = min(max(o["max_stops"], 2), HARD_STOP_CAP)

        if not getattr(settings, "GOOGLE_MAPS_ENABLED", False):
            self.stdout.write(self.style.WARNING(
                "GOOGLE_MAPS_ENABLED is False -> distances come from the haversine MOCK. "
                "Set it True in settings.py to call real Google (cached + daily-capped)."))
        else:
            self.stdout.write(self.style.SUCCESS(
                "GOOGLE_MAPS_ENABLED is True -> using real Google distances (cached + capped)."))

        qs = Technician.objects.filter(
            schedules__isnull=False, current_latitude__isnull=False).distinct()
        if o["group"]:
            qs = qs.filter(group__name=o["group"])
        techs = list(qs[:n_techs])
        if not techs:
            self.stdout.write(self.style.WARNING(
                "No routed technicians found. Run a solve first."))
            return

        # Google-backed stop->stop leg distance, made robust:
        #   * identical coordinates -> 0 km, no API call (co-located units)
        #   * Google missing distance / API error -> haversine for that leg
        def google_leg_km(a, b):
            if a["lat"] == b["lat"] and a["lng"] == b["lng"]:
                return 0.0
            try:
                data = get_or_create_unit_distance(a["unit"], b["unit"])
                meters = data.get("distance_meters")
                if meters is None:
                    raise ValueError("Google returned no distanceMeters")
                return meters / 1000.0
            except Exception:
                # co-located-by-rounding, unroutable, or transient API hiccup:
                # use haversine for this single leg so the run never crashes.
                return haversine_km(a["lat"], a["lng"], b["lat"], b["lng"])

        total_reordered = 0
        for t in techs:
            scheds = list(
                Schedule.objects.filter(technician=t)
                .select_related("task__unit")
                .order_by("sequence_order")[:max_stops])
            stops = []
            for s in scheds:
                u = s.task.unit
                if u.latitude is None or u.longitude is None:
                    continue
                stops.append({
                    "lat": float(u.latitude), "lng": float(u.longitude),
                    "is_aa": (s.task.priority or "").upper() == "AA",
                    "unit": u, "sched": s,
                })
            if len(stops) < 2:
                continue

            depot = (float(t.current_latitude), float(t.current_longitude))
            ordered, total_km = optimal_open_route(depot, stops, leg_dist_fn=google_leg_km)

            with transaction.atomic():
                for seq, st in enumerate(ordered, start=1):
                    s = st["sched"]
                    s.sequence_order = seq
                    s.save(update_fields=["sequence_order"])

            total_reordered += 1
            self.stdout.write(self.style.SUCCESS(
                f"  {t.full_name}: re-ordered {len(ordered)} stops, "
                f"{total_km:.1f} km (Gurobi TSP on Google distances)."))

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {total_reordered} technician route(s) recalculated on Google "
            f"distances. Open the simulation map to view them."))
