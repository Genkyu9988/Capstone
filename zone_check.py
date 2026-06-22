import math
from api.models import SupervisorGroup, Technician, Unit, TechnicianRole

def km(a, b, c, d):
    return math.sqrt(((a - c) * 111) ** 2 + ((b - d) * 85) ** 2)

hqs, mcount = {}, {}
for g in SupervisorGroup.objects.all():
    t = Technician.objects.filter(group=g, tech_role=TechnicianRole.MAINTENANCE,
                                  current_latitude__isnull=False).first()
    if t:
        hqs[g.id] = (g.name, float(t.current_latitude), float(t.current_longitude))
        mcount[g.id] = Technician.objects.filter(group=g, tech_role=TechnicianRole.MAINTENANCE).count()

zone = {gid: 0 for gid in hqs}
for u in Unit.objects.filter(is_active=True, latitude__isnull=False).values("latitude", "longitude"):
    la, ln = float(u["latitude"]), float(u["longitude"])
    nearest = min(hqs.items(), key=lambda kv: km(la, ln, kv[1][1], kv[1][2]))[0]
    zone[nearest] += 1

print(f"{'Group':<24}{'ZoneUnits':>10}{'Techs':>7}{'Optimal':>9}")
for gid, (name, la, ln) in hqs.items():
    print(f"{name:<24}{zone[gid]:>10}{mcount[gid]:>7}{round(zone[gid] / 100):>9}")