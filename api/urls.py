from django.urls import path, include
from rest_framework.routers import DefaultRouter
from api.demo_showcase_views import ShowcaseRoutesView
from .simulation_run_views import SimulationRunView
from .simulation_reset_views import SimulationResetView
from .admin_views import AdminHQListView, AdminHQStateView, AdminGenerateView
from .location_views import MyLocationUpdateView
from .clock_views import SetClockView
from .views import MyOptimizedRouteView
from .views import (
    SupervisorGroupViewSet,
    PlanningPeriodViewSet,
    UnitViewSet,
    TechnicianViewSet,
    TaskTypeViewSet,
    TaskViewSet,
    ScheduleViewSet,
    AvailabilityRequestViewSet,
    OptimizationRunViewSet,
    test_unit_distance,
)
from .dispatch_views import DispatchTaskView
from .me_view import MeView
from .leave_views import (
    LeaveRequestCreateView, LeaveRequestListView, LeaveRequestDecisionView,
)
from .simulation_views import SimulationRoutesView, SimulationMapView, SimulationDemoRoutesView
from .dashboard_views import DemoDashboardStateView
from .add_technician_view import (
    AddTechnicianView, RemoveTechnicianView, ReactivateTechnicianView,
    TechnicianChangeImpactPreviewView,
)
from .report_views import (
    ReportMonthsView, MonthlyReportView, MonthlyReportExportView,
)
from .unit_history_views import (
    UnitHistorySummaryView, UnitHistoryDetailView, UnitHistoryExportView,
)
from .overview_views import (
    MaintenanceOverviewView, CallbackOverviewView,
)
from .daily_report_views import DailyReportView
from .repair_views import RepairPanelView, RepairDispatchView, RepairDispatchUnitsView, ClearRepairsView
from .callback_incident_views import CallbackIncidentCenterView, CallbackIncidentExportView
from .monthly_log_views import MonthlyLogView

router = DefaultRouter()
router.register(r"groups", SupervisorGroupViewSet, basename="group")
router.register(r"planning-periods", PlanningPeriodViewSet, basename="planning-period")
router.register(r"units", UnitViewSet, basename="unit")
router.register(r"technicians", TechnicianViewSet, basename="technician")
router.register(r"task-types", TaskTypeViewSet, basename="task-type")
router.register(r"tasks", TaskViewSet, basename="task")
router.register(r"schedules", ScheduleViewSet, basename="schedule")
router.register(r"availability-requests", AvailabilityRequestViewSet, basename="availability-request")
router.register(r"optimization-runs", OptimizationRunViewSet, basename="optimization-run")

urlpatterns = [
    path("test-distance/", test_unit_distance, name="test-distance"),
    # technician management -- BEFORE the router so these aren't shadowed by
    # the router's technicians/<pk>/ detail routes
    path("technicians/add/", AddTechnicianView.as_view()),
    path("technicians/impact-preview/", TechnicianChangeImpactPreviewView.as_view()),
    path("technicians/<int:pk>/remove/", RemoveTechnicianView.as_view()),
    path("technicians/<int:pk>/reactivate/", ReactivateTechnicianView.as_view()),
    # reports + unit history -- BEFORE the router so the units/ and technicians/
    # detail routes don't shadow them
    path("reports/months/", ReportMonthsView.as_view()),
    path("reports/monthly/", MonthlyReportView.as_view()),
    path("reports/monthly/export/", MonthlyReportExportView.as_view()),
    path("units/history/", UnitHistorySummaryView.as_view()),
    path("units/history/export/", UnitHistoryExportView.as_view()),
    path("units/<int:unit_id>/history/", UnitHistoryDetailView.as_view()),
    path("overview/maintenance/", MaintenanceOverviewView.as_view()),
    path("overview/callbacks/", CallbackIncidentCenterView.as_view()),
    path("overview/callbacks/export/", CallbackIncidentExportView.as_view()),
    path("overview/monthly-log/", MonthlyLogView.as_view()),
    path("overview/daily-report/", DailyReportView.as_view()),
    path("demo/showcase-routes/", ShowcaseRoutesView.as_view(), name="showcase-routes"),
    path("", include(router.urls)),
    path('my-route/', MyOptimizedRouteView.as_view(), name='my-route'),
    path("dispatch-task/", DispatchTaskView.as_view(), name="dispatch-task"),
    path("dashboard/state/", DemoDashboardStateView.as_view(), name="dashboard-state"),
    path("me/", MeView.as_view()),
    path("leave-request/", LeaveRequestCreateView.as_view()),
    path("leave-requests/", LeaveRequestListView.as_view()),
    path("leave-request/<int:pk>/decision/", LeaveRequestDecisionView.as_view()),
    path("simulation/routes/", SimulationRoutesView.as_view()),
    path("simulation/map/", SimulationMapView.as_view()),
    path("simulation/demo-routes/", SimulationDemoRoutesView.as_view()),
    path("repair/panel/", RepairPanelView.as_view()),
    path("repair/dispatch/", RepairDispatchView.as_view()),
    path("repair/dispatch-units/", RepairDispatchUnitsView.as_view()),
    path("simulation/run/", SimulationRunView.as_view(), name="simulation-run"),
    path("repair/clear/", ClearRepairsView.as_view()),
    path("my-location/", MyLocationUpdateView.as_view(), name="my-location"),
    path("clock/set/", SetClockView.as_view(), name="set-clock"),
    path("simulation/reset/", SimulationResetView.as_view(), name="simulation-reset"),
    path("admin/hqs/", AdminHQListView.as_view()),
    path("admin/hq-state/", AdminHQStateView.as_view()),
    path("admin/generate/", AdminGenerateView.as_view()),
]
