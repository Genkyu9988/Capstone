# rebalance_specialty.py  —  Fix the specialty gap on the two broken groups.
# Murat Demir (25 elevator-only, 500 escalators uncoverable) and Emre Koc
# (only 6 elevator-capable for 2049 elevators) get all their MAINTENANCE techs
# set to BOTH, matching the healthy groups so every tech can service every unit.
# Persists across --init (Technician table), reversible by re-seeding.
# Run: python manage.py shell -c "exec(open('rebalance_specialty.py', encoding='utf-8').read())"
from collections import Counter
from api.models import SupervisorGroup, Technician, TechnicianRole, SpecialtyType

TARGET_GROUPS = ["Murat Demir Group", "Emre Koç Group"]

for name in TARGET_GROUPS:
    g = SupervisorGroup.objects.filter(name=name).first()
    if not g:
        print(f"!! group not found: {name}")
        continue
    techs = Technician.objects.filter(group=g, tech_role=TechnicianRole.MAINTENANCE)
    before = Counter(techs.values_list("specialty", flat=True))
    n = techs.update(specialty=SpecialtyType.BOTH)
    print(f"{name}: set {n} maintenance techs -> BOTH   (was {dict(before)})")

print("\nDone. Now re-run:")
print("  python manage.py run_simulation_all --start 2026-06-22 --end 2026-07-22 --init")
