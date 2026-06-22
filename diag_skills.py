# diag_skills.py  —  READ ONLY. Tech specialty split vs zone unit-type split.
# Reveals specialty mismatches (e.g. elevator-heavy zone, too few elevator techs)
# that leave tasks with no eligible technician.
# Run: python manage.py shell -c "exec(open('diag_skills.py', encoding='utf-8').read())"
import math
from collections import Counter
from api.models import SupervisorGroup, Technician, TechnicianRole, Unit

def km(la1, ln1, la2, ln2):
    R = 6371.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = math.radians(la2 - la1), math.radians(ln2 - ln1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))

hqs = {}
for g in SupervisorGroup.objects.all():
    t = Technician.objects.filter(group=g, tech_role=TechnicianRole.MAINTENANCE,
                                  current_latitude__isnull=False).first()
    if t:
        hqs[g.id] = (g, float(t.current_latitude), float(t.current_longitude))

zone = {gid: Counter() for gid in hqs}
for u in Unit.objects.filter(is_active=True, latitude__isnull=False).values(
        "unit_type", "latitude", "longitude"):
    la, ln = float(u["latitude"]), float(u["longitude"])
    nearest = min(hqs.items(), key=lambda kv: km(la, ln, kv[1][1], kv[1][2]))[0]
    zone[nearest][u["unit_type"]] += 1

print(f"{'GROUP':22s} {'techs E/S/BOTH':16s} {'units ELE/ESC':14s} "
      f"{'can-do-ELE':10s} {'ELE need/day':12s} {'ELE cap/day'}")
for gid, (g, la, ln) in sorted(hqs.items(), key=lambda x: x[1][0].name):
    techs = Technician.objects.filter(group=g, tech_role=TechnicianRole.MAINTENANCE,
                                      is_available=True, current_latitude__isnull=False)
    sp = Counter(techs.values_list("specialty", flat=True))
    ele_t, esc_t, both_t = sp.get("ELEVATOR", 0), sp.get("ESCALATOR", 0), sp.get("BOTH", 0)
    ele_u, esc_u = zone[gid].get("ELEVATOR", 0), zone[gid].get("ESCALATOR", 0)
    can_ele = ele_t + both_t
    can_esc = esc_t + both_t
    ele_need = round(ele_u / 30 * 1.2, 1)   # C-rate + ~20% for B/A
    ele_cap = can_ele * 7                     # ~7 tasks/tech/8h-day
    flag = "  <-- SHORT" if ele_cap < ele_need else ""
    print(f"{g.name:22s} {f'{ele_t}/{esc_t}/{both_t}':16s} {f'{ele_u}/{esc_u}':14s} "
          f"{can_ele:<10d} {ele_need:<12} {ele_cap}{flag}")
    print(f"{'':22s} (escalator: {can_esc} techs can do {esc_u} units = "
          f"~{round(esc_u/30*1.2,1)}/day need)")
