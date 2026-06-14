# api/migrations/0007_unitmaintenancestate.py
# Adds the UnitMaintenanceState table (A/B/C maintenance cycle tracking).
# Purely additive: creates one new table, touches nothing existing.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0006_role_model_maintenance_callback"),
    ]

    operations = [
        migrations.CreateModel(
            name="UnitMaintenanceState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("last_a_date", models.DateField(blank=True, null=True,
                                                 verbose_name="Son A Bakımı")),
                ("last_b_date", models.DateField(blank=True, null=True,
                                                 verbose_name="Son B Bakımı")),
                ("last_c_date", models.DateField(blank=True, null=True,
                                                 verbose_name="Son C Bakımı")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("unit", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="maintenance_state",
                    to="api.unit",
                    verbose_name="Ünite")),
            ],
            options={
                "verbose_name": "Unit Maintenance State",
                "verbose_name_plural": "Unit Maintenance States",
            },
        ),
    ]
