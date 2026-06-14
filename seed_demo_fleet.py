"""
seed_demo_fleet.py
=============================================================================
Builds the demo fleet for the dashboard:

  - 10 technicians:
        6 elevator maintainers  (3 Europe, 3 Asia)
        1 escalator maintainer  (Europe)
        3 fault technicians     (1 Europe, 2 Asia)  -> start EMPTY (they get
                                                        faults via dispatch)
  - 100 units (80 elevator, 20 escalator; 50 Europe, 50 Asia)
  - 30 planned maintenance tasks for the maintainers
  - Gurobi assigns tasks (skill + region + capacity), then Gurobi orders each
    technician's stops into the shortest route (AA first).

Region is derived from longitude (Bosphorus split ~29.02E): coordinates are
generated to fall cleanly on one side, so no schema change is needed.

Run (after migrate):   python seed_demo_fleet.py

All technician logins use password: demo12345
=============================================================================
"""
import os
import random
from datetime import timedelta

import django
from django.utils import timezone

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "capstone.settings")
django.setup()

from django.contrib.auth import get_user_model
from api.models import (
    SupervisorGroup, Technician, Unit, TaskType, Task, PlanningPeriod,
    Schedule, OptimizationRun,
    UnitType, TechnicianRole, SpecialtyType, OperationType, TaskStatus,
)
from api.services.optimization.routing import optimal_open_route

User = get_user_model()
random.seed(7)

REGION_THRESHOLD = 29.02
def region_of(lng):
    return "ASIA" if float(lng) >= REGION_THRESHOLD else "EUROPE"

PASSWORD = "demo12345"


# ---------------------------------------------------------------------------
def reset():
    print("Cleaning old schedules / tasks / runs ...")
    Schedule.objects.all().delete()
    Task.objects.all().delete()
    OptimizationRun.objects.all().delete()


def base():
    admin, _ = User.objects.get_or_create(username="admin_test",
                                          defaults={"first_name": "Demo", "last_name": "Supervisor"})
    group, _ = SupervisorGroup.objects.get_or_create(
        code="IST-01", defaults={"name": "Istanbul Region", "supervisor": admin})
    today = timezone.now().date()
    period, _ = PlanningPeriod.objects.get_or_create(
        start_date=today, end_date=today + timedelta(days=7),
        defaults={"name": "Demo Fleet Week", "created_by": admin})
    return admin, group, period


def make_technicians(group):
    """Returns list of (Technician, region) tuples."""
    print("Creating 10 technicians ...")
    # (key, full_name, role, specialty, depot_lat, depot_lng)
    # username, full_name, role, specialty, depot_lat, depot_lng
    # (usernames stay the same so logins don't change; only the display name is real now)
    specs = [
        # 6 elevator maintainers
        ("elev_m1", "Ahmet Yılmaz",  TechnicianRole.MAINTENANCE, SpecialtyType.ELEVATOR, 41.05, 28.97),
        ("elev_m2", "Mehmet Demir",  TechnicianRole.MAINTENANCE, SpecialtyType.ELEVATOR, 41.07, 28.99),
        ("elev_m3", "Mustafa Kaya",  TechnicianRole.MAINTENANCE, SpecialtyType.ELEVATOR, 41.03, 28.95),
        ("elev_m4", "Emre Şahin",    TechnicianRole.MAINTENANCE, SpecialtyType.ELEVATOR, 40.99, 29.10),
        ("elev_m5", "Burak Aydın",   TechnicianRole.MAINTENANCE, SpecialtyType.ELEVATOR, 41.01, 29.08),
        ("elev_m6", "Kerem Çelik",   TechnicianRole.MAINTENANCE, SpecialtyType.ELEVATOR, 40.97, 29.12),
        # 1 escalator maintainer (Europe)
        ("esc_m1",  "Hakan Arslan",  TechnicianRole.MAINTENANCE, SpecialtyType.ESCALATOR, 41.06, 28.98),
        # 3 fault technicians
        ("fault_1", "Ali Vural",     TechnicianRole.REPAIR, SpecialtyType.BOTH, 41.04, 28.96),
        ("fault_2", "Deniz Koç",     TechnicianRole.REPAIR, SpecialtyType.BOTH, 41.00, 29.09),
        ("fault_3", "Cem Özkan",     TechnicianRole.REPAIR, SpecialtyType.BOTH, 40.98, 29.11),
    ]
    techs = []
    for i, (key, name, role, spec, lat, lng) in enumerate(specs, start=1):
        u, _ = User.objects.get_or_create(username=key, defaults={"first_name": name})
        u.set_password(PASSWORD)
        u.save()
        t, _ = Technician.objects.get_or_create(
            user=u,
            defaults={"employee_code": f"DEMO-{i:02d}", "full_name": name, "group": group})
        t.full_name = name
        t.group = group
        t.tech_role = role
        t.specialty = spec
        t.is_available = True
        t.is_active_employee = True
        t.daily_capacity_min = 480
        t.current_latitude = lat
        t.current_longitude = lng
        t.save()
        techs.append((t, region_of(lng)))

    # Deactivate any technician not part of this demo fleet (old scenario leftovers
    # like Can/Mehmet/Ahmet), so the dashboard shows exactly these 10 and dispatch
    # only ever considers them.
    Technician.objects.exclude(employee_code__startswith="DEMO-").update(
        is_active_employee=False, is_available=False)
    return techs


def make_units():
    print("Creating 100 units ...")
    units = []
    for i in range(1, 101):
        is_elev = i <= 80                      # 80 elevators, 20 escalators
        europe = (i % 2 == 0)                  # alternate region
        if europe:
            lat = round(random.uniform(40.99, 41.10), 6)
            lng = round(random.uniform(28.86, 28.99), 6)
        else:
            lat = round(random.uniform(40.92, 41.05), 6)
            lng = round(random.uniform(29.05, 29.18), 6)
        utype = UnitType.ELEVATOR if is_elev else UnitType.ESCALATOR
        u, _ = Unit.objects.get_or_create(
            unit_code=f"FU-{i:03d}",
            defaults={
                "unit_name": f"{'Elevator' if is_elev else 'Escalator'} Unit {i:03d}",
                "unit_type": utype,
                "address": f"Demo address {i}",
                "latitude": lat, "longitude": lng,
                "notes": f"Region: {region_of(lng)}",
            })
        # keep coords/type in sync on re-runs
        u.unit_type = utype
        u.latitude = lat
        u.longitude = lng
        u.notes = f"Region: {region_of(lng)}"
        u.save()
        units.append(u)
    return units


def make_task_types():
    elev_c, _ = TaskType.objects.get_or_create(
        code="ELEV-MAINT-C",
        defaults={"name": "Asansör C Bakım", "operation_type": OperationType.MAINTENANCE,
                  "required_specialty": SpecialtyType.ELEVATOR,
                  "required_technician_role": TechnicianRole.MAINTENANCE, "base_duration_min": 45})
    esc_m, _ = TaskType.objects.get_or_create(
        code="ESC-MAINT",
        defaults={"name": "Yürüyen Merdiven Bakım", "operation_type": OperationType.MAINTENANCE,
                  "required_specialty": SpecialtyType.ESCALATOR,
                  "required_technician_role": TechnicianRole.MAINTENANCE, "base_duration_min": 45})
    # used later by the dispatch flow
    TaskType.objects.get_or_create(
        code="ELEV-CALL",
        defaults={"name": "Asansör Arıza (Callback)", "operation_type": OperationType.CALLBACK,
                  "required_specialty": SpecialtyType.ELEVATOR,
                  "required_technician_role": TechnicianRole.REPAIR, "base_duration_min": 60})
    return elev_c, esc_m


def make_tasks(period, admin, units, elev_c, esc_m):
    """30 maintenance tasks: 24 elevator (12 Eur, 12 Asia) + 6 escalator (Eur)."""
    print("Creating 30 maintenance tasks ...")
    elev_units = [u for u in units if u.unit_type == UnitType.ELEVATOR]
    esc_units = [u for u in units if u.unit_type == UnitType.ESCALATOR]

    eur_elev = [u for u in elev_units if region_of(u.longitude) == "EUROPE"]
    asia_elev = [u for u in elev_units if region_of(u.longitude) == "ASIA"]
    eur_esc = [u for u in esc_units if region_of(u.longitude) == "EUROPE"]

    chosen = (random.sample(eur_elev, 12) + random.sample(asia_elev, 12)
              + random.sample(eur_esc, min(6, len(eur_esc))))

    tasks = []
    for i, u in enumerate(chosen, start=1):
        tt = elev_c if u.unit_type == UnitType.ELEVATOR else esc_m
        t = Task.objects.create(
            task_no=f"FT-{i:03d}", unit=u, task_type=tt, planning_period=period,
            created_by=admin, estimated_duration_min=tt.base_duration_min,
            status=TaskStatus.PENDING, is_active=True)
        tasks.append(t)
    return tasks


# ---------------------------------------------------------------------------
def gurobi_assign(techs, tasks):
    """
    Gurobi: assign each task to at most one ELIGIBLE technician (skill +
    region + capacity), maximizing served tasks. Returns {tech_id: [tasks]}.
    Fault technicians are excluded (they take dispatched faults, not planned
    maintenance). Falls back to greedy if Gurobi is unavailable.
    """
    maintainers = [(t, r) for (t, r) in techs if t.tech_role == TechnicianRole.MAINTENANCE]

    def eligible(tech, region, task):
        spec_ok = (tech.specialty == task.task_type.required_specialty
                   or tech.specialty == SpecialtyType.BOTH)
        region_ok = (region == region_of(task.unit.longitude))
        return spec_ok and region_ok

    try:
        import gurobipy as gp
        from gurobipy import GRB

        m = gp.Model("fleet_assignment")
        m.setParam("OutputFlag", 1)          # show Gurobi log in the terminal
        m.setParam("TimeLimit", 30)

        pairs = [(ti, j) for ti, (tech, reg) in enumerate(maintainers)
                 for j, task in enumerate(tasks) if eligible(tech, reg, task)]
        x = m.addVars(pairs, vtype=GRB.BINARY, name="x")
        unserved = m.addVars(range(len(tasks)), vtype=GRB.BINARY, name="unserved")

        # each task: assigned to <=1 eligible tech, or unserved
        for j in range(len(tasks)):
            m.addConstr(gp.quicksum(x[ti, j] for (ti, jj) in pairs if jj == j)
                        + unserved[j] == 1)
        # capacity per technician
        for ti, (tech, reg) in enumerate(maintainers):
            m.addConstr(
                gp.quicksum(tasks[j].estimated_duration_min * x[ti, j]
                            for (tii, j) in pairs if tii == ti)
                <= tech.daily_capacity_min)

        # Balance the load: penalize the busiest technician's stop count so
        # Gurobi spreads jobs evenly (~4 each) instead of dumping 10 on one person.
        maxload = m.addVar(vtype=GRB.INTEGER, lb=0, name="maxload")
        for ti, (tech, reg) in enumerate(maintainers):
            m.addConstr(gp.quicksum(x[ti, j] for (tii, j) in pairs if tii == ti) <= maxload)

        m.setObjective(
            10 * gp.quicksum(x[ti, j] for (ti, j) in pairs)
            - 50 * gp.quicksum(unserved[j] for j in range(len(tasks)))
            - 1 * maxload,
            GRB.MAXIMIZE)
        m.optimize()

        result = {tech.id: [] for tech, _ in maintainers}
        for (ti, j) in pairs:
            if x[ti, j].X > 0.5:
                result[maintainers[ti][0].id].append(tasks[j])
        return result

    except Exception as e:
        print(f"(Gurobi unavailable: {e} -> greedy fallback)")
        result = {tech.id: [] for tech, _ in maintainers}
        load = {tech.id: 0 for tech, _ in maintainers}
        for task in tasks:
            cands = [(tech, r) for (tech, r) in maintainers if eligible(tech, r, task)]
            cands = [c for c in cands if load[c[0].id] + task.estimated_duration_min <= c[0].daily_capacity_min]
            if not cands:
                continue
            tech = min(cands, key=lambda c: load[c[0].id])[0]
            result[tech.id].append(task)
            load[tech.id] += task.estimated_duration_min
        return result


def write_routes(techs, assignment, period, admin):
    print("Routing each technician (Gurobi TSP) and writing schedules ...")
    run = OptimizationRun.objects.create(planning_period=period, triggered_by=admin, status="FEASIBLE")
    tech_by_id = {t.id: (t, r) for (t, r) in techs}

    for tech_id, task_list in assignment.items():
        if not task_list:
            continue
        tech, _ = tech_by_id[tech_id]
        depot = (float(tech.current_latitude), float(tech.current_longitude))
        stops = [{
            "id": t.id,
            "lat": float(t.unit.latitude),
            "lng": float(t.unit.longitude),
            "is_aa": (t.priority or "").upper() == "AA",
            "payload": t,
        } for t in task_list]

        ordered, _km = optimal_open_route(depot, stops)

        start = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        for seq, s in enumerate(ordered, start=1):
            task = s["payload"]
            end = start + timedelta(minutes=task.estimated_duration_min)
            Schedule.objects.create(
                task=task, technician=tech, optimization_run=run,
                start_time=start, end_time=end, sequence_order=seq, source="AUTO")
            task.status = TaskStatus.ASSIGNED
            task.save()
            start = end + timedelta(minutes=15)


def run():
    reset()
    admin, group, period = base()
    techs = make_technicians(group)
    units = make_units()
    elev_c, esc_m = make_task_types()
    tasks = make_tasks(period, admin, units, elev_c, esc_m)

    print("\nRunning Gurobi assignment ...")
    assignment = gurobi_assign(techs, tasks)
    write_routes(techs, assignment, period, admin)

    print("\n" + "=" * 60)
    print("FLEET READY")
    print("=" * 60)
    for (t, r) in techs:
        n = Schedule.objects.filter(technician=t).count()
        print(f"  {t.full_name:20s} [{t.tech_role:11s}/{t.specialty:9s}] {r:6s} -> {n} stops")
    print("=" * 60)
    print(f"  Units: {Unit.objects.count()}   Tasks: {Task.objects.count()}   "
          f"Schedules: {Schedule.objects.count()}")
    print("=" * 60)
    print("  All technician logins use password: demo12345")
    print("  e.g.  elev_m1 / demo12345   |   fault_2 / demo12345")


if __name__ == "__main__":
    run()