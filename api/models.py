from datetime import date, time , timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


# =========================================================
# 1) ORTAK CHOICES / ENUMS
# =========================================================

class UserRole(models.TextChoices):
    ADMIN = "ADMIN", "Admin"
    SUP = "SUP", "Supervisor"
    TECH = "TECH", "Technician"


class UnitType(models.TextChoices):
    ELEVATOR = "ELEVATOR", "Asansör"
    ESCALATOR = "ESCALATOR", "Yürüyen Merdiven"


class TechnicianRole(models.TextChoices):
    MAINTENANCE = "MAINTENANCE", "Bakım Teknisyeni"
    CALLBACK = "CALLBACK", "Arıza (Callback) Teknisyeni"


class SpecialtyType(models.TextChoices):
    ELEVATOR = "ELEVATOR", "Asansör Uzmanı"
    ESCALATOR = "ESCALATOR", "Yürüyen Merdiven Uzmanı"
    BOTH = "BOTH", "Her İkisi"


class ExperienceLevel(models.IntegerChoices):
    JUNIOR = 1, "Junior"
    MID = 2, "Mid"
    SENIOR = 3, "Senior"
    EXPERT = 4, "Expert"
    MASTER = 5, "Master"


class OperationType(models.TextChoices):
    MAINTENANCE = "MAINTENANCE", "Planned Maintenance"
    CALLBACK = "CALLBACK", "Callback / Arıza"
    FOLLOW_UP = "FOLLOW_UP", "Callback Follow-up"


class TaskStatus(models.TextChoices):
    PENDING = "PENDING", "Beklemede"
    ASSIGNED = "ASSIGNED", "Atandı"
    IN_PROGRESS = "IN_PROGRESS", "Devam Ediyor"
    COMPLETED = "COMPLETED", "Tamamlandı"
    CANCELLED = "CANCELLED", "İptal Edildi"
    UNASSIGNED = "UNASSIGNED", "Atanamadı"

class MaintenanceType(models.TextChoices):
    A = "A", "A Bakımı"
    B = "B", "B Bakımı"
    C = "C", "C Bakımı"


class CallbackPriority(models.TextChoices):
    AA = "AA", "AA"
    A = "A", "A"
    B = "B", "B"
    C = "C", "C"
    D = "D", "D"


class RequestStatus(models.TextChoices):
    PENDING = "PENDING", "Beklemede"
    APPROVED = "APPROVED", "Onaylandı"
    REJECTED = "REJECTED", "Reddedildi"
    CANCELLED = "CANCELLED", "İptal Edildi"


class RunStatus(models.TextChoices):
    DRAFT = "DRAFT", "Taslak"
    RUNNING = "RUNNING", "Çalışıyor"
    FEASIBLE = "FEASIBLE", "Çözüm Bulundu"
    INFEASIBLE = "INFEASIBLE", "Çözümsüz"
    FAILED = "FAILED", "Başarısız"
    CANCELLED = "CANCELLED", "İptal Edildi"


class ScheduleSource(models.TextChoices):
    AUTO = "AUTO", "Optimization"
    MANUAL = "MANUAL", "Manual Override"


class AuditAction(models.TextChoices):
    CREATE = "CREATE", "Create"
    UPDATE = "UPDATE", "Update"
    DELETE = "DELETE", "Delete"
    APPROVE = "APPROVE", "Approve"
    REJECT = "REJECT", "Reject"
    RUN_OPTIMIZATION = "RUN_OPTIMIZATION", "Run Optimization"
    MANUAL_ASSIGN = "MANUAL_ASSIGN", "Manual Assign"


# =========================================================
# 2) KULLANICI / ROL / GRUP YAPISI
# =========================================================

class UserProfile(models.Model):
    """
    Django User tablosunu bozmadan rol bilgisini burada tutuyoruz.
    Rapor ADMIN / SUP / TECH rol ayrımını açıkça istiyor.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=10, choices=UserRole.choices)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    department = models.CharField(max_length=100, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"

    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN

    @property
    def is_supervisor(self):
        return self.role == UserRole.SUP

    @property
    def is_technician(self):
        return self.role == UserRole.TECH


class SupervisorGroup(models.Model):
    """
    Rapor SUP'ların kendi teknisyen gruplarını yönettiğini söylüyor.
    """
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=30, unique=True)
    description = models.TextField(blank=True, null=True)

    supervisor = models.OneToOneField(
        User,
        on_delete=models.PROTECT,
        related_name="supervised_group",
        help_text="Bu grubun sorumlu supervisor kullanıcısı"
    )

    region = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Supervisor Group"
        verbose_name_plural = "Supervisor Groups"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def clean(self):
        super().clean()

        # Supervisor atanmış kullanıcının rolü SUP olmalı
        if hasattr(self.supervisor, "profile"):
            if self.supervisor.profile.role != UserRole.SUP:
                raise ValidationError({"supervisor": "Atanan kullanıcı SUP rolünde olmalıdır."})
        else:
            raise ValidationError({"supervisor": "Supervisor kullanıcısının UserProfile kaydı bulunmalıdır."})


# =========================================================
# 3) PLANLAMA DÖNEMİ
# =========================================================

class PlanningPeriod(models.Model):
    """
    Rapor: Admin planning period seçer ve optimization run başlatır.
    """
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()

    is_locked = models.BooleanField(default=False, help_text="Sonuçlar onaylandıysa kilitlenebilir.")
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="created_planning_periods"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Planning Period"
        verbose_name_plural = "Planning Periods"
        ordering = ["-start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["start_date", "end_date"],
                name="unique_planning_period_dates"
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.start_date} - {self.end_date})"

    def clean(self):
        super().clean()
        if self.end_date < self.start_date:
            raise ValidationError({"end_date": "Bitiş tarihi başlangıç tarihinden önce olamaz."})


# =========================================================
# 4) ÜNİTE / LOKASYON
# =========================================================

class Unit(models.Model):
    """
    Rapor: Units tablo geospatial source of truth.
    """
    unit_name = models.CharField(max_length=200, verbose_name="Bina/Ünite Adı")
    unit_code = models.CharField(max_length=50, unique=True, verbose_name="Ünite Kodu")
    unit_type = models.CharField(
        max_length=20,
        choices=UnitType.choices,
        default=UnitType.ELEVATOR,
        verbose_name="Ünite Tipi",
    )

    brand = models.CharField(max_length=100, blank=True, null=True)
    model_name = models.CharField(max_length=100, blank=True, null=True)

    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100, default="Istanbul")
    district = models.CharField(max_length=100, blank=True, null=True)

    venue_type = models.CharField(
    max_length=50,
    blank=True,
    null=True,
    verbose_name="Konum Tipi"
)

    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=[
            MinValueValidator(Decimal("-90.000000")),
            MaxValueValidator(Decimal("90.000000")),
        ],
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=[
            MinValueValidator(Decimal("-180.000000")),
            MaxValueValidator(Decimal("180.000000")),
        ],
    )

    # Özellikle escalator için işletme saatleri dışında servis gerekebilir
    operating_hours_start = models.TimeField(default=time(9, 0), blank=True, null=True)
    operating_hours_end = models.TimeField(default=time(18, 0), blank=True, null=True)

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Unit"
        verbose_name_plural = "Units"
        ordering = ["unit_name"]

    def __str__(self):
        return f"{self.unit_name} ({self.get_unit_type_display()})"

    def clean(self):
        super().clean()

        if (
            self.operating_hours_start
            and self.operating_hours_end
            and self.operating_hours_end <= self.operating_hours_start
        ):
            raise ValidationError(
                {"operating_hours_end": "Bitiş saati başlangıç saatinden sonra olmalıdır."}
            )


# =========================================================
# 5) TEKNİSYEN
# =========================================================

class Technician(models.Model):
    """
    Rapor: TECH login olur, kendi görevini görür.
    SUP kendi teknisyen grubunu yönetir.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="technician_profile"
    )

    employee_code = models.CharField(max_length=30, unique=True)
    competency_code = models.CharField(
    max_length=50,
    blank=True,
    null=True,
    verbose_name="Yetkinlik Kodu"
    )
    full_name = models.CharField(max_length=100, verbose_name="Ad Soyad")
    phone = models.CharField(max_length=20, blank=True, null=True)

    group = models.ForeignKey(
        SupervisorGroup,
        on_delete=models.PROTECT,
        related_name="technicians"
    )

    tech_role = models.CharField(
        max_length=20,
        choices=TechnicianRole.choices,
        verbose_name="Görev Tipi",
    )
    specialty = models.CharField(
        max_length=20,
        choices=SpecialtyType.choices,
        default=SpecialtyType.ELEVATOR,
        verbose_name="Uzmanlık Alanı",
    )

    experience_level = models.IntegerField(
        choices=ExperienceLevel.choices,
        default=ExperienceLevel.JUNIOR,
    )

    # Bu alan anlık kullanım için kalabilir ama asıl planlama kısıtı AvailabilityRequest'ten gelmeli
    is_available = models.BooleanField(default=True, verbose_name="Genel olarak aktif/müsait mi?")
    is_active_employee = models.BooleanField(default=True)

    # Son bilinen konum - mobil güncelleme için ileride kullanılabilir
    current_latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("-90.000000")),
            MaxValueValidator(Decimal("90.000000")),
        ],
    )
    current_longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("-180.000000")),
            MaxValueValidator(Decimal("180.000000")),
        ],
    )
    # last GPS report time — distinguishes live (gps) vs estimated position
    last_location_at = models.DateTimeField(null=True, blank=True)
    work_start = models.TimeField(default=time(8, 0))
    work_end = models.TimeField(default=time(17, 0))

    # kapasiteyi görev sayısı yerine dakika tutmak optimizasyon için daha anlamlıdır
    daily_capacity_min = models.PositiveIntegerField(default=480, help_text="Dakika bazlı günlük kapasite")
    max_overtime_min = models.PositiveIntegerField(default=60, help_text="İzin verilen maksimum mesai (dakika)")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Technician"
        verbose_name_plural = "Technicians"
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name} ({self.get_tech_role_display()})"

    def clean(self):
        super().clean()

        if hasattr(self.user, "profile"):
            if self.user.profile.role != UserRole.TECH:
                raise ValidationError({"user": "Technician kaydı yalnızca TECH rolündeki kullanıcıya bağlanabilir."})
        else:
            raise ValidationError({"user": "Bu kullanıcı için UserProfile bulunamadı."})

        if self.work_end <= self.work_start:
            raise ValidationError({"work_end": "Mesai bitiş saati başlangıçtan sonra olmalıdır."})


# =========================================================
# 6) GÖREV TİPİ / SLA / UZMANLIK EŞLEŞMESİ
# =========================================================

class TaskType(models.Model):
    """
    Rapor: operation type, estimated duration, SLA target gibi parametreler tanımlanmalı.
    """
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=100)

    operation_type = models.CharField(
        max_length=20,
        choices=OperationType.choices
    )

    maintenance_type = models.CharField(
        max_length=20,
        choices=MaintenanceType.choices,
        null=True,
        blank=True,
        help_text="Sadece MAINTENANCE görevleri için bakım tipi"
    )

    # Bu görev tipi için gereken ana uzmanlık
    required_specialty = models.CharField(
        max_length=20,
        choices=SpecialtyType.choices,
        default=SpecialtyType.ELEVATOR
    )

    # Bu görev tipi için gereken teknisyen rolü
    required_technician_role = models.CharField(
        max_length=20,
        choices=TechnicianRole.choices,
        default=TechnicianRole.MAINTENANCE
    )

    base_duration_min = models.PositiveIntegerField(help_text="Varsayılan işlem süresi (dakika)")
    sla_target_min = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="SLA hedef süresi (dakika). Özellikle callback için kullanılabilir."
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Task Type"
        verbose_name_plural = "Task Types"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_operation_type_display()})"


# =========================================================
# 7) TASK / İŞ EMRİ
# =========================================================

class Task(models.Model):
    """
    Rapor: Tasks fact table'dır.
    Schedules ayrı derived data olarak tutulmalıdır.
    """
    task_no = models.CharField(max_length=50, unique=True, verbose_name="İş Emri No")

    unit = models.ForeignKey(
        Unit,
        on_delete=models.CASCADE,
        related_name="tasks"
    )

    planning_period = models.ForeignKey(
        PlanningPeriod,
        on_delete=models.PROTECT,
        related_name="tasks"
    )

    task_type = models.ForeignKey(
        TaskType,
        on_delete=models.PROTECT,
        related_name="tasks"
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="created_tasks"
    )

    # Supervisor callback açtığında hangi grup için açıldığını tutmak faydalı
    assigned_group = models.ForeignKey(
        SupervisorGroup,
        on_delete=models.PROTECT,
        related_name="tasks",
        null=True,
        blank=True
    )

    description = models.TextField(blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=TaskStatus.choices,
        default=TaskStatus.PENDING
    )

    # callback ise priority gerekir; maintenance için boş kalabilir
    priority = models.CharField(
        max_length=2,
        choices=CallbackPriority.choices,
        blank=True,
        null=True
    )

    is_follow_up = models.BooleanField(default=False)
    parent_task = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="follow_up_tasks"
    )

    estimated_duration_min = models.PositiveIntegerField(help_text="Bu iş emrine özel tahmini süre (dakika)")

    # callback veya time window gereksinimi için
    earliest_start = models.DateTimeField(null=True, blank=True)
    latest_finish = models.DateTimeField(null=True, blank=True)

    # callback çağrısı veya planlama başlangıcı
    release_time = models.DateTimeField(default=timezone.now)

    # optimizasyon sonrası atanamazsa işaretlenmeli
    is_unassigned = models.BooleanField(default=False)
    unassigned_reason = models.TextField(blank=True, null=True)

    # bu iş gerçekten aktif mi
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Task"
        verbose_name_plural = "Tasks"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.task_no} - {self.task_type.name} - {self.unit.unit_name}"

    def clean(self):
        super().clean()

        if self.latest_finish and self.earliest_start and self.latest_finish <= self.earliest_start:
            raise ValidationError({"latest_finish": "latest_finish, earliest_start'tan sonra olmalıdır."})

        # Follow-up ise parent task beklenir
        if self.is_follow_up and not self.parent_task:
            raise ValidationError({"parent_task": "Follow-up görev için parent_task zorunludur."})

        # Callback için priority beklenir
        if self.task_type.operation_type == OperationType.CALLBACK and not self.priority:
            raise ValidationError({"priority": "Callback görevlerinde priority zorunludur."})

        # Maintenance görevinde priority boş bırakılabilir
        if self.task_type.operation_type == OperationType.MAINTENANCE and self.priority:
            raise ValidationError({"priority": "Bakım görevlerinde callback priority kullanılmaz."})

        # Assigned group boşsa ve creator supervisor ise creator'ın grubuna bağlanması tercih edilir
        # Bunu otomatik save içinde de yapabiliriz ama şimdilik validation basit kalsın.

    @property
    def is_callback(self):
        return self.task_type.operation_type == OperationType.CALLBACK

    @property
    def is_planned_maintenance(self):
        return self.task_type.operation_type == OperationType.MAINTENANCE


# =========================================================
# 8) OPTİMİZASYON KOŞUSU
# =========================================================

class OptimizationRun(models.Model):
    """
    Rapor: Admin planning period seçer, system modeli kurar,
    çözer, sonucu DB'ye yazar, unassigned taskları işaretler.
    """
    planning_period = models.ForeignKey(
        PlanningPeriod,
        on_delete=models.PROTECT,
        related_name="optimization_runs"
    )

    triggered_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="optimization_runs"
    )

    status = models.CharField(
        max_length=20,
        choices=RunStatus.choices,
        default=RunStatus.DRAFT
    )

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    solver_name = models.CharField(max_length=50, default="Gurobi")
    solver_time_limit_sec = models.PositiveIntegerField(default=60)
    objective_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    mip_gap = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)

    assigned_task_count = models.PositiveIntegerField(default=0)
    unassigned_task_count = models.PositiveIntegerField(default=0)

    summary = models.TextField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Optimization Run"
        verbose_name_plural = "Optimization Runs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Run #{self.id} - {self.planning_period.name} - {self.get_status_display()}"

    def clean(self):
        super().clean()

        if self.finished_at and self.started_at and self.finished_at < self.started_at:
            raise ValidationError({"finished_at": "finished_at, started_at'tan önce olamaz."})


# =========================================================
# 9) SCHEDULE / OPTİMİZASYON SONUCU
# =========================================================

class Schedule(models.Model):
    """
    Rapor: Schedules derived data'dır.
    Kullanıcı doğrudan girmez; optimization engine üretir.
    """
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="schedules"
    )

    technician = models.ForeignKey(
        Technician,
        on_delete=models.PROTECT,
        related_name="schedules"
    )

    optimization_run = models.ForeignKey(
        OptimizationRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schedules"
    )

    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    sequence_order = models.PositiveIntegerField(default=1)

    travel_time_min = models.PositiveIntegerField(null=True, blank=True)
    travel_distance_km = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    source = models.CharField(
        max_length=10,
        choices=ScheduleSource.choices,
        default=ScheduleSource.AUTO
    )
    is_manual_override = models.BooleanField(default=False)

    notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Schedule"
        verbose_name_plural = "Schedules"
        ordering = ["start_time", "sequence_order"]
        constraints = [
            # Aynı run içinde aynı task için birden fazla schedule olmasın
            models.UniqueConstraint(
                fields=["task", "optimization_run"],
                name="unique_task_per_optimization_run"
            )
        ]

    def __str__(self):
        return f"{self.task.task_no} -> {self.technician.full_name}"

    def clean(self):
        super().clean()

        if self.end_time <= self.start_time:
            raise ValidationError({"end_time": "Bitiş zamanı başlangıçtan sonra olmalıdır."})

        # Skill-role uyumluluğu (artık BOTH rol yok: tam eşleşme)
        required_role = self.task.task_type.required_technician_role
        if self.technician.tech_role != required_role:
            raise ValidationError({
                "technician": "Bu teknisyen görev tipinin gerektirdiği role uygun değil."
            })

        required_specialty = self.task.task_type.required_specialty
        if self.technician.specialty not in [required_specialty, SpecialtyType.BOTH]:
            raise ValidationError({
                "technician": "Bu teknisyen görev tipinin gerektirdiği uzmanlığa uygun değil."
            })

        # Supervisor group kısıtı
        if self.task.assigned_group and self.technician.group_id != self.task.assigned_group_id:
            raise ValidationError({
                "technician": "Teknisyen task'ın ait olduğu supervisor grubunda değil."
            })


# =========================================================
# 10) TEKNİSYEN MÜSAİTLİK / İZİN TALEBİ
# =========================================================

class AvailabilityRequest(models.Model):
    """
    Rapor: TECH request açar, SUP onaylar/reddeder,
    approved request planlamayı etkiler.
    """
    technician = models.ForeignKey(
        Technician,
        on_delete=models.CASCADE,
        related_name="availability_requests"
    )

    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()

    reason = models.TextField(blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=RequestStatus.choices,
        default=RequestStatus.PENDING
    )

    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_availability_requests"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Availability Request"
        verbose_name_plural = "Availability Requests"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.technician.full_name} - {self.status} ({self.start_datetime} / {self.end_datetime})"

    def clean(self):
        super().clean()

        if self.end_datetime <= self.start_datetime:
            raise ValidationError({"end_datetime": "Bitiş zamanı başlangıçtan sonra olmalıdır."})

        # Raporda geçmiş tarihli request reddedilmeli
        if self.start_datetime < timezone.now():
            raise ValidationError({"start_datetime": "Geçmiş tarih için request oluşturulamaz."})

        if self.reviewed_by:
            if not hasattr(self.reviewed_by, "profile"):
                raise ValidationError({"reviewed_by": "reviewed_by kullanıcısının UserProfile kaydı yok."})

            if self.reviewed_by.profile.role != UserRole.SUP:
                raise ValidationError({"reviewed_by": "Request'i yalnızca SUP rolü inceleyebilir."})

            # İsteği inceleyen supervisor, teknisyenin grubunun supervisor'ı olmalı
            group_supervisor_id = self.technician.group.supervisor_id
            if self.reviewed_by_id != group_supervisor_id:
                raise ValidationError({
                    "reviewed_by": "Bu request sadece teknisyenin kendi supervisor'ı tarafından incelenebilir."
                })


# =========================================================
# 11) DISTANCE CACHE
# =========================================================

class DistanceMatrixCache(models.Model):
    """
    Rapor risk kısmında Google Maps maliyetini azaltmak için local caching öneriyor.
    """
    origin_unit = models.ForeignKey(
        Unit,
        on_delete=models.CASCADE,
        related_name="distance_origin_rows"
    )
    destination_unit = models.ForeignKey(
        Unit,
        on_delete=models.CASCADE,
        related_name="distance_destination_rows"
    )

    distance_meters = models.PositiveIntegerField()
    duration_seconds = models.PositiveIntegerField()

    provider = models.CharField(max_length=50, default="GOOGLE_MAPS")
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Distance Matrix Cache"
        verbose_name_plural = "Distance Matrix Cache"
        constraints = [
            models.UniqueConstraint(
                fields=["origin_unit", "destination_unit", "provider"],
                name="unique_distance_cache_row"
            )
        ]

    def __str__(self):
        return f"{self.origin_unit.unit_name} -> {self.destination_unit.unit_name}"


# =========================================================
# 12) AUDIT LOG
# =========================================================

class AuditLog(models.Model):
    """
    Rapor auditability istiyor:
    optimization sonuçları ve manual override'lar trace edilebilir olmalı.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs"
    )

    action = models.CharField(max_length=30, choices=AuditAction.choices)
    target_model = models.CharField(max_length=100)
    target_id = models.PositiveIntegerField(null=True, blank=True)

    message = models.TextField(blank=True, null=True)
    metadata_json = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} - {self.target_model} ({self.target_id})"

# =========================================================
# 13) İZİN TALEBİ (LEAVE REQUEST)
# =========================================================

class LeaveRequest(models.Model):
    class LeaveStatus(models.TextChoices):
        PENDING = "PENDING", "Beklemede"
        APPROVED = "APPROVED", "Onaylandı"
        REJECTED = "REJECTED", "Reddedildi"
        RETURNED = "RETURNED", "İşe Döndü"

    technician = models.ForeignKey(
        Technician, on_delete=models.CASCADE, related_name="leave_requests"
    )
    leave_type = models.CharField(max_length=50, default="Medical Leave")
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField(blank=True, null=True)
    status = models.CharField(
        max_length=10, choices=LeaveStatus.choices, default=LeaveStatus.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.technician.full_name} - {self.leave_type} ({self.status})"

class UnitMaintenanceState(models.Model):
    unit = models.OneToOneField(
        "Unit",
        on_delete=models.CASCADE,
        related_name="maintenance_state",
        verbose_name="Ünite",
    )
    last_a_date = models.DateField(blank=True, null=True, verbose_name="Son A Bakımı")
    last_b_date = models.DateField(blank=True, null=True, verbose_name="Son B Bakımı")
    last_c_date = models.DateField(blank=True, null=True, verbose_name="Son C Bakımı")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Unit Maintenance State"
        verbose_name_plural = "Unit Maintenance States"

    C_DAYS = 28
    B_DAYS = 168
    A_DAYS = 336

    def due_type(self, on_date):
        def overdue(last, interval):
            if last is None:
                return True
            return (on_date - last).days >= interval
        if overdue(self.last_a_date, self.A_DAYS):
            return "A"
        if overdue(self.last_b_date, self.B_DAYS):
            return "B"
        if overdue(self.last_c_date, self.C_DAYS):
            return "C"
        return None

    def complete(self, mtype, on_date):
        while on_date.weekday() >= 5:      # weekend completion -> next weekday
            on_date += timedelta(days=1)
        if mtype == "A":
            self.last_a_date = on_date
            self.last_b_date = on_date
            self.last_c_date = on_date
        elif mtype == "B":
            self.last_b_date = on_date
            self.last_c_date = on_date
        elif mtype == "C":
            self.last_c_date = on_date
        self.save()