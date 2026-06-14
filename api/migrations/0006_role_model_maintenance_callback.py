# Generated for the Maintenance/Callback role-model change.
# Converts existing Technician rows from the old MAINTENANCE/REPAIR/BOTH model
# to the new MAINTENANCE/CALLBACK model, BEFORE the new enum choices are enforced.
#
#   REPAIR -> CALLBACK
#   BOTH   -> CALLBACK         (per project decision; the source Excel has no
#                               "both" techs, so these are import artifacts that
#                               most closely map to the flexible callback role)
#   MAINTENANCE -> unchanged
#
# Also normalizes specialty: every CALLBACK technician covers BOTH elevator and
# escalator (new rule), so their specialty is forced to BOTH. Maintenance techs
# keep their specialty (ELEVATOR / ESCALATOR / BOTH).
#
# Place this file at:  api/migrations/0006_role_model_maintenance_callback.py
# Then run:            python manage.py migrate

import datetime
from django.db import migrations, models


def forwards(apps, schema_editor):
    Technician = apps.get_model("api", "Technician")
    Technician.objects.filter(tech_role="REPAIR").update(tech_role="CALLBACK")
    Technician.objects.filter(tech_role="BOTH").update(tech_role="CALLBACK")
    Technician.objects.filter(tech_role="CALLBACK").update(specialty="BOTH")


def backwards(apps, schema_editor):
    Technician = apps.get_model("api", "Technician")
    Technician.objects.filter(tech_role="CALLBACK").update(tech_role="REPAIR")


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0004_technician_competency_code_and_more"),
    ]

    operations = [
        # --- venue_type + work-hour changes (what 0005 would have done) ---
        migrations.AddField(
            model_name="unit",
            name="venue_type",
            field=models.CharField(
                blank=True, max_length=50, null=True, verbose_name="Konum Tipi"
            ),
        ),
        migrations.AlterField(
            model_name="technician",
            name="work_end",
            field=models.TimeField(default=datetime.time(17, 0)),
        ),
        migrations.AlterField(
            model_name="technician",
            name="work_start",
            field=models.TimeField(default=datetime.time(8, 0)),
        ),
        # --- role-model data conversion (REPAIR/BOTH -> CALLBACK) ---
        migrations.RunPython(forwards, backwards),
        # --- update tech_role choices to MAINTENANCE/CALLBACK ---
        migrations.AlterField(
            model_name="technician",
            name="tech_role",
            field=models.CharField(
                max_length=20,
                choices=[("MAINTENANCE", "Bakım Teknisyeni"),
                         ("CALLBACK", "Arıza (Callback) Teknisyeni")],
                verbose_name="Görev Tipi",
            ),
        ),
    ]
