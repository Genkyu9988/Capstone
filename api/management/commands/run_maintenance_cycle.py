"""
api/management/commands/run_maintenance_cycle.py
=============================================================================
Real A/B/C maintenance cycle, driven by per-unit UnitMaintenanceState.

Two modes:

  --init
      Initialize maintenance state for every unit, with last-maintenance dates
      STAGGERED into the past so units come due on different days (so day-to-day
      the load is spread, not all-due-at-once). Run this ONCE after seeding.

  (default, for a date)
      For the given --date (default today), compute which units in each
      maintenance group's zone are DUE, generate the appropriate A/B/C task
      (highest type, A>B>C supersedes), and assign it to that group.

Cycle (from constraints doc):
    C : every 30 days   (45 min)
    B : every 182 days  (2 h = 120 min)
    A : every 365 days  (4 h = 240 min)

Completion / advancing the clock is done by the solver/dispatch when a task is
marked done (call state.complete(mtype, date)); see complete_tasks command.

Usage:
    python manage.py run_maintenance_cycle --init
    python manage.py run_maintenance_cycle --date 2026-06-12
    python manage.py solve_group "Ahmet Yılmaz Group"
=============================================================================
"""
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api.models import (
    Unit, UnitMaintenanceState, Task, TaskType, PlanningPeriod,
    OperationType, MaintenanceType, SpecialtyType, UnitType,
    TechnicianRole, TaskStatus,
)

DUR = {"A": 240, "B": 120, "C": 45}
INTERVAL = {"A": 365, "B": 182, "C": 30}


class Command(BaseCommand):
    help = "Run the real A/B/C maintenance cycle from per-unit state."

    def add_arguments(self, parser):
        parser.add_argument("--init", action="store_true",
                            help="Initialize staggered maintenance state for all units.")
        parser.add_argument("--date", type=str, default=None,
                            help="Cycle date YYYY-MM-DD (default today).")

    def handle(self, *args, **opts):
        if opts["init"]:
            return self._init()
        the_date = (date.fromisoformat(opts["date"]) if opts["date"] else date.today())
        return self._generate(the_date)

    # ---------------------------------------------------------------- init
    def _init(self):
        """Seed maintenance clocks on WEEKDAYS only, phase-aligned.

        Intervals are whole weeks (28/168/336), so a unit's due-date always
        falls on the same weekday as its last-maintenance date. By seeding every
        clock on Mon-Fri, no unit can ever come due on a weekend. B and A stay
        nested on C boundaries (B = 6 C-cycles, A = 12 C-cycles).
        """
        C_WEEKS = UnitMaintenanceState.C_DAYS // 7   # 4
        B_WEEKS = UnitMaintenanceState.B_DAYS // 7   # 24
        A_WEEKS = UnitMaintenanceState.A_DAYS // 7   # 48

        today = date.today()

        def weekday_anchor(weekday, weeks_ago):
            # most recent `weekday` (0=Mon..4=Fri) on/before today, minus weeks_ago weeks
            delta = (today.weekday() - weekday) % 7
            return today - timedelta(days=delta) - timedelta(weeks=weeks_ago)

        units = list(Unit.objects.filter(is_active=True))
        self.stdout.write(f"Initializing maintenance state for {len(units)} units...")
        created = 0
        for i, u in enumerate(units):
            weekday = i % 5                 # Mon..Fri -> never a weekend
            pw = (i // 5) % A_WEEKS         # week-phase across the yearly cycle
            last_a = weekday_anchor(weekday, pw)
            last_b = weekday_anchor(weekday, pw % B_WEEKS)
            last_c = weekday_anchor(weekday, pw % C_WEEKS)
            UnitMaintenanceState.objects.update_or_create(
                unit=u,
                defaults={"last_a_date": last_a, "last_b_date": last_b,
                          "last_c_date": last_c},
            )
            created += 1
        self.stdout.write(self.style.SUCCESS(
            f"Initialized {created} unit maintenance states (weekday-aligned)."))

    # ------------------------------------------------------------ generate
    def _generate(self, on_date):
        creator = User.objects.filter(is_superuser=True).first() or User.objects.first()

        # one shared planning period for the date
        period = PlanningPeriod.objects.filter(start_date=on_date, end_date=on_date).first()
        if period is None:
            period = PlanningPeriod.objects.create(
                name=f"Cycle {on_date.isoformat()}", start_date=on_date,
                end_date=on_date, is_active=True, created_by=creator)

        # task types per (mtype, specialty)
        def get_tt(mtype, specialty):
            code = f"MNT-{mtype}-{'ESC' if specialty == SpecialtyType.ESCALATOR else 'ELEV'}"
            tt, _ = TaskType.objects.update_or_create(
                code=code,
                defaults={"name": f"{mtype} Bakimi", "operation_type": OperationType.MAINTENANCE,
                          "maintenance_type": getattr(MaintenanceType, mtype),
                          "required_specialty": specialty,
                          "required_technician_role": TechnicianRole.MAINTENANCE,
                          "base_duration_min": DUR[mtype], "is_active": True})
            return tt

        # iterate units that already have a group assignment via existing tasks'
        # zone — but zone ownership lives on the Task.assigned_group from the seed.
        # So we re-use the existing maintenance tasks' unit->group mapping:
        # simplest: a unit's group = the assigned_group of any prior MNT task for it.
        from api.models import Task as T
        unit_group = {}
        for t in T.objects.filter(task_no__startswith="MNT-").select_related("unit", "assigned_group"):
            if t.unit_id not in unit_group and t.assigned_group_id:
                unit_group[t.unit_id] = t.assigned_group

        counts = {"A": 0, "B": 0, "C": 0}
        states = (UnitMaintenanceState.objects
                  .select_related("unit").all())
        for st in states:
            mtype = st.due_type(on_date)
            if mtype is None:
                continue
            g = unit_group.get(st.unit_id)
            if g is None:
                continue  # unit not in any maintenance zone (e.g. callback area)
            unit = st.unit
            specialty = (SpecialtyType.ESCALATOR if unit.unit_type == UnitType.ESCALATOR
                         else SpecialtyType.ELEVATOR)
            tt = get_tt(mtype, specialty)
            Task.objects.update_or_create(
                task_no=f"MNT-{mtype}-{g.code}-{unit.unit_code}",
                defaults={"unit": unit, "planning_period": period, "task_type": tt,
                          "created_by": creator, "assigned_group": g,
                          "description": f"{mtype} maintenance for {unit.unit_name}",
                          "status": TaskStatus.PENDING, "priority": None,
                          "estimated_duration_min": DUR[mtype],
                          "release_time": timezone.now(), "is_active": True})
            counts[mtype] += 1

        self.stdout.write(self.style.SUCCESS(
            f"Cycle {on_date}: generated A={counts['A']} B={counts['B']} C={counts['C']} "
            f"(total {sum(counts.values())}) tasks."))
        self.stdout.write("Next: python manage.py solve_group \"<Maintenance Group Name>\"")
