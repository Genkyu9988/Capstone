# diag_zone.py  —  READ ONLY.  Finds why a zone reports ~6x its real size.
# Run:  python manage.py shell -c "exec(open('diag_zone.py', encoding='utf-8').read())"
import math
from django.db.models import Count
from api.models import (Unit, UnitMaintenanceState, SupervisorGroup,
                        Technician, TechnicianRole)

def km(la1, ln1, la2, ln2):
    R = 6371.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = math.radians(la2 - la1), math.radians(ln2 - ln1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))

# 1) Are UNITS duplicated?
u_total  = Unit.objects.count()
u_active = Unit.objects.filter(is_active=True).count()
u_codes  = Unit.objects.values("unit_code").distinct().count()
print(f"[UNITS]  total={u_total}  active={u_active}  distinct_codes={u_codes}")
if u_codes and u_total > u_codes * 1.5:
    print(f"   >>> UNITS DUPLICATED  (~{u_total/u_codes:.1f}x per code)  <-- likely cause")

# 2) Are STATE rows duplicated?
s_total = UnitMaintenanceState.objects.count()
s_dup   = (UnitMaintenanceState.objects.values("unit_id")
           .annotate(n=Count("id")).filter(n__gt=1).count())
print(f"[STATE]  rows={s_total}   units_with_>1_state={s_dup}")
if s_dup:
    print("   >>> STATE ROWS DUPLICATED  <-- likely cause")

# 3) HQs as solve_month sees them + resulting Voronoi zone sizes
hqs = {}
for g in SupervisorGroup.objects.all():
    t = (Technician.objects.filter(group=g, tech_role=TechnicianRole.MAINTENANCE,
                                   current_latitude__isnull=False).first())
    if t:
        hqs[g.id] = (g.name, float(t.current_latitude), float(t.current_longitude))
print(f"[HQS]    solve_month sees {len(hqs)} maintenance HQs (expected 8)")
for nm, la, ln in sorted(v for v in hqs.values()):
    print(f"         {nm:24s} ({la:.4f}, {ln:.4f})")

sizes = {gid: 0 for gid in hqs}
for u in Unit.objects.filter(is_active=True, latitude__isnull=False).values("latitude", "longitude"):
    la, ln = float(u["latitude"]), float(u["longitude"])
    nearest = min(hqs.items(), key=lambda kv: km(la, ln, kv[1][1], kv[1][2]))[0]
    sizes[nearest] += 1
print("[ZONES]  Voronoi sizes (what each solve_month run will load):")
for gid, n in sorted(sizes.items(), key=lambda x: -x[1]):
    print(f"         {hqs[gid][0]:24s} {n}")
print(f"         TOTAL zoned = {sum(sizes.values())}")
