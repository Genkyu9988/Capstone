# diag_techs.py  —  READ ONLY. Why are only 19 of Murat's 25 techs used?
# Compares Murat's maintenance roster to a healthy group's, looking for techs
# with null/outlier coordinates that the optimizer can't route to.
# Run: python manage.py shell -c "exec(open('diag_techs.py', encoding='utf-8').read())"
import math
from api.models import SupervisorGroup, Technician, TechnicianRole

def km(la1, ln1, la2, ln2):
    R = 6371.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = math.radians(la2 - la1), math.radians(ln2 - ln1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))

# one-line summary for every maintenance group
print("=== all maintenance groups (available + located) ===")
for g in SupervisorGroup.objects.all().order_by("name"):
    qs = Technician.objects.filter(group=g, tech_role=TechnicianRole.MAINTENANCE,
                                   is_available=True, current_latitude__isnull=False)
    n = qs.count()
    null_lng = qs.filter(current_longitude__isnull=True).count()
    if n:
        print(f"  {g.name:24s} located={n:3d}  null_longitude={null_lng}")

# detailed look at Murat vs a healthy group
for name in ["Murat Demir Group", "Ahmet Yılmaz Group"]:
    g = SupervisorGroup.objects.filter(name=name).first()
    if not g:
        continue
    techs = list(Technician.objects.filter(
        group=g, tech_role=TechnicianRole.MAINTENANCE,
        is_available=True, current_latitude__isnull=False))
    coords = [(t.full_name, float(t.current_latitude),
               None if t.current_longitude is None else float(t.current_longitude))
              for t in techs]
    good = [(nm, la, ln) for nm, la, ln in coords if ln is not None]
    clat = sum(c[1] for c in good) / len(good) if good else 0
    clng = sum(c[2] for c in good) / len(good) if good else 0
    print(f"\n=== {name}: {len(techs)} available+located ===")
    print(f"   centroid = ({clat:.4f}, {clng:.4f})")
    nulls = [nm for nm, la, ln in coords if ln is None]
    if nulls:
        print(f"   !!! NULL longitude ({len(nulls)}): {nulls}")
    dists = sorted(round(km(la, ln, clat, clng), 1) for nm, la, ln in good)
    print(f"   distances from centroid (km): {dists}")
    outliers = [(nm, round(km(la, ln, clat, clng), 1))
                for nm, la, ln in good if km(la, ln, clat, clng) > 15]
    if outliers:
        print(f"   !!! >15km outliers: {outliers}")
    print(f"   distinct coordinate points: {len(set((la, ln) for _, la, ln in good))}")
