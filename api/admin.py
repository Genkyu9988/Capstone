from django.contrib import admin

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
)

admin.site.register(UserProfile)
admin.site.register(SupervisorGroup)
admin.site.register(PlanningPeriod)
admin.site.register(Unit)
admin.site.register(Technician)
admin.site.register(TaskType)
admin.site.register(Task)
admin.site.register(OptimizationRun)
admin.site.register(Schedule)
admin.site.register(AvailabilityRequest)
admin.site.register(DistanceMatrixCache)
admin.site.register(AuditLog)