"""
api/management/commands/simulate_year.py
=============================================================================
Console simulation: roll ONE maintenance group's zone forward day by day for a
full year, so you can watch the A/B/C cycle behave over time.

For each working day it:
  1. computes which of the group's units are DUE (A>B>C supersession),
  2. assigns them to the group's technicians up to daily capacity
     (work hours minus break, minus a rough travel allowance),
  3. completes the assigned ones -> advances their unit clocks,
  4. carries any over-capacity units forward as OVERDUE,
  5. prints a per-day summary.

It uses the SAME UnitMaintenanceState model the real cycle uses, but does the
assignment with a simple capacity rule instead of Gurobi (so a full year runs
in seconds, and you see the cycle pattern, not the routing detail).

This does NOT call the solver and (by default) does NOT write tasks; it works on
an in-memory copy of the unit clocks unless you pass --commit.

Usage:
    python manage.py simulate_year "Ahmet Yılmaz Group"
    python manage.py simulate_year "Ahmet Yılmaz Group" --days 365 --weekly-off
=============================================================================
"""
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from api.models import (
    SupervisorGroup, Technician, Task, UnitMaintenanceState,
    TechnicianRole, MaintenanceType,
)

DUR_MIN = {"A": 240, "B": 120, "C": 45}
INTERVAL = {"A": 365, "B": 182, "C": 30}
WORK_MIN = 8 * 60            # 8 working hours (9h day - 1h break)
TRAVEL_ALLOW = 0.30         # assume ~30% of the day lost to travel between units


class UnitClock:
    """In-memory copy of a unit's maintenance state, for fast simulation."""
    __slots__ = ("uid", "la", "lb", "lc")

    def __init__(self, uid, la, lb, lc):
        self.uid, self.la, self.lb, self.lc = uid, la, lb, lc

    def due_type(self, d):
        def od(last, iv):
            return last is None or (d - last).days >= iv
        if od(self.la, INTERVAL["A"]):
            return "A"
        if od(self.lb, INTERVAL["B"]):
            return "B"
        if od(self.lc, INTERVAL["C"]):
            return "C"
        return None

    def complete(self, mtype, d):
        if mtype == "A":
            self.la = self.lb = self.lc = d
        elif mtype == "B":
            self.lb = self.lc = d
        elif mtype == "C":
            self.lc = d


class Command(BaseCommand):
    help = "Simulate one group's maintenance cycle over a year (console)."

    def add_arguments(self, parser):
        parser.add_argument("group_name", type=str)
        parser.add_argument("--days", type=int, default=365)
        parser.add_argument("--weekly-off", action="store_true",
                            help="No planned maintenance on Sat/Sun (per constraints).")
        parser.add_argument("--start", type=str, default=None,
                            help="Start date YYYY-MM-DD (default today).")

    def _zone_unit_ids(self, group):
        """Units whose NEAREST maintenance HQ is this group's HQ (Voronoi).

        HQ locations are read from each maintenance group's technician
        current_latitude/longitude (set by seed_deployment).
        """
        import math
        from api.models import Unit, SupervisorGroup as SG

        def hq_of(g):
            t = (Technician.objects
                 .filter(group=g, tech_role=TechnicianRole.MAINTENANCE,
                         current_latitude__isnull=False)
                 .first())
            if t is None:
                return None
            return (float(t.current_latitude), float(t.current_longitude))

        # all maintenance-capable groups that have an HQ
        hqs = []
        for g in SG.objects.all():
            has_maint = Technician.objects.filter(
                group=g, tech_role=TechnicianRole.MAINTENANCE).exists()
            if not has_maint:
                continue
            h = hq_of(g)
            if h is not None:
                hqs.append((g.id, h))
        if not hqs:
            return []

        my_hq = hq_of(group)
        if my_hq is None:
            return []

        def km(a, b, c, d):
            return math.sqrt(((a - c) * 111) ** 2 + ((b - d) * 85) ** 2)

        ids = []
        for u in Unit.objects.filter(is_active=True).values(
                "id", "latitude", "longitude"):
            lat, lng = float(u["latitude"]), float(u["longitude"])
            nearest = min(hqs, key=lambda x: km(lat, lng, x[1][0], x[1][1]))
            if nearest[0] == group.id:
                ids.append(u["id"])
        return ids

    def handle(self, *args, **opts):
        group = SupervisorGroup.objects.filter(name=opts["group_name"]).first()
        if group is None:
            raise CommandError(f"Group '{opts['group_name']}' not found.")

        # technicians available (maintenance) in the group
        n_tech = Technician.objects.filter(
            group=group, tech_role=TechnicianRole.MAINTENANCE).count()
        if n_tech == 0:
            raise CommandError("Group has no maintenance technicians.")
        daily_capacity_min = int(n_tech * WORK_MIN * (1 - TRAVEL_ALLOW))

        # the group's zone units = units that have a maintenance task assigned to
        # this group (from the deployment seed / cycle). Build their in-memory clocks.
        unit_ids = list(
            self._zone_unit_ids(group))
        if not unit_ids:
            raise CommandError(
                "No units in this group's zone. Run seed_deployment first "
                "(technician HQ coordinates must be set).")

        states = {s.unit_id: s for s in
                  UnitMaintenanceState.objects.filter(unit_id__in=unit_ids)}
        clocks = []
        for uid in unit_ids:
            s = states.get(uid)
            if s is None:
                clocks.append(UnitClock(uid, None, None, None))
            else:
                clocks.append(UnitClock(uid, s.last_a_date, s.last_b_date, s.last_c_date))

        start = (date.fromisoformat(opts["start"]) if opts["start"] else date.today())
        days = opts["days"]
        weekly_off = opts["weekly_off"]

        self.stdout.write(self.style.SUCCESS(
            f"=== YEAR SIMULATION: {group.name} ==="))
        self.stdout.write(
            f"{len(clocks)} units in zone | {n_tech} techs | "
            f"daily capacity ~{daily_capacity_min} min "
            f"(~{daily_capacity_min // 60}h effective)\n")
        self.stdout.write(
            f"{'Day':>4} {'Date':>10} {'Dow':>4} {'due':>5} {'A':>3} {'B':>3} {'C':>4} "
            f"{'done':>5} {'carry':>6} {'minutes':>8}")
        self.stdout.write("-" * 60)

        carry = set()   # unit indices overdue from previous days
        totals = {"A": 0, "B": 0, "C": 0}

        for day in range(days):
            d = start + timedelta(days=day)
            if weekly_off and d.weekday() >= 5:   # Sat=5, Sun=6
                # No planned maintenance on weekends (per constraints doc).
                # Weekend-due tasks are NOT done -> they carry to Monday.
                waiting = sum(1 for c in clocks if c.due_type(d) is not None)
                dayname = d.strftime("%a")
                self.stdout.write(
                    f"{day:>4} {d.isoformat():>10} {dayname:>4} "
                    f"--- weekend off, {waiting} due tasks waiting for Monday ---")
                continue

            # find all due units today (plus carryover)
            due = []
            for idx, c in enumerate(clocks):
                mt = c.due_type(d)
                if mt is not None:
                    due.append((idx, mt))

            # sort: prioritize bigger/older services first (A, then B, then C)
            order = {"A": 0, "B": 1, "C": 2}
            due.sort(key=lambda x: order[x[1]])

            # assign up to capacity
            used = 0
            done = {"A": 0, "B": 0, "C": 0}
            assigned_idx = []
            for idx, mt in due:
                if used + DUR_MIN[mt] <= daily_capacity_min:
                    used += DUR_MIN[mt]
                    done[mt] += 1
                    assigned_idx.append((idx, mt))
                # else: leave it for a future day (overdue carryover)

            # complete assigned -> advance their clocks
            for idx, mt in assigned_idx:
                clocks[idx].complete(mt, d)
                totals[mt] += 1

            carry_count = len(due) - len(assigned_idx)
            dayname = d.strftime("%a")
            self.stdout.write(
                f"{day:>4} {d.isoformat():>10} {dayname:>4} {len(due):>5} "
                f"{done['A']:>3} {done['B']:>3} {done['C']:>4} "
                f"{len(assigned_idx):>5} {carry_count:>6} {used:>8}")

        self.stdout.write("-" * 60)
        self.stdout.write(self.style.SUCCESS(
            f"YEAR TOTAL completed: A={totals['A']} B={totals['B']} C={totals['C']} "
            f"(total {sum(totals.values())})"))
        self.stdout.write(
            "Note: simulation only; unit clocks in DB are unchanged.")
