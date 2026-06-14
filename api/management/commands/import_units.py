import pandas as pd

from django.core.management.base import BaseCommand
from api.models import Unit, UnitType


def map_unit_type(value):
    value = str(value).strip().lower()

    if value in ["elevator", "asansör", "asansor"]:
        return UnitType.ELEVATOR

    if value in ["escalator", "yürüyen merdiven", "yuruyen merdiven"]:
        return UnitType.ESCALATOR

    raise ValueError(f"Bilinmeyen Unit Type: {value}")


class Command(BaseCommand):
    help = "Import units from the real portfolio Excel file"

    def add_arguments(self, parser):
        parser.add_argument("excel_path", type=str)

    def handle(self, *args, **options):
        excel_path = options["excel_path"]

        df = pd.read_excel(excel_path)

        # Real file columns:
        #   Portfolio Building | Unit Type | Unit Number | Location |
        #   Unit Type.1 | Brand | Latitude | Longitude | Region
        # NOTE:
        #   - "Unit Type.1" holds the REAL unit type (Elevator / Escalator)
        #   - "Unit Type"   holds the VENUE type (Konut, AVM, ...) -> venue_type
        df = df.rename(columns={"Unit Type.1": "real_unit_type"})

        created_count = 0
        updated_count = 0
        skipped = 0

        for _, row in df.iterrows():
            try:
                unit_name = str(row["Portfolio Building"]).strip()
                unit_code = str(row["Unit Number"]).strip()
                location = str(row["Location"]).strip() if "Location" in df.columns else ""
                unit_type = map_unit_type(row["real_unit_type"])
                brand = str(row["Brand"]).strip() if "Brand" in df.columns else ""

                # venue type comes from the (mis-labeled) "Unit Type" column
                venue_type = str(row["Unit Type"]).strip() if "Unit Type" in df.columns else ""
                if venue_type.lower() in ("nan", "none", ""):
                    venue_type = ""

                region = str(row["Region"]).strip() if "Region" in df.columns else ""
                if region.lower() in ("nan", "none"):
                    region = ""

                latitude = float(str(row["Latitude"]).replace(",", "."))
                longitude = float(str(row["Longitude"]).replace(",", "."))
            except Exception as e:
                skipped += 1
                continue

            _, created = Unit.objects.update_or_create(
                unit_code=unit_code,
                defaults={
                    "unit_name": unit_name,
                    "unit_type": unit_type,
                    "brand": brand,
                    "address": location,
                    "city": "Istanbul",
                    "district": region,
                    "venue_type": venue_type,
                    "latitude": latitude,
                    "longitude": longitude,
                    "is_active": True,
                }
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Import tamamlandı. Yeni: {created_count}, "
                f"Güncellenen: {updated_count}, Atlanan: {skipped}"
            )
        )
