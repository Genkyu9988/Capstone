"""
restore_tech_coords.py
=============================================================================
Copies ONLY technician current_latitude / current_longitude from a backup
database into the live db.sqlite3, matching by technician id. Nothing else is
touched -- your month schedule and all other data stay exactly as they are.

Run from C:\\capstone-main (where the .sqlite3 files live), with the Django
server NOT running (so the DB file isn't locked):

    python restore_tech_coords.py

Safety net: you already have db_backup_before_4month.sqlite3 (a copy of the
current state). If anything looks wrong afterward, copy that back over
db.sqlite3 to undo.
=============================================================================
"""
import sqlite3

SOURCE = "db_backup_before_month.sqlite3"   # backup that still has coordinates
LIVE = "db.sqlite3"                         # your working database

# Rough Istanbul bounding box, used only to warn about stray (e.g. California) coords.
IST_LAT = (40.5, 41.5)
IST_LNG = (28.0, 29.8)


def main():
    src = sqlite3.connect(SOURCE)
    rows = src.execute(
        "SELECT id, current_latitude, current_longitude FROM api_technician "
        "WHERE current_latitude IS NOT NULL AND current_longitude IS NOT NULL"
    ).fetchall()
    src.close()
    print(f"Read {len(rows)} technician coordinates from {SOURCE}.")

    # sanity check: anything outside Istanbul is suspicious
    outliers = [
        (tid, lat, lng) for tid, lat, lng in rows
        if not (IST_LAT[0] <= lat <= IST_LAT[1] and IST_LNG[0] <= lng <= IST_LNG[1])
    ]
    if outliers:
        print(f"WARNING: {len(outliers)} coordinate(s) look outside Istanbul "
              f"(possible leftover bad GPS). First few:")
        for tid, lat, lng in outliers[:5]:
            print(f"   tech id {tid}: ({lat}, {lng})")
        print("   (They will still be copied. Inspect if the count is unexpected.)")

    dst = sqlite3.connect(LIVE)
    updated = 0
    for tid, lat, lng in rows:
        cur = dst.execute(
            "UPDATE api_technician SET current_latitude=?, current_longitude=? WHERE id=?",
            (lat, lng, tid),
        )
        updated += cur.rowcount
    dst.commit()

    have = dst.execute(
        "SELECT COUNT(*) FROM api_technician WHERE current_latitude IS NOT NULL"
    ).fetchone()[0]
    total = dst.execute("SELECT COUNT(*) FROM api_technician").fetchone()[0]
    dst.close()

    print(f"Updated {updated} technician rows in {LIVE}.")
    print(f"{LIVE} now has {have} of {total} technicians with coordinates.")
    if have == 0:
        print("Nothing matched -- the technician ids in the backup may differ from the "
              "live DB. Tell me and we'll match on another key.")
    else:
        print("Done. You can now run solve_month.")


if __name__ == "__main__":
    main()
