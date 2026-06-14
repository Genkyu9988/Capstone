import pandas as pd

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from datetime import time
from api.models import (
    Technician,
    TechnicianRole,
    SpecialtyType,
    ExperienceLevel,
    SupervisorGroup,
    UserProfile,
    UserRole,
)


DEFAULT_PASSWORD = "Change123!"


def map_tech_role(value):
    """New model: technicians are EITHER Maintenance OR Callback. No 'both' role."""
    value = str(value).strip().lower()

    if "bakım" in value or "bakim" in value or "maintenance" in value:
        return TechnicianRole.MAINTENANCE

    # Arızacı / repair / breakdown / callback -> CALLBACK
    if ("arıza" in value or "ariza" in value or "repair" in value
            or "breakdown" in value or "callback" in value):
        return TechnicianRole.CALLBACK

    raise ValueError(f"Bilinmeyen Görev Türü: {value}")


def map_specialty(value):
    """Maintenance techs: Elevator / Escalator / Both. (Callback specialty is
    overridden to BOTH below, since callback covers both unit types.)"""
    value = str(value).strip().lower()

    if "+" in value or "her" in value or "both" in value or "ikisi" in value:
        return SpecialtyType.BOTH

    if "asansör" in value or "asansor" in value or "elevator" in value:
        return SpecialtyType.ELEVATOR

    if "yürüyen" in value or "yuruyen" in value or "merdiven" in value or "escalator" in value:
        return SpecialtyType.ESCALATOR

    raise ValueError(f"Bilinmeyen Uzmanlık: {value}")


def make_username(employee_code):
    return str(employee_code).strip().lower()


class Command(BaseCommand):
    help = "Import technicians from Excel file (Maintenance/Callback model)"

    def add_arguments(self, parser):
        parser.add_argument("excel_path", type=str)

    def handle(self, *args, **options):
        excel_path = options["excel_path"]

        df = pd.read_excel(excel_path)

        created_count = 0
        updated_count = 0

        for _, row in df.iterrows():
            employee_code = str(row["Technician ID"]).strip()
            first_name = str(row["Ad"]).strip()
            last_name = str(row["Soyad"]).strip()
            full_name = f"{first_name} {last_name}".strip()

            tech_role = map_tech_role(row["Görev Türü"])
            specialty = map_specialty(row["Uzmanlık"])

            # New rule: callback technicians always cover BOTH elevator & escalator.
            if tech_role == TechnicianRole.CALLBACK:
                specialty = SpecialtyType.BOTH

            competency_code = str(row["Yetkinlik Kodu"]).strip()
            spv_name = str(row["SPV"]).strip()

            supervisor_username = spv_name.lower().replace(" ", "_")

            supervisor_user, _ = User.objects.get_or_create(
                username=supervisor_username,
                defaults={
                    "first_name": spv_name.split()[0] if spv_name else "",
                    "last_name": " ".join(spv_name.split()[1:]) if len(spv_name.split()) > 1 else "",
                    "email": "",
                    "is_staff": False,
                }
            )

            UserProfile.objects.get_or_create(
                user=supervisor_user,
                defaults={
                    "role": UserRole.SUP,
                }
            )

            group, _ = SupervisorGroup.objects.get_or_create(
                name=f"{spv_name} Group",
                defaults={
                    "code": supervisor_username.upper(),
                    "supervisor": supervisor_user,
                    "region": "",
                    "is_active": True,
                }
            )

            username = make_username(employee_code)

            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": "",
                    "is_staff": False,
                }
            )

            if not user.has_usable_password():
                user.set_password(DEFAULT_PASSWORD)
                user.save()

            UserProfile.objects.update_or_create(
                user=user,
                defaults={
                    "role": UserRole.TECH,
                }
            )

            _, created = Technician.objects.update_or_create(
                employee_code=employee_code,
                defaults={
                    "user": user,
                    "full_name": full_name,
                    "group": group,
                    "tech_role": tech_role,
                    "specialty": specialty,
                    "competency_code": competency_code,
                    "experience_level": ExperienceLevel.MID,
                    "is_available": True,
                    "is_active_employee": True,
                    "daily_capacity_min": 480,
                    "max_overtime_min": 60,
                    "work_start": time(8, 0),
                    "work_end": time(17, 0),
                }
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Technician import tamamlandı. Yeni: {created_count}, Güncellenen: {updated_count}"
            )
        )
