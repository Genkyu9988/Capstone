"""
api/management/commands/seed_deployment.py
=============================================================================
DATA-DRIVEN, ZONE-BASED DEPLOYMENT (does NOT modify roles/groups/specialties).

  * Classifies each existing group by composition (read-only):
        only callback -> CALLBACK HQ | only maintenance -> MAINTENANCE HQ |
        both -> MIXED HQ
  * Places the maintenance-capable HQs at K-MEANS centers of the unit cloud
    (balanced zones), split by region proportional to unit share.
  * Places the 2 CALLBACK HQs at the densest spot on each side.
  * ZONE OWNERSHIP: every maintenance unit belongs to its NEAREST maintenance HQ.
  * MONTHLY C-CYCLE: each unit gets a due-day across CYCLE_DAYS working days;
    today's tasks = the slice due now (~zone/CYCLE_DAYS).
  * Writes ONLY technician current_latitude/longitude. Nothing else changes.

Requires: pip install scikit-learn

Run:
  python manage.py seed_deployment "C:/capstone-main/data/portfolio_realistic_20000_v2.xlsx"
Then:
  python manage.py solve_group "<Maintenance Group Name>"
=============================================================================
"""
import math
from datetime import date

import numpy as np
import pandas as pd
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api.models import (
    SupervisorGroup, Technician, Unit, UnitType, PlanningPeriod,
    TaskType, Task, OperationType, MaintenanceType, SpecialtyType,
    TechnicianRole, TaskStatus,
)

CYCLE_DAYS = 20
C_DURATION_MIN = 45
BOSPHORUS_LNG = 29.02


def _km(a, b, c, d):
    return math.sqrt(((a - c) * 111) ** 2 + ((b - d) * 85) ** 2)


class Command(BaseCommand):
    help = "Zone-based deployment: k-means HQs, zone ownership, C-cycle daily tasks."

    def add_arguments(self, parser):
        parser.add_argument("units_excel", type=str)
        parser.add_argument("--cycle-day", type=int, default=0)

    def handle(self, *args, **opts):
        try:
            from sklearn.cluster import KMeans
        except ImportError:
            raise CommandError("scikit-learn required: pip install scikit-learn")

        df = pd.read_excel(opts["units_excel"]).rename(columns={"Unit Type.1": "utype"})
        df["lat"] = pd.to_numeric(df["Latitude"], errors="coerce")
        df["lng"] = pd.to_numeric(df["Longitude"], errors="coerce")
        df = df.dropna(subset=["lat", "lng"]).reset_index(drop=True)

        eu = df[df.lng < BOSPHORUS_LNG]
        asia = df[df.lng >= BOSPHORUS_LNG]

        groups = []
        for g in SupervisorGroup.objects.all():
            qs = Technician.objects.filter(group=g)
            m = qs.filter(tech_role=TechnicianRole.MAINTENANCE).count()
            c = qs.filter(tech_role=TechnicianRole.CALLBACK).count()
            if m and c:
                typ = "MIXED"
            elif c:
                typ = "CALLBACK"
            elif m:
                typ = "MAINTENANCE"
            else:
                continue
            groups.append({"group": g, "type": typ, "m": m, "c": c})

        callbacks = [x for x in groups if x["type"] == "CALLBACK"]
        maint_capable = [x for x in groups if x["type"] in ("MAINTENANCE", "MIXED")]
        n_maint = len(maint_capable)
        if n_maint == 0:
            raise CommandError("No maintenance-capable groups found.")

        n_eu = round(n_maint * len(eu) / len(df))
        n_as = n_maint - n_eu

        def kmeans_centers(side_df, k):
            if k <= 0:
                return []
            X = side_df[["lat", "lng"]].values
            model = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)
            return [tuple(c) for c in model.cluster_centers_]

        eu_centers = kmeans_centers(eu, n_eu)
        as_centers = kmeans_centers(asia, n_as)
        maint_hqs = [("Europe", c) for c in eu_centers] + [("Asia", c) for c in as_centers]

        maint_plan = []
        for entry, (side, center) in zip(maint_capable, maint_hqs):
            maint_plan.append({"group": entry["group"], "type": entry["type"],
                               "side": side, "hq": center})

        def densest(side_df):
            s = side_df.copy()
            s["glat"] = (s.lat * 50).round() / 50
            s["glng"] = (s.lng * 50).round() / 50
            d = s.groupby(["glat", "glng"]).size().reset_index(name="n").sort_values("n", ascending=False)
            r = d.iloc[0]
            return (float(r.glat), float(r.glng))

        callback_plan = []
        sides = ["Europe", "Asia"]
        for i, entry in enumerate(callbacks):
            side = sides[i % 2]
            hq = densest(eu if side == "Europe" else asia)
            callback_plan.append({"group": entry["group"], "type": "CALLBACK",
                                  "side": side, "hq": hq})

        for p in maint_plan + callback_plan:
            Technician.objects.filter(group=p["group"]).update(
                current_latitude=p["hq"][0], current_longitude=p["hq"][1])

        centers_arr = np.array([p["hq"] for p in maint_plan])
        coords = df[["lat", "lng"]].values
        w = np.array([111.0, 85.0])
        dists = np.sqrt((((coords[:, None, :] - centers_arr[None, :, :]) * w) ** 2).sum(axis=2))
        df["zone"] = dists.argmin(axis=1)
        df["due_day"] = df.index % CYCLE_DAYS
        today_due = opts["cycle_day"] % CYCLE_DAYS

        tt_elev, _ = TaskType.objects.update_or_create(
            code="MNT-C-ELEV",
            defaults={"name": "C Bakimi (Asansor)", "operation_type": OperationType.MAINTENANCE,
                      "maintenance_type": MaintenanceType.C, "required_specialty": SpecialtyType.ELEVATOR,
                      "required_technician_role": TechnicianRole.MAINTENANCE,
                      "base_duration_min": C_DURATION_MIN, "is_active": True})
        tt_esc, _ = TaskType.objects.update_or_create(
            code="MNT-C-ESC",
            defaults={"name": "C Bakimi (Yuruyen Merdiven)", "operation_type": OperationType.MAINTENANCE,
                      "maintenance_type": MaintenanceType.C, "required_specialty": SpecialtyType.ESCALATOR,
                      "required_technician_role": TechnicianRole.MAINTENANCE,
                      "base_duration_min": C_DURATION_MIN, "is_active": True})

        today = date.today()
        self.stdout.write(self.style.SUCCESS("=== ZONE-BASED DEPLOYMENT ==="))

        # ONE shared planning period for the whole day (the model enforces
        # unique start_date+end_date, so all groups share it).
        creator = User.objects.filter(is_superuser=True).first()
        if creator is None:
            creator = User.objects.first()
        period = PlanningPeriod.objects.filter(start_date=today, end_date=today).first()
        if period is None:
            period = PlanningPeriod.objects.create(
                name=f"Deployment Day {today.isoformat()}",
                start_date=today, end_date=today, is_active=True,
                created_by=creator,
            )

        for zi, p in enumerate(maint_plan):
            g = p["group"]
            zone_today = df[(df["zone"] == zi) & (df["due_day"] == today_due)]
            zone_total = int((df["zone"] == zi).sum())
            self.stdout.write(
                f"{g.name:24s} {p['type']:11s} {p['side']:6s} "
                f"HQ=({p['hq'][0]:.3f},{p['hq'][1]:.3f}) "
                f"zone={zone_total} units, today={len(zone_today)} tasks")

            for _, row in zone_today.iterrows():
                code = str(row["Unit Number"]).strip()
                unit = Unit.objects.filter(unit_code=code).first()
                if unit is None:
                    continue
                tt = tt_esc if unit.unit_type == UnitType.ESCALATOR else tt_elev
                Task.objects.update_or_create(
                    task_no=f"MNT-{g.code}-{code}",
                    defaults={"unit": unit, "planning_period": period, "task_type": tt,
                              "created_by": creator, "assigned_group": g,
                              "description": f"C maintenance for {unit.unit_name}",
                              "status": TaskStatus.PENDING, "priority": None,
                              "estimated_duration_min": tt.base_duration_min,
                              "release_time": timezone.now(), "is_active": True})

        for p in callback_plan:
            self.stdout.write(
                f"{p['group'].name:24s} CALLBACK    {p['side']:6s} "
                f"HQ=({p['hq'][0]:.3f},{p['hq'][1]:.3f}) (callbacks only)")

        self.stdout.write(self.style.SUCCESS(
            "\nDeployment done. Next: python manage.py solve_group \"<Maintenance Group Name>\""))
