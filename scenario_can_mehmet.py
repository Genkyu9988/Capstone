"""
scenario_can_mehmet.py
=============================================================================
İki teknisyenli demo senaryosu:

  - Mehmet (tech_esc)  -> MAINTENANCE / ESCALATOR  -> 3 yürüyen merdiven bakımı
  - Can    (can_ariza) -> REPAIR / BOTH            -> 3 asansör arıza (callback)

Gurobi atama optimizasyonunu çalıştırır, sonucu Schedule tablosuna yazar ve
her iki teknisyenin /api/my-route/ üzerinden göreceği rotayı ekrana basar.

Çalıştırma (test_gurobi.py ile aynı ortamda):

    python scenario_can_mehmet.py

LOGIN BİLGİLERİ:
    Mehmet -> kullanıcı: tech_esc   şifre: mehmet123
    Can    -> kullanıcı: can_ariza  şifre: can12345
=============================================================================
"""

import os
import django
from datetime import timedelta
from django.utils import timezone

# 1) Django ortamını başlat
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "capstone.settings")
django.setup()

from django.contrib.auth import get_user_model
from api.models import (
    SupervisorGroup,
    Technician,
    Unit,
    TaskType,
    Task,
    PlanningPeriod,
    Schedule,
    OptimizationRun,
    UnitType,
    TechnicianRole,
    SpecialtyType,
    OperationType,
)
from api.services.optimization.input_builder import build_optimization_input
from api.services.optimization.solver import solve_with_gurobi
from api.services.optimization.result_writer import write_optimization_results

User = get_user_model()


def reset_planning_data():
    """Eski rota/görev/koşu verilerini temizle (teknisyen ve üniteleri korur)."""
    print("🧹 Eski Schedule / Task / OptimizationRun kayıtları siliniyor...")
    Schedule.objects.all().delete()
    Task.objects.all().delete()
    OptimizationRun.objects.all().delete()


def get_base_entities():
    """Admin kullanıcı, supervisor grubu ve planlama dönemini hazırla."""
    admin_user, _ = User.objects.get_or_create(username="admin_test")

    group, _ = SupervisorGroup.objects.get_or_create(
        code="IST-01",
        defaults={"name": "Istanbul Region", "supervisor": admin_user},
    )

    today = timezone.now().date()
    period, _ = PlanningPeriod.objects.get_or_create(
        start_date=today,
        end_date=today + timedelta(days=7),
        defaults={
            "name": "Demo Haftası (Can & Mehmet)",
            "created_by": admin_user,
        },
    )
    return admin_user, group, period


def setup_technicians(group):
    """Can ve Mehmet'i şifre + depo konumu ile hazırla."""
    print("👷 Teknisyenler hazırlanıyor (şifre + depo konumu)...")

    # --- Mehmet: yürüyen merdiven bakımcı (Avrupa yakası deposu) ---
    mehmet_user, _ = User.objects.get_or_create(username="tech_esc")
    mehmet_user.first_name = "Mehmet"
    mehmet_user.set_password("mehmet123")  # Flutter login şifresi
    mehmet_user.save()

    mehmet, _ = Technician.objects.get_or_create(
        user=mehmet_user,
        defaults={
            "employee_code": "TECH-ESC-01",
            "full_name": "Mehmet (Merdiven Bakım)",
            "group": group,
        },
    )
    mehmet.full_name = "Mehmet (Merdiven Bakım)"
    mehmet.group = group
    mehmet.tech_role = TechnicianRole.MAINTENANCE
    mehmet.specialty = SpecialtyType.ESCALATOR
    mehmet.is_available = True
    mehmet.is_active_employee = True
    mehmet.daily_capacity_min = 480
    mehmet.current_latitude = 41.0410   # Mehmet'in güne başlangıç noktası
    mehmet.current_longitude = 28.9870
    mehmet.save()

    # --- Can: acil arızacı (Anadolu yakası deposu) ---
    can_user, _ = User.objects.get_or_create(username="can_ariza")
    can_user.first_name = "Can"
    can_user.set_password("can12345")  # Flutter login şifresi
    can_user.save()

    can, _ = Technician.objects.get_or_create(
        user=can_user,
        defaults={
            "employee_code": "TECH-FLT-01",
            "full_name": "Can (Acil Arızacı)",
            "group": group,
        },
    )
    can.full_name = "Can (Acil Arızacı)"
    can.group = group
    can.tech_role = TechnicianRole.REPAIR
    can.specialty = SpecialtyType.BOTH
    can.is_available = True
    can.is_active_employee = True
    can.daily_capacity_min = 480
    can.current_latitude = 41.0500    # Can'ın güne başlangıç noktası
    can.current_longitude = 29.0000
    can.save()

    return can, mehmet


def setup_task_types():
    esc_maint, _ = TaskType.objects.get_or_create(
        code="ESC-MAINT",
        defaults={
            "name": "Yürüyen Merdiven Bakımı",
            "operation_type": OperationType.MAINTENANCE,
            "required_specialty": SpecialtyType.ESCALATOR,
            "required_technician_role": TechnicianRole.MAINTENANCE,
            "base_duration_min": 120,
        },
    )

    elev_callback, _ = TaskType.objects.get_or_create(
        code="ELEV-CALL",
        defaults={
            "name": "Asansör Arıza (Callback)",
            "operation_type": OperationType.CALLBACK,
            "required_specialty": SpecialtyType.ELEVATOR,
            "required_technician_role": TechnicianRole.REPAIR,
            "base_duration_min": 60,
        },
    )
    return esc_maint, elev_callback


def setup_units():
    """Demo üniteleri (Mehmet için yürüyen merdiven, Can için asansör)."""
    print("🏢 Üniteler oluşturuluyor...")

    # Mehmet'in yürüyen merdivenleri (AVM / istasyon)
    esc_units_data = [
        ("ESC-U1", "Kanyon AVM Yürüyen Merdiven", 41.0784, 29.0106),
        ("ESC-U2", "Cevahir AVM Yürüyen Merdiven", 41.0625, 28.9933),
        ("ESC-U3", "Marmara Forum Yürüyen Merdiven", 40.9889, 28.8731),
    ]

    # Can'ın asansör arıza noktaları
    elev_units_data = [
        ("CALL-U1", "Acıbadem Hastanesi Asansör", 40.9905, 29.0297),
        ("CALL-U2", "Ataşehir Rezidans Asansör", 40.9923, 29.1244),
        ("CALL-U3", "Maslak Plaza Asansör", 41.1106, 29.0203),
    ]

    def make_units(data, unit_type):
        units = []
        for code, name, lat, lon in data:
            u, _ = Unit.objects.get_or_create(
                unit_code=code,
                defaults={
                    "unit_name": name,
                    "unit_type": unit_type,
                    "address": name,
                    "latitude": lat,
                    "longitude": lon,
                },
            )
            units.append(u)
        return units

    esc_units = make_units(esc_units_data, UnitType.ESCALATOR)
    elev_units = make_units(elev_units_data, UnitType.ELEVATOR)
    return esc_units, elev_units


def create_tasks(period, admin_user, esc_type, call_type, esc_units, elev_units):
    print("📋 Görevler oluşturuluyor (3 + 3)...")

    # Mehmet'in 3 yürüyen merdiven bakımı (maintenance -> priority YOK)
    for i, unit in enumerate(esc_units, start=1):
        Task.objects.create(
            task_no=f"MEH-{i:03d}",
            unit=unit,
            task_type=esc_type,
            planning_period=period,
            created_by=admin_user,
            estimated_duration_min=120,
        )

    # Can'ın 3 asansör arızası (callback -> priority ZORUNLU)
    callback_priorities = ["AA", "A", "B"]
    for i, (unit, prio) in enumerate(zip(elev_units, callback_priorities), start=1):
        Task.objects.create(
            task_no=f"CAN-{i:03d}",
            unit=unit,
            task_type=call_type,
            planning_period=period,
            created_by=admin_user,
            estimated_duration_min=60 if prio == "AA" else 90,
            priority=prio,
        )


def print_route_for(technician):
    """MyOptimizedRouteView'in döndüreceği rotayı birebir taklit eder."""
    start_lat = technician.current_latitude or 41.0082
    start_lon = technician.current_longitude or 28.9784

    schedules = (
        Schedule.objects.filter(technician=technician)
        .select_related("task", "task__unit", "task__task_type")
        .order_by("sequence_order")
    )

    print("\n" + "=" * 60)
    print(f"🗺️  {technician.full_name} ROTASI ({schedules.count()} durak + depo)")
    print("=" * 60)
    print(f"  0. DEPO  -> ({start_lat}, {start_lon})")
    for s in schedules:
        print(
            f"  {s.sequence_order}. {s.task.task_no} | {s.task.task_type.name} "
            f"| {s.task.unit.unit_name} -> ({s.task.unit.latitude}, {s.task.unit.longitude})"
        )
    print("=" * 60)


def run_scenario():
    reset_planning_data()
    admin_user, group, period = get_base_entities()
    can, mehmet = setup_technicians(group)
    esc_type, call_type = setup_task_types()
    esc_units, elev_units = setup_units()
    create_tasks(period, admin_user, esc_type, call_type, esc_units, elev_units)

    print("\n🚀 Gurobi optimizasyonu başlatılıyor...")
    input_data = build_optimization_input(period)
    results = solve_with_gurobi(input_data)

    print("\n💾 Sonuçlar veritabanına yazılıyor...")
    run_record = OptimizationRun.objects.create(
        planning_period=period,
        triggered_by=admin_user,
        status="FEASIBLE",
    )
    write_optimization_results(run_record, results)

    print("\n" + "=" * 60)
    print("🏆 GUROBI ATAMA SONUÇLARI")
    print("=" * 60)
    for res in results:
        task_name = res["task"].task_no
        tech_name = res["technician"].full_name if res["technician"] else "ATANAMADI"
        print(f"  {task_name:10s} -> {tech_name}")
    print("=" * 60)

    # Her iki teknisyenin rotasını yazdır
    print_route_for(mehmet)
    print_route_for(can)

    print("\n✅ Hazır! Flutter'dan giriş yapabilirsiniz:")
    print("   Mehmet -> kullanıcı: tech_esc   şifre: mehmet123")
    print("   Can    -> kullanıcı: can_ariza  şifre: can12345")


if __name__ == "__main__":
    run_scenario()