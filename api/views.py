from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated , AllowAny
from rest_framework.response import Response
import base64
from rest_framework.views import APIView
from rest_framework.response import Response
from django.contrib.auth import authenticate
from .models import Schedule
from .active_day import get_active_date, get_active_datetime
from datetime import datetime, time as dtime
from .dashboard_views import (
    _build_timeline, _road_position_at, _position_at, DAY_START_HOUR,
)

from .models import (
    UserRole,
    SupervisorGroup,
    PlanningPeriod,
    Unit,
    Technician,
    TaskType,
    Task,
    OptimizationRun,
    Schedule,
    AvailabilityRequest,
    AuditLog,
    AuditAction,
    RunStatus,
    RequestStatus,
)
from .serializers import (
    SupervisorGroupSerializer,
    PlanningPeriodSerializer,
    UnitSerializer,
    TechnicianSerializer,
    TaskTypeSerializer,
    TaskSerializer,
    OptimizationRunSerializer,
    ScheduleSerializer,
    AvailabilityRequestSerializer,
    AvailabilityRequestReviewSerializer,
)
from .permissions import (
    IsAdminRole,
    IsSupervisorRole,
    IsTechnicianRole,
    IsAdminOrSupervisor,
    IsAnyProjectRole,
)


def user_role(user):
    if hasattr(user, "profile"):
        return user.profile.role
    return None


def create_audit_log(user, action, target_model, target_id=None, message=None, metadata_json=None):
    AuditLog.objects.create(
        user=user,
        action=action,
        target_model=target_model,
        target_id=target_id,
        message=message,
        metadata_json=metadata_json or {},
    )


class SupervisorGroupViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SupervisorGroup.objects.select_related("supervisor").all()
    serializer_class = SupervisorGroupSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        role = user_role(self.request.user)

        if role == UserRole.ADMIN:
            return self.queryset

        if role == UserRole.SUP and hasattr(self.request.user, "supervised_group"):
            return self.queryset.filter(id=self.request.user.supervised_group.id)

        return self.queryset.none()


class PlanningPeriodViewSet(viewsets.ModelViewSet):
    queryset = PlanningPeriod.objects.select_related("created_by").all()
    serializer_class = PlanningPeriodSerializer
    permission_classes = [AllowAny]

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user)
        create_audit_log(
            self.request.user,
            AuditAction.CREATE,
            "PlanningPeriod",
            instance.id,
            "Planning period created."
        )


class UnitViewSet(viewsets.ModelViewSet):
    queryset = Unit.objects.all()
    serializer_class = UnitSerializer
    permission_classes = [AllowAny]

    def perform_create(self, serializer):
        instance = serializer.save()
        create_audit_log(self.request.user, AuditAction.CREATE, "Unit", instance.id, "Unit created.")

    def perform_update(self, serializer):
        instance = serializer.save()
        create_audit_log(self.request.user, AuditAction.UPDATE, "Unit", instance.id, "Unit updated.")


class TechnicianViewSet(viewsets.ModelViewSet):
    queryset = Technician.objects.select_related("user", "group", "group__supervisor").all()
    serializer_class = TechnicianSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        role = user_role(self.request.user)

        if role == UserRole.ADMIN:
            return self.queryset

        if role == UserRole.SUP and hasattr(self.request.user, "supervised_group"):
            return self.queryset.filter(group=self.request.user.supervised_group)

        return self.queryset.none()

    def perform_create(self, serializer):
        instance = serializer.save()
        create_audit_log(self.request.user, AuditAction.CREATE, "Technician", instance.id, "Technician created.")

    def perform_update(self, serializer):
        instance = serializer.save()
        create_audit_log(self.request.user, AuditAction.UPDATE, "Technician", instance.id, "Technician updated.")


class TaskTypeViewSet(viewsets.ModelViewSet):
    queryset = TaskType.objects.all()
    serializer_class = TaskTypeSerializer
    permission_classes = [AllowAny]


class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.select_related(
        "unit",
        "planning_period",
        "task_type",
        "created_by",
        "assigned_group",
        "parent_task",
    ).all()
    serializer_class = TaskSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        role = user_role(self.request.user)

        if role == UserRole.ADMIN:
            return self.queryset

        if role == UserRole.SUP and hasattr(self.request.user, "supervised_group"):
            return self.queryset.filter(assigned_group=self.request.user.supervised_group)

        if role == UserRole.TECH and hasattr(self.request.user, "technician_profile"):
            return self.queryset.filter(schedules__technician=self.request.user.technician_profile).distinct()

        return self.queryset.none()

    def perform_create(self, serializer):
        instance = serializer.save()
        create_audit_log(self.request.user, AuditAction.CREATE, "Task", instance.id, "Task created.")

    def perform_update(self, serializer):
        instance = serializer.save()
        create_audit_log(self.request.user, AuditAction.UPDATE, "Task", instance.id, "Task updated.")

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated, IsTechnicianRole], url_path="my-tasks")
    def my_tasks(self, request):
        technician = getattr(request.user, "technician_profile", None)
        if not technician:
            return Response({"detail": "Technician profile bulunamadı."}, status=400)

        tasks = self.queryset.filter(schedules__technician=technician).distinct()
        serializer = self.get_serializer(tasks, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated, IsSupervisorRole], url_path="supervisor-tasks")
    def supervisor_tasks(self, request):
        if not hasattr(request.user, "supervised_group"):
            return Response({"detail": "Supervisor group bulunamadı."}, status=400)

        tasks = self.queryset.filter(assigned_group=request.user.supervised_group)
        serializer = self.get_serializer(tasks, many=True)
        return Response(serializer.data)


class ScheduleViewSet(viewsets.ModelViewSet):
    queryset = Schedule.objects.select_related(
        "task",
        "task__unit",
        "task__task_type",
        "technician",
        "optimization_run",
    ).all()
    serializer_class = ScheduleSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        role = user_role(self.request.user)

        if role == UserRole.ADMIN:
            return self.queryset

        if role == UserRole.SUP and hasattr(self.request.user, "supervised_group"):
            return self.queryset.filter(technician__group=self.request.user.supervised_group)

        if role == UserRole.TECH and hasattr(self.request.user, "technician_profile"):
            return self.queryset.filter(technician=self.request.user.technician_profile)

        return self.queryset.none()

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated, IsTechnicianRole], url_path="my-schedule")
    def my_schedule(self, request):
        technician = getattr(request.user, "technician_profile", None)
        if not technician:
            return Response({"detail": "Technician profile bulunamadı."}, status=400)

        schedules = self.queryset.filter(technician=technician).order_by("start_time", "sequence_order")
        serializer = self.get_serializer(schedules, many=True)
        return Response(serializer.data)


class AvailabilityRequestViewSet(viewsets.ModelViewSet):
    queryset = AvailabilityRequest.objects.select_related(
        "technician",
        "technician__group",
        "reviewed_by",
    ).all()
    serializer_class = AvailabilityRequestSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        role = user_role(self.request.user)

        if role == UserRole.ADMIN:
            return self.queryset

        if role == UserRole.SUP and hasattr(self.request.user, "supervised_group"):
            return self.queryset.filter(technician__group=self.request.user.supervised_group)

        if role == UserRole.TECH and hasattr(self.request.user, "technician_profile"):
            return self.queryset.filter(technician=self.request.user.technician_profile)

        return self.queryset.none()

    def perform_create(self, serializer):
        instance = serializer.save()
        create_audit_log(
            self.request.user,
            AuditAction.CREATE,
            "AvailabilityRequest",
            instance.id,
            "Availability request created."
        )

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated, IsTechnicianRole], url_path="my-requests")
    def my_requests(self, request):
        technician = getattr(request.user, "technician_profile", None)
        if not technician:
            return Response({"detail": "Technician profile bulunamadı."}, status=400)

        requests_qs = self.queryset.filter(technician=technician)
        serializer = self.get_serializer(requests_qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated, IsSupervisorRole], url_path="pending")
    def pending_requests(self, request):
        if not hasattr(request.user, "supervised_group"):
            return Response({"detail": "Supervisor group bulunamadı."}, status=400)

        qs = self.queryset.filter(
            technician__group=request.user.supervised_group,
            status=RequestStatus.PENDING
        )
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["patch"], permission_classes=[IsAuthenticated, IsSupervisorRole], url_path="review")
    def review_request(self, request, pk=None):
        availability_request = self.get_object()

        if availability_request.technician.group.supervisor != request.user:
            return Response(
                {"detail": "Bu request'i sadece ilgili supervisor inceleyebilir."},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = AvailabilityRequestReviewSerializer(
            availability_request,
            data=request.data,
            partial=True
        )
        serializer.is_valid(raise_exception=True)

        availability_request.status = serializer.validated_data["status"]
        availability_request.reviewed_by = request.user
        availability_request.reviewed_at = timezone.now()
        availability_request.save()

        action = (
            AuditAction.APPROVE
            if availability_request.status == RequestStatus.APPROVED
            else AuditAction.REJECT
        )

        create_audit_log(
            request.user,
            action,
            "AvailabilityRequest",
            availability_request.id,
            f"Availability request {availability_request.status.lower()}."
        )

        return Response(AvailabilityRequestSerializer(availability_request).data)


class OptimizationRunViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet
):
    queryset = OptimizationRun.objects.select_related("planning_period", "triggered_by").all()
    serializer_class = OptimizationRunSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        role = user_role(self.request.user)

        if role == UserRole.ADMIN:
            return self.queryset

        # Supervisor sadece kendi grubuna ait planning period task’larına bakacaksa
        # şimdilik tüm runları görebilir; istenirse daha da daraltılır.
        if role == UserRole.SUP:
            return self.queryset

        return self.queryset.none()

    @transaction.atomic
    def perform_create(self, serializer):
        run = serializer.save(
            triggered_by=self.request.user,
            status=RunStatus.RUNNING,
            started_at=timezone.now(),
        )

        create_audit_log(
            self.request.user,
            AuditAction.RUN_OPTIMIZATION,
            "OptimizationRun",
            run.id,
            "Optimization run started."
        )

        # Şimdilik mock davranış:
        # Gerçek Gurobi entegrasyonu gelene kadar run'ı FEASIBLE kapatıyoruz.
        # Sonra bunu services/optimization içine taşıyacağız.
        run.status = RunStatus.FEASIBLE
        run.finished_at = timezone.now()
        run.summary = "Mock optimization completed. Gurobi integration pending."
        run.assigned_task_count = 0
        run.unassigned_task_count = 0
        run.save()

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated, IsAdminOrSupervisor], url_path="results")
    def results(self, request, pk=None):
        run = self.get_object()
        schedules = Schedule.objects.filter(optimization_run=run).select_related(
            "task", "technician", "task__unit", "task__task_type"
        )
        serializer = ScheduleSerializer(schedules, many=True)
        return Response(serializer.data)

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from api.models import Unit
from api.services.maps.distance_service import get_or_create_unit_distance


@api_view(["GET"])
@permission_classes([AllowAny])
def test_unit_distance(request):
    origin = Unit.objects.first()

    if not origin:
        return Response({"error": "Database içinde Unit yok."}, status=400)

    destination = Unit.objects.exclude(id=origin.id).first()

    if not destination:
        return Response({"error": "Test için en az 2 Unit gerekiyor."}, status=400)

    data = get_or_create_unit_distance(origin, destination)

    return Response({
        "origin": str(origin),
        "destination": str(destination),
        "distance_meters": data["distance_meters"],
        "duration_seconds": data["duration_seconds"],
        "duration_minutes": round(data["duration_seconds"] / 60, 2),
        "from_cache": data["from_cache"],
        "source": data["source"],
    })
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import Schedule


class MyOptimizedRouteView(APIView):
    # 1. Disable strict global DRF restrictions so we can handle it manually for Mobile
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        # 2. Read the Auth Header sent from Flutter
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Basic '):
            print("🔴 HATA: Header eksik (Missing Authorization)")
            return Response({"error": "No Auth Header"}, status=401)

        # 3. Decode the username and password from Flutter
        try:
            encoded_credentials = auth_header.split(' ')[1]
            decoded_credentials = base64.b64decode(encoded_credentials).decode('utf-8')
            username, password = decoded_credentials.split(':', 1)
        except Exception:
            print("🔴 HATA: Şifre çözülemedi (Format Error)")
            return Response({"error": "Format Error"}, status=400)

        # 4. Check against the Django database
        user = authenticate(username=username, password=password)
        if user is None:
            print(f"🔴 HATA: Şifre veya Kullanıcı adı yanlış! (Denenen: {username})")
            return Response({"error": "Invalid credentials"}, status=401)

        # 5. Check if they are a registered technician
        #    FIX: the reverse accessor for Technician.user is "technician_profile"
        #    (related_name in the model), NOT "technician". Using user.technician
        #    raised AttributeError, which was swallowed and returned 400 -> the
        #    Flutter app then showed "No tasks scheduled for today".
        try:
            technician = user.technician_profile
        except Technician.DoesNotExist:
            print(f"🔴 HATA: {username} bir teknisyen değil!")
            return Response({"error": "Not a technician"}, status=400)

        # 6. Build the Route Data
        start_lat = technician.current_latitude or 41.0082
        start_lon = technician.current_longitude or 28.9784

        # Only TODAY's stops, where "today" is the OPERATING clock (sim clock),
        # not the real device date. Without this filter the phone received the
        # technician's stops for the whole month benchmark, jumbled together.
        active_dt = get_active_datetime(request)
        active_day = active_dt.date()
        schedules = list(Schedule.objects
                         .filter(technician=technician,
                                 start_time__date=active_day,
                                 start_time__isnull=False)
                         .select_related("task", "task__unit", "task__task_type")
                         .order_by('sequence_order'))

        route_data = [
            {
                "stop_number": 0,
                "type": "DEPOT",
                "title": "Güne Başlangıç Noktası",
                "latitude": start_lat,
                "longitude": start_lon,
                "task_no": "START",
                "priority": "NONE"

            }
        ]

        for sched in schedules:
            route_data.append({
                "stop_number": sched.sequence_order,
                "type": "TASK",
                "title": sched.task.task_type.name,
                "latitude": sched.task.unit.latitude,
                "longitude": sched.task.unit.longitude,
                "task_no": sched.task.task_no,
                "priority": sched.task.priority or "NORMAL",
                "unit_name": sched.task.unit.unit_name,
                "duration_min": sched.task.estimated_duration_min,
            })

        # ---- real Google road geometry, identical to the supervisor map ----
        # IMPORTANT: use the technician's depot/current location as the route
        # origin. The older version used the first task as the origin, while
        # the supervisor dashboard timeline used the technician depot. That made
        # /api/my-route/ and /api/dashboard/state/ disagree at the same roll time.
        stop_coords = [(float(s.task.unit.latitude), float(s.task.unit.longitude))
                       for s in schedules]
        route_polyline = None
        geometry_source = None
        distance_km = None
        road_duration_min = None
        start_pos = (float(start_lat), float(start_lon))
        if len(stop_coords) >= 1:
            try:
                from .services.maps.route_geometry import build_route_geometry
                depot_geom = start_pos
                rest = [{"lat": lat, "lng": lng} for lat, lng in stop_coords]
                geom = build_route_geometry(depot_geom, rest)
                route_polyline = geom.get("points")
                geometry_source = geom.get("source")
                distance_km = geom.get("distance_km")
                road_duration_min = geom.get("duration_min")
            except Exception as exc:
                print(f"[my-route] road geometry failed ({exc}) -> straight legs.")

        # ---- estimated live position, driven by the operating clock --------
        # We deliberately IGNORE the device GPS here: on an emulator it can
        # report a bad/stale location. Instead we interpolate the technician
        # along the same depot -> stops geometry used by the supervisor map.
        current_position = None
        if schedules:
            tl_stops = [{
                "latitude": float(s.task.unit.latitude),
                "longitude": float(s.task.unit.longitude),
                "duration_min": s.task.estimated_duration_min,
            } for s in schedules]
            day_start = timezone.make_aware(
                datetime.combine(active_day, dtime(DAY_START_HOUR, 0)))
            timeline = _build_timeline(tl_stops, start_pos, day_start)
            if route_polyline and len(route_polyline) >= 2:
                cur = _road_position_at(route_polyline, tl_stops, timeline,
                                        day_start, active_dt)
            else:
                cur = _position_at(tl_stops, start_pos, timeline,
                                   day_start, active_dt)
            if cur:
                current_position = {"lat": cur[0], "lng": cur[1]}

        print(f"🟢 BAŞARILI: {technician.full_name} için rota gönderildi! "
              f"({len(route_data)} durak, geometry={geometry_source})")
        return Response({
            "technician": technician.full_name,
            "active_date": active_day.isoformat(),     # the operating-clock day
            "active_time": active_dt.isoformat(),      # the operating-clock time
            "current_position": current_position,      # {"lat","lng"} on the route
            "route_polyline": route_polyline,          # [[lat,lng],...] road path
            "geometry_source": geometry_source,        # GOOGLE_ROADS | CACHE | ...
            "distance_km": distance_km,
            "duration_min": road_duration_min,
            "route": route_data,
        })