import os
import django
import random
# Django ayarlarını sisteme tanıtıyoruz
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'capstone.settings')
django.setup()

from api.models import Unit, Technician, Task, SupervisorGroup
def run_seed():
    print("Veriler ekleniyor, lütfen bekleyin...")

    # 1. Örnek Üniteler (Asansörler) ekleyelim
    # Added "code" to each dictionary
    units_data = [
        {"code": "UNIT-001", "name": "Sapphire Tower A", "addr": "Levent, Istanbul", "lat": 41.08, "lon": 29.01},
        {"code": "UNIT-002", "name": "Metropol Istanbul", "addr": "Atasehir, Istanbul", "lat": 40.99, "lon": 29.12},
        {"code": "UNIT-003", "name": "Spine Tower", "addr": "Maslak, Istanbul", "lat": 41.11, "lon": 29.02},
        {"code": "UNIT-004", "name": "Ege Plaza", "addr": "Cankaya, Ankara", "lat": 39.91, "lon": 32.81},
    ]

    units = []
    for data in units_data:
        u, created = Unit.objects.get_or_create(
            unit_code=data["code"],  # <-- TELL DJANGO TO SAVE THE CODE
            unit_name=data["name"],
            address=data["addr"],
            latitude=data["lat"],
            longitude=data["lon"]
        )
        units.append(u)

        from django.contrib.auth import get_user_model  # Safest way to get the User model
        User = get_user_model()

        # 2. Örnek Teknisyenler ekleyelim

        # A) First, create a dummy User to act as the supervisor
        sup_user, _ = User.objects.get_or_create(
            username="admin_supervisor",
            defaults={"first_name": "Admin", "last_name": "Supervisor"}
        )

        # B) Now create the group, and assign our new supervisor to it!
        tech_group, _ = SupervisorGroup.objects.get_or_create(
            name="Saha Teknisyenleri",
            defaults={"supervisor": sup_user}  # <--- THE FIX: No longer NULL!
        )

        # C) Create the technicians and assign them to the group AND a user account
        techs_data = [
            {"code": "TECH-001", "name": "Ahmet Yılmaz", "type": "M", "phone": "5551112233"},
            {"code": "TECH-002", "name": "Mehmet Demir", "type": "C", "phone": "5554445566"},
            {"code": "TECH-003", "name": "Ayşe Kaya", "type": "M", "phone": "5557778899"},
        ]

        techs = []
        for data in techs_data:
            # 1. Create a User account for the technician (we will use their code as their username)
            tech_user, _ = User.objects.get_or_create(
                username=data["code"],
                defaults={"first_name": data["name"]}
            )

            # 2. Create the Technician profile and link the User account
            t, created = Technician.objects.get_or_create(
                employee_code=data["code"],
                full_name=data["name"],
                tech_role=data["type"],
                phone=data["phone"],
                group=tech_group,
                user=tech_user  # <--- THE FIX: Assign the required user_id!
            )
            techs.append(t)

    import datetime
    from django.utils import timezone
    from api.models import PlanningPeriod, TaskType
    from django.contrib.auth import get_user_model
    User = get_user_model()

    # 3. Rastgele Görev (Task) oluşturalım

    # A) Get the supervisor we created in Section 2 to be the "creator" of the tasks
    sup_user = User.objects.get(username="admin_supervisor")

    # B) Create a Planning Period (Tasks require this)
    today = timezone.now().date()
    period, _ = PlanningPeriod.objects.get_or_create(
        name="Mayıs 2026 Planlaması",
        start_date=today,
        end_date=today + datetime.timedelta(days=7),
        created_by=sup_user
    )

    # C) Create Task Types (Tasks require this instead of a raw "error_code")
    tt_maint, _ = TaskType.objects.get_or_create(
        code="TT-MAINT",
        defaults={"name": "Periyodik Bakım", "operation_type": "MAINTENANCE", "base_duration_min": 60}
    )
    tt_call, _ = TaskType.objects.get_or_create(
        code="TT-CALL",
        defaults={"name": "Acil Arıza", "operation_type": "CALLBACK", "base_duration_min": 90}
    )
    task_types = [tt_maint, tt_call]

    # D) Generate the Tasks!
    descriptions = ["Motor aşırı ısınma", "Kapı sensör arızası", "Periyodik yağlama", "Kat ayarı bozuk",
                    "Acil fren testi"]

    for i in range(10):
        # Pick a random task type
        t_type = random.choice(task_types)

        # Your model requires a priority ONLY if it is a CALLBACK. Maintenance must be None.
        priority = random.choice(["A", "B", "C"]) if t_type.operation_type == "CALLBACK" else None

        Task.objects.get_or_create(
            task_no=f"TSK-2026-{i:03d}",  # Creates TSK-2026-000, TSK-2026-001, etc.
            defaults={
                "unit": random.choice(units),
                "planning_period": period,
                "task_type": t_type,
                "created_by": sup_user,
                "description": random.choice(descriptions),
                "status": "PENDING",
                "priority": priority,
                "estimated_duration_min": t_type.base_duration_min
            }
        )

    print("İşlem tamam! 4 Ünite, 3 Teknisyen ve 10 Görev başarıyla eklendi.")

if __name__ == '__main__':
    run_seed()