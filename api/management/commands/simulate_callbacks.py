"""
api/management/commands/simulate_callbacks.py
=============================================================================
Callback (breakdown) simulation for the CALLBACK headquarters.

Unlike maintenance (a fixed cycle), callbacks are RANDOM breakdowns that arrive
through the day. A callback tech is dispatched to the nearest one and must meet
a response-time SLA:

    AA  (people trapped)  -> reach within 1 hour
    other fault types     -> reach within 4 hours

The breakdown RATE is not in the constraints doc, so we use a realistic
industry figure (~1.5 callbacks / unit / year), tunable via --rate.

Two modes:
  --day [YYYY-MM-DD]   detailed single day: each callback, dispatch, response, SLA
  (default)            year summary: daily counts + SLA hit-rates

Dispatch model: each callback goes to the nearest callback tech in the SAME
region (Europe/Asia) who is free at that time; response time = travel time from
the tech's position (HQ or previous job) at ~30 km/h road speed.

Usage:
    python manage.py simulate_callbacks --day 2026-06-12
    python manage.py simulate_callbacks --rate 1.5
=============================================================================
"""
import math
import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from api.models import (
    SupervisorGroup, Technician, Unit, TechnicianRole,
)

BOSPHORUS_LNG = 29.02
ROAD_FACTOR = 1.35
SPEED_KMH = 30.0
AA_FRACTION = 0.15          # ~15% of callbacks are entrapments (AA, 1h SLA)
AA_SLA_MIN = 60
OTHER_SLA_MIN = 240
FAULT_TYPES = ["Entrapment(AA)", "Motor", "Door", "Power", "Other"]
WEEKEND_TECHS = 2           # doc: 2 callback techs on weekend standby (per region)
WEEKNIGHT_TECHS = 1         # doc: 1 callback tech on weeknight standby
WEEKEND_RATE_FACTOR = 0.3   # weekends have lower building usage -> fewer callbacks


def km(a, b, c, d):
    return math.sqrt(((a - c) * 111) ** 2 + ((b - d) * 85) ** 2)


def region(lng):
    return "Europe" if float(lng) < BOSPHORUS_LNG else "Asia"


class Command(BaseCommand):
    help = "Simulate random callbacks and nearest-tech dispatch with SLA tracking."

    def add_arguments(self, parser):
        parser.add_argument("--day", type=str, nargs="?", const="today", default=None,
                            help="Detailed single-day mode (optional YYYY-MM-DD).")
        parser.add_argument("--rate", type=float, default=1.5,
                            help="Callbacks per unit per year (default 1.5).")
        parser.add_argument("--days", type=int, default=365,
                            help="Days to simulate in year mode (default 365).")
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--weekend-rate", type=float, default=WEEKEND_RATE_FACTOR,
                            help="Weekend callback volume as a fraction of weekday "
                                 "(default 0.3). Weekends use only 2 techs/region.")

    def handle(self, *args, **opts):
        random.seed(opts["seed"])

        # callback techs by region (their HQ = current_lat/lng from seed)
        cb_techs = list(Technician.objects.filter(
            tech_role=TechnicianRole.CALLBACK,
            current_latitude__isnull=False).select_related("group", "user"))
        if not cb_techs:
            raise CommandError(
                "No located callback technicians. Run seed_deployment first.")

        techs_by_region = {"Europe": [], "Asia": []}
        for t in cb_techs:
            techs_by_region[region(t.current_longitude)].append(t)

        # units by region (potential breakdown sites)
        units = list(Unit.objects.filter(is_active=True)
                     .values("id", "unit_code", "unit_name", "latitude", "longitude"))
        units_by_region = {"Europe": [], "Asia": []}
        for u in units:
            units_by_region[region(u["longitude"])].append(u)

        rate = opts["rate"]
        # expected callbacks per region per day
        exp_per_day = {r: len(units_by_region[r]) * rate / 365.0
                       for r in ("Europe", "Asia")}

        self.stdout.write(self.style.SUCCESS("=== CALLBACK SIMULATION ==="))
        for r in ("Europe", "Asia"):
            self.stdout.write(
                f"{r}: {len(units_by_region[r])} units, "
                f"{len(techs_by_region[r])} callback techs, "
                f"~{exp_per_day[r]:.1f} callbacks/day expected")
        self.stdout.write("")

        if opts["day"] is not None:
            d = (date.today() if opts["day"] == "today"
                 else date.fromisoformat(opts["day"]))
            self._detailed_day(d, units_by_region, techs_by_region, exp_per_day)
        else:
            self._year(units_by_region, techs_by_region, exp_per_day, opts["days"],
                       opts["weekend_rate"])

    # ----------------------------------------------------------- detailed day
    def _detailed_day(self, d, units_by_region, techs_by_region, exp_per_day):
        self.stdout.write(self.style.SUCCESS(f"--- DETAILED DAY: {d} ---"))
        self.stdout.write(
            f"{'time':>5} {'reg':>6} {'type':>14} {'unit':>10} "
            f"{'tech':>18} {'resp':>5} {'SLA':>4}")
        self.stdout.write("-" * 70)

        for r in ("Europe", "Asia"):
            n = self._poisson(exp_per_day[r])
            techs = techs_by_region[r]
            units = units_by_region[r]
            if not techs or not units or n == 0:
                continue
            # tech availability: minute-of-day each becomes free
            free_at = {t.id: 8 * 60 for t in techs}   # start at 08:00
            tech_pos = {t.id: (float(t.current_latitude), float(t.current_longitude))
                        for t in techs}
            # generate n callbacks at random times 08:00-20:00, random units
            events = []
            for _ in range(n):
                minute = random.randint(8 * 60, 20 * 60)
                u = random.choice(units)
                is_aa = random.random() < AA_FRACTION
                ftype = "Entrapment(AA)" if is_aa else random.choice(FAULT_TYPES[1:])
                events.append((minute, u, is_aa, ftype))
            events.sort(key=lambda e: e[0])

            for minute, u, is_aa, ftype in events:
                ulat, ulng = float(u["latitude"]), float(u["longitude"])
                # choose nearest tech free by this time (or soonest free)
                best = None
                for t in techs:
                    tlat, tlng = tech_pos[t.id]
                    dist = km(ulat, ulng, tlat, tlng) * ROAD_FACTOR
                    travel = dist / SPEED_KMH * 60.0
                    ready = max(minute, free_at[t.id])
                    resp = (ready - minute) + travel
                    if best is None or resp < best[0]:
                        best = (resp, travel, t)
                resp, travel, t = best
                # update tech state
                service = 60   # assume ~1h on site
                free_at[t.id] = minute + resp + service
                tech_pos[t.id] = (ulat, ulng)
                sla = AA_SLA_MIN if is_aa else OTHER_SLA_MIN
                ok = "OK" if resp <= sla else "MISS"
                hh, mm = divmod(minute, 60)
                name = (t.user.get_full_name() if t.user else t.employee_code) or t.employee_code
                self.stdout.write(
                    f"{hh:02d}:{mm:02d} {r:>6} {ftype:>14} {u['unit_code']:>10} "
                    f"{name[:18]:>18} {resp:>4.0f}m {ok:>4}")
        self.stdout.write("-" * 70)

    # ----------------------------------------------------------------- year
    def _year(self, units_by_region, techs_by_region, exp_per_day, days, weekend_rate):
        self.stdout.write(self.style.SUCCESS(f"--- YEAR SUMMARY ({days} days) ---"))
        self.stdout.write(
            f"{'Day':>4} {'Dow':>4} {'callbacks':>10} {'AA':>4} {'AA<1h':>6} "
            f"{'oth<4h':>7} {'misses':>7}")
        self.stdout.write("-" * 56)
        tot = {"cb": 0, "aa": 0, "aa_ok": 0, "oth_ok": 0, "miss": 0,
               "wk_miss": 0, "wkend_miss": 0}
        start = date.today()
        for day in range(days):
            d = start + timedelta(days=day)
            is_weekend = d.weekday() >= 5
            day_cb = day_aa = day_aa_ok = day_oth_ok = day_miss = 0
            for r in ("Europe", "Asia"):
                full_techs = techs_by_region[r]
                if not full_techs or not units_by_region[r]:
                    continue
                # WEEKEND: only 2 techs on duty + reduced callback volume
                if is_weekend:
                    techs = full_techs[:WEEKEND_TECHS]
                    n = self._poisson(exp_per_day[r] * weekend_rate)
                else:
                    techs = full_techs
                    n = self._poisson(exp_per_day[r])
                units = units_by_region[r]
                free_at = {t.id: 8 * 60 for t in techs}
                tech_pos = {t.id: (float(t.current_latitude), float(t.current_longitude))
                            for t in techs}
                events = []
                for _ in range(n):
                    minute = random.randint(8 * 60, 20 * 60)
                    u = random.choice(units)
                    is_aa = random.random() < AA_FRACTION
                    events.append((minute, u, is_aa))
                events.sort(key=lambda e: e[0])
                for minute, u, is_aa in events:
                    ulat, ulng = float(u["latitude"]), float(u["longitude"])
                    best = None
                    for t in techs:
                        tlat, tlng = tech_pos[t.id]
                        dist = km(ulat, ulng, tlat, tlng) * ROAD_FACTOR
                        travel = dist / SPEED_KMH * 60.0
                        ready = max(minute, free_at[t.id])
                        resp = (ready - minute) + travel
                        if best is None or resp < best[0]:
                            best = (resp, t)
                    resp, t = best
                    free_at[t.id] = minute + resp + 60
                    tech_pos[t.id] = (ulat, ulng)
                    day_cb += 1
                    sla = AA_SLA_MIN if is_aa else OTHER_SLA_MIN
                    ok = resp <= sla
                    if is_aa:
                        day_aa += 1
                        if ok:
                            day_aa_ok += 1
                        else:
                            day_miss += 1
                    else:
                        if ok:
                            day_oth_ok += 1
                        else:
                            day_miss += 1
                            
            tot["cb"] += day_cb; tot["aa"] += day_aa
            tot["aa_ok"] += day_aa_ok; tot["oth_ok"] += day_oth_ok; tot["miss"] += day_miss
            if is_weekend:
                tot["wkend_miss"] += day_miss
            else:
                tot["wk_miss"] += day_miss
            dow = d.strftime("%a")
            # print every 30th day, plus any day with a miss, plus weekends in first 2 weeks
            if day % 30 == 0 or day_miss > 0 or (is_weekend and day < 14):
                tag = " <-- WEEKEND (2 techs)" if is_weekend else ""
                self.stdout.write(
                    f"{day:>4} {dow:>4} {day_cb:>10} {day_aa:>4} {day_aa_ok:>6} "
                    f"{day_oth_ok:>7} {day_miss:>7}{tag}")
        self.stdout.write("-" * 56)
        aa_rate = (100 * tot["aa_ok"] / tot["aa"]) if tot["aa"] else 100
        oth_total = tot["cb"] - tot["aa"]
        oth_rate = (100 * tot["oth_ok"] / oth_total) if oth_total else 100
        self.stdout.write(self.style.SUCCESS(
            f"YEAR TOTAL: {tot['cb']} callbacks ({tot['aa']} AA). "
            f"AA<1h: {aa_rate:.1f}% | other<4h: {oth_rate:.1f}% | misses: {tot['miss']}"))
        self.stdout.write(
            f"  misses on weekdays: {tot['wk_miss']} | "
            f"misses on weekends: {tot['wkend_miss']} "
            f"(weekends run on only {WEEKEND_TECHS} techs/region)")

    @staticmethod
    def _poisson(lam):
        # simple Knuth Poisson for daily count around the expected rate
        L = math.exp(-lam)
        k = 0
        p = 1.0
        while True:
            k += 1
            p *= random.random()
            if p <= L:
                return k - 1
