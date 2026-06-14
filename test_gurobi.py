import os
import django
from datetime import timedelta
from django.utils import timezone

# 1. Start Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'capstone.settings')
django.setup()

from django.contrib.auth import get_user_model
from api.models import (
    SupervisorGroup, Technician, Unit, TaskType, Task, PlanningPeriod,
    UnitType, TechnicianRole, SpecialtyType, OperationType, OptimizationRun
)

# 2. Imports from your sub-directory structure
from api.services.optimization.input_builder import build_optimization_input
from api.services.optimization.solver import solve_with_gurobi
from api.services.optimization.result_writer import write_optimization_results

User = get_user_model()


def run_micro_city_test():
    print("🧹 Veritabanı temizleniyor...")
    # Clear existing data to ensure a clean test
    Task.objects.all().delete()
    Technician.objects.all().delete()
    Unit.objects.all().delete()
    TaskType.objects.all().delete()
    SupervisorGroup.objects.all().delete()
    OptimizationRun.objects.all().delete()

    # Setup test entities
    admin_user, _ = User.objects.get_or_create(username="admin_test")
    group, _ = SupervisorGroup.objects.get_or_create(name="Istanbul Region", code="IST-01", supervisor=admin_user)
    period, _ = PlanningPeriod.objects.get_or_create(
        name="Test Week",
        start_date=timezone.now().date(),
        end_date=timezone.now().date() + timedelta(days=7),
        created_by=admin_user
    )

    print("👷 Teknisyenler oluşturuluyor...")
    # Create Technicians
    tech_elev = Technician.objects.create(
        user=User.objects.get_or_create(username="tech_elev")[0],
        employee_code="TECH-ELEV-01", full_name="Ahmet (Asansör Bakım)",
        group=group, tech_role=TechnicianRole.MAINTENANCE, specialty=SpecialtyType.ELEVATOR,
        daily_capacity_min=480
    )
    tech_esc = Technician.objects.create(
        user=User.objects.get_or_create(username="tech_esc")[0],
        employee_code="TECH-ESC-01", full_name="Mehmet (Merdiven Bakım)",
        group=group, tech_role=TechnicianRole.MAINTENANCE, specialty=SpecialtyType.ESCALATOR,
        daily_capacity_min=480
    )
    # 3. Arızacı (Can) - Setup with Login Credentials and Depot
    user_can, _ = User.objects.get_or_create(username="can_ariza")
    user_can.set_password("can12345")  # THIS IS HIS FLUTTER LOGIN PASSWORD
    user_can.save()
    tech_fault = Technician.objects.create(
        user=user_can,
        employee_code="TECH-FLT-01",
        full_name="Can (Acil Arızacı)",
        group=group,
        tech_role=TechnicianRole.REPAIR,
        specialty=SpecialtyType.BOTH,
        daily_capacity_min=480,
        current_latitude=41.0500,  # CAN'S STARTING POINT (DEPOT)
        current_longitude=29.0000
    )

    print("🏢 Üniteler oluşturuluyor...")
    u1 = Unit.objects.create(unit_code="U-ELEV-1", unit_name="Plaza Asansör 1", unit_type=UnitType.ELEVATOR,
                             latitude=41.08, longitude=29.01)
    u2 = Unit.objects.create(unit_code="U-ESC-1", unit_name="AVM Merdiven 1", unit_type=UnitType.ESCALATOR,
                             latitude=40.99, longitude=29.12)
    u3 = Unit.objects.create(unit_code="U-ELEV-2", unit_name="Hastane Asansör (ARIZA)", unit_type=UnitType.ELEVATOR,
                             latitude=41.05, longitude=29.05)

    print("📋 Görev Tipleri ve Görevler oluşturuluyor...")
    tt_maint_elev = TaskType.objects.create(code="MAINT-ELEV", name="Asansör Bakım",
                                            operation_type=OperationType.MAINTENANCE,
                                            required_specialty=SpecialtyType.ELEVATOR,
                                            required_technician_role=TechnicianRole.MAINTENANCE, base_duration_min=120)
    tt_maint_esc = TaskType.objects.create(code="MAINT-ESC", name="Merdiven Bakım",
                                           operation_type=OperationType.MAINTENANCE,
                                           required_specialty=SpecialtyType.ESCALATOR,
                                           required_technician_role=TechnicianRole.MAINTENANCE, base_duration_min=120)
    tt_fault = TaskType.objects.create(code="FAULT-AA", name="AA Tipi Arıza", operation_type=OperationType.CALLBACK,
                                       required_specialty=SpecialtyType.BOTH,
                                       required_technician_role=TechnicianRole.REPAIR, base_duration_min=60)

    # Create Tasks
    Task.objects.create(task_no="TSK-001", unit=u1, task_type=tt_maint_elev, planning_period=period,
                        created_by=admin_user, estimated_duration_min=120)
    Task.objects.create(task_no="TSK-002", unit=u2, task_type=tt_maint_esc, planning_period=period,
                        created_by=admin_user, estimated_duration_min=120)
    Task.objects.create(task_no="TSK-003", unit=u3, task_type=tt_fault, planning_period=period, created_by=admin_user,
                        estimated_duration_min=60, priority="AA")

    print("\n🚀 Gurobi Optimizasyonu Başlatılıyor...")
    # 1. Build input for Gurobi
    input_data = build_optimization_input(period)

    # 2. Run solver
    results = solve_with_gurobi(input_data)

    # 3. Save results to Database
    print("\n💾 Sonuçlar veritabanına kaydediliyor...")
    run_record = OptimizationRun.objects.create(
        planning_period=period,
        triggered_by=admin_user,
        status="FEASIBLE"
    )
    write_optimization_results(run_record, results)
    print("✅ Bütün atamalar Schedule tablosuna başarıyla kaydedildi!")

    print("\n" + "=" * 50)
    print("🏆 GUROBI ATAMA SONUÇLARI")
    print("=" * 50)
    for res in results:
        task_name = res['task'].task_no
        tech_name = res['technician'].full_name if res['technician'] else "ATANAMADI"
        reason = res.get('unassigned_reason', 'Başarılı')
        print(f"Görev: {task_name} ({res['task'].task_type.name}) ---> Teknisyen: {tech_name} | Durum: {reason}")
    print("=" * 50)


if __name__ == "__main__":
    run_micro_city_test()