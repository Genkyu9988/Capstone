# rightsize.py
# =============================================================================
# Option A: reduce each maintenance group to its optimal headcount, convert the
# mixed group (Emre Koç) to pure maintenance, keep ZONES FROZEN (no re-seed, no
# k-means). Reversible.
#
# WHY is_active_employee (not just is_available):
#   The live-map / dashboard view filters on is_active_employee=True and treats
#   is_available=False as "on leave". If we sideline with is_available alone,
#   surplus techs still show on the map AND render as bogus "on leave" entries.
#   Sidelining on is_active_employee removes them from the active roster cleanly,
#   keeps the solver excluding them, and leaves is_available free to mean only
#   genuine leave. Fully reversible: flip the flags back (or restore a backup).
#
# Run with:
#   python manage.py shell -c "exec(open('rightsize.py', encoding='utf-8').read())"
# =============================================================================
from api.models import SupervisorGroup, Technician, TechnicianRole

OPTIMAL = {
    "Ahmet Yılmaz Group": 26,
    "Durmuş Bolayır Group": 15,
    "Emre Koç Group": 26,
    "Hakan Polat Group": 24,
    "Mehmet Aksu Group": 28,
    "Murat Demir Group": 25,
    "Okan Şahin Group": 37,
    "Serkan Kaya Group": 19,
}

for gname, keep in OPTIMAL.items():
    g = SupervisorGroup.objects.filter(name=gname).first()
    if not g:
        print(f"!! group not found: {gname}")
        continue

    # 1) make the mixed group (Emre Koç) pure maintenance. No-op for pure groups.
    converted = Technician.objects.filter(
        group=g, tech_role=TechnicianRole.CALLBACK
    ).update(tech_role=TechnicianRole.MAINTENANCE)

    maint = list(Technician.objects.filter(
        group=g, tech_role=TechnicianRole.MAINTENANCE).order_by("id"))

    # 2) make sure every maintenance tech is located (fill blanks from a peer).
    loc = next((t for t in maint if t.current_latitude is not None), None)
    if loc:
        for t in maint:
            if t.current_latitude is None:
                t.current_latitude = loc.current_latitude
                t.current_longitude = loc.current_longitude
                t.save(update_fields=["current_latitude", "current_longitude"])

    # 3) keep the first `keep` as the ACTIVE roster, sideline the rest.
    #    active    -> is_active_employee=True,  is_available=True
    #    sidelined -> is_active_employee=False, is_available=False
    ids = [t.id for t in maint]
    Technician.objects.filter(id__in=ids[:keep]).update(
        is_active_employee=True, is_available=True)
    Technician.objects.filter(id__in=ids[keep:]).update(
        is_active_employee=False, is_available=False)

    active = min(keep, len(ids))
    flag = "  <-- UNDER optimal" if len(ids) < keep else ""
    print(f"{gname}: {len(ids)} maintenance (+{converted} converted) "
          f"-> {active} active, {max(0, len(ids) - keep)} sidelined{flag}")

print("\nDone. Zones unchanged. Sidelined techs are now off the active roster "
      "(is_active_employee=False) so the live map shows the real active count.")
