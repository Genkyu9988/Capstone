
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import serializers

from .models import (
    UserProfile,
    SupervisorGroup,
    PlanningPeriod,
    Unit,
    Technician,
    TaskType,
    Task,
    OptimizationRun,
    Schedule,
    AvailabilityRequest,
    DistanceMatrixCache,
    AuditLog,
    UserRole,
    RequestStatus,
    TaskStatus,
    RunStatus,
)


class UserBasicSerializer(serializers.ModelSerializer):
    role = serializers.CharField(source="profile.role", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email", "role"]


class UserProfileSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)

    class Meta:
        model = UserProfile
        fields = ["id", "user", "role", "phone_number", "department", "created_at"]


class SupervisorGroupSerializer(serializers.ModelSerializer):
    supervisor = UserBasicSerializer(read_only=True)
    technician_count = serializers.IntegerField(source="technicians.count", read_only=True)

    class Meta:
        model = SupervisorGroup
        fields = [
            "id",
            "name",
            "code",
            "description",
            "supervisor",
            "region",
            "is_active",
            "technician_count",
            "created_at",
        ]


class PlanningPeriodSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = PlanningPeriod
        fields = [
            "id",
            "name",
            "start_date",
            "end_date",
            "is_locked",
            "is_active",
            "created_by",
            "created_at",
        ]


class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = [
            "id",
            "unit_name",
            "unit_code",
            "unit_type",
            "brand",
            "model_name",
            "address",
            "city",
            "district",
            "latitude",
            "longitude",
            "operating_hours_start",
            "operating_hours_end",
            "is_active",
            "notes",
            "created_at",
        ]


class TechnicianSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)
    group = SupervisorGroupSerializer(read_only=True)
    group_id = serializers.PrimaryKeyRelatedField(
        source="group",
        queryset=SupervisorGroup.objects.all(),
        write_only=True
    )

    class Meta:
        model = Technician
        fields = [
            "id",
            "user",
            "employee_code",
            "full_name",
            "phone",
            "group",
            "group_id",
            "tech_role",
            "specialty",
            "is_available",
            "is_active_employee",
            "current_latitude",
            "current_longitude",
            "work_start",
            "work_end",
            "daily_capacity_min",
            "max_overtime_min",
            "created_at",
        ]


class TaskTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskType
        fields = [
            "id",
            "code",
            "name",
            "operation_type",
            "maintenance_type",
            "required_specialty",
            "required_technician_role",
            "base_duration_min",
            "sla_target_min",
            "is_active",
        ]


class TaskSerializer(serializers.ModelSerializer):
    unit = UnitSerializer(read_only=True)
    unit_id = serializers.PrimaryKeyRelatedField(
        source="unit",
        queryset=Unit.objects.all(),
        write_only=True
    )

    planning_period = PlanningPeriodSerializer(read_only=True)
    planning_period_id = serializers.PrimaryKeyRelatedField(
        source="planning_period",
        queryset=PlanningPeriod.objects.all(),
        write_only=True
    )

    task_type = TaskTypeSerializer(read_only=True)
    task_type_id = serializers.PrimaryKeyRelatedField(
        source="task_type",
        queryset=TaskType.objects.all(),
        write_only=True
    )

    created_by = UserBasicSerializer(read_only=True)

    assigned_group = SupervisorGroupSerializer(read_only=True)
    assigned_group_id = serializers.PrimaryKeyRelatedField(
        source="assigned_group",
        queryset=SupervisorGroup.objects.all(),
        write_only=True,
        required=False,
        allow_null=True
    )

    parent_task_id = serializers.PrimaryKeyRelatedField(
        source="parent_task",
        queryset=Task.objects.all(),
        write_only=True,
        required=False,
        allow_null=True
    )

    parent_task = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id",
            "task_no",
            "unit",
            "unit_id",
            "planning_period",
            "planning_period_id",
            "task_type",
            "task_type_id",
            "created_by",
            "assigned_group",
            "assigned_group_id",
            "description",
            "status",
            "priority",
            "is_follow_up",
            "parent_task",
            "parent_task_id",
            "estimated_duration_min",
            "earliest_start",
            "latest_finish",
            "release_time",
            "is_unassigned",
            "unassigned_reason",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "is_unassigned", "unassigned_reason", "created_at", "updated_at"]

    def get_parent_task(self, obj):
        if not obj.parent_task:
            return None
        return {
            "id": obj.parent_task.id,
            "task_no": obj.parent_task.task_no,
        }

    def create(self, validated_data):
        request = self.context["request"]
        validated_data["created_by"] = request.user

        # Supervisor callback açıyorsa default kendi grubuna düşsün
        if not validated_data.get("assigned_group"):
            if hasattr(request.user, "profile") and request.user.profile.role == UserRole.SUP:
                if hasattr(request.user, "supervised_group"):
                    validated_data["assigned_group"] = request.user.supervised_group

        return super().create(validated_data)


class OptimizationRunSerializer(serializers.ModelSerializer):
    planning_period = PlanningPeriodSerializer(read_only=True)
    planning_period_id = serializers.PrimaryKeyRelatedField(
        source="planning_period",
        queryset=PlanningPeriod.objects.all(),
        write_only=True
    )
    triggered_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = OptimizationRun
        fields = [
            "id",
            "planning_period",
            "planning_period_id",
            "triggered_by",
            "status",
            "started_at",
            "finished_at",
            "solver_name",
            "solver_time_limit_sec",
            "objective_value",
            "mip_gap",
            "assigned_task_count",
            "unassigned_task_count",
            "summary",
            "error_message",
            "created_at",
        ]
        read_only_fields = [
            "status",
            "started_at",
            "finished_at",
            "objective_value",
            "mip_gap",
            "assigned_task_count",
            "unassigned_task_count",
            "summary",
            "error_message",
            "created_at",
        ]


class ScheduleSerializer(serializers.ModelSerializer):
    task = TaskSerializer(read_only=True)
    task_id = serializers.PrimaryKeyRelatedField(
        source="task",
        queryset=Task.objects.all(),
        write_only=True
    )

    technician = TechnicianSerializer(read_only=True)
    technician_id = serializers.PrimaryKeyRelatedField(
        source="technician",
        queryset=Technician.objects.all(),
        write_only=True
    )

    optimization_run = OptimizationRunSerializer(read_only=True)
    optimization_run_id = serializers.PrimaryKeyRelatedField(
        source="optimization_run",
        queryset=OptimizationRun.objects.all(),
        write_only=True,
        required=False,
        allow_null=True
    )

    class Meta:
        model = Schedule
        fields = [
            "id",
            "task",
            "task_id",
            "technician",
            "technician_id",
            "optimization_run",
            "optimization_run_id",
            "start_time",
            "end_time",
            "sequence_order",
            "travel_time_min",
            "travel_distance_km",
            "source",
            "is_manual_override",
            "notes",
            "created_at",
        ]


class AvailabilityRequestSerializer(serializers.ModelSerializer):
    technician = TechnicianSerializer(read_only=True)
    technician_id = serializers.PrimaryKeyRelatedField(
        source="technician",
        queryset=Technician.objects.all(),
        write_only=True,
        required=False
    )
    reviewed_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = AvailabilityRequest
        fields = [
            "id",
            "technician",
            "technician_id",
            "start_datetime",
            "end_datetime",
            "reason",
            "status",
            "reviewed_by",
            "reviewed_at",
            "created_at",
        ]
        read_only_fields = ["status", "reviewed_by", "reviewed_at", "created_at"]

    def validate(self, attrs):
        start_datetime = attrs.get("start_datetime")
        end_datetime = attrs.get("end_datetime")

        if start_datetime and end_datetime and end_datetime <= start_datetime:
            raise serializers.ValidationError("Bitiş zamanı başlangıçtan sonra olmalıdır.")

        if start_datetime and start_datetime < timezone.now():
            raise serializers.ValidationError("Geçmiş tarih için request oluşturulamaz.")

        return attrs

    def create(self, validated_data):
        request = self.context["request"]

        # Technician kendi request'ini oluşturuyorsa technician otomatik gelsin
        if hasattr(request.user, "profile") and request.user.profile.role == UserRole.TECH:
            try:
                validated_data["technician"] = request.user.technician_profile
            except Technician.DoesNotExist:
                raise serializers.ValidationError("Bu kullanıcıya bağlı technician profili bulunamadı.")

        return super().create(validated_data)


class AvailabilityRequestReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = AvailabilityRequest
        fields = ["status"]

    def validate_status(self, value):
        if value not in [RequestStatus.APPROVED, RequestStatus.REJECTED]:
            raise serializers.ValidationError("Status sadece APPROVED veya REJECTED olabilir.")
        return value


class DistanceMatrixCacheSerializer(serializers.ModelSerializer):
    class Meta:
        model = DistanceMatrixCache
        fields = "__all__"


class AuditLogSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True)

    class Meta:
        model = AuditLog
        fields = "__all__"