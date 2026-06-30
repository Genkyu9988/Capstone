"""
api/repair_views.py
=============================================================================
A self-contained repair-dispatch section that works with the Demo Group data.

  GET  /api/repair/panel/    -> a simple page: pick fault type + location,
                                submit, and see which repair-capable technician
                                got the job + the full candidate scoreboard.

  POST /api/repair/dispatch/ -> creates the fault, filters repair-capable techs
                                (role REPAIR or BOTH + matching specialty),
                                measures each candidate's added travel
                                (cheapest-insertion via haversine), assigns the
                                winner, writes their Schedule, returns the
                                scoreboard.

No "favor" logic: the winner is simply whoever's route grows least.
Wire in api/urls.py:
    from .repair_views import RepairPanelView, RepairDispatchView
    path("repair/panel/",    RepairPanelView.as_view()),
    path("repair/dispatch/", RepairDispatchView.as_view()),
=============================================================================
"""
from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Q, Count
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import (
    PlanningPeriod, Schedule, Task, TaskType, Technician, Unit,
    TaskStatus, OperationType, SpecialtyType, TechnicianRole, CallbackPriority,
    UnitType,
)
from api.services.maps.distance_service import haversine_distance_km
from api.active_day import get_active_datetime
from api.services.maps.route_geometry import build_route_geometry

ROAD_FACTOR = 1.35
SPEED_KMH = 30.0

# fault type -> the specialty it needs + the unit type + default duration
FAULT_TYPES = {
    "Elevator Entrapment": dict(specialty=SpecialtyType.ELEVATOR,  unit=UnitType.ELEVATOR,  dur=60, pr=CallbackPriority.AA),
    "Elevator Fault":      dict(specialty=SpecialtyType.ELEVATOR,  unit=UnitType.ELEVATOR,  dur=45, pr=CallbackPriority.B),
    "Escalator Fault":     dict(specialty=SpecialtyType.ESCALATOR, unit=UnitType.ESCALATOR, dur=45, pr=CallbackPriority.B),
}


def _depot(t):
    return float(t.current_latitude), float(t.current_longitude)


def _route_km(depot, stops):
    """Greedy nearest-neighbour open-route length from depot through stops."""
    if not stops:
        return 0.0
    remaining = stops[:]
    cur = depot
    total = 0.0
    while remaining:
        nxt = min(remaining, key=lambda s: haversine_distance_km(cur[0], cur[1], s[0], s[1]))
        total += haversine_distance_km(cur[0], cur[1], nxt[0], nxt[1]) * ROAD_FACTOR
        cur = nxt
        remaining.remove(nxt)
    return total


def _tech_stops(tech, active_day=None):
    """Coordinates of a technician route.

    Dispatch must compare routes for the selected operating day, not all
    historical schedules. Otherwise a callback can be assigned based on old
    month-long data and then disappear from the live dashboard.
    """
    qs = Schedule.objects.filter(technician=tech)
    if active_day is not None:
        qs = qs.filter(start_time__date=active_day)
    out = []
    for s in qs.select_related("task__unit").order_by("sequence_order", "start_time"):
        u = s.task.unit
        if u and u.latitude is not None and u.longitude is not None:
            out.append((float(u.latitude), float(u.longitude)))
    return out


def _current_group_for_request(request):
    try:
        return request.user.supervised_group
    except Exception:
        return None


def _aware_active_datetime(request):
    active_now = get_active_datetime(request)
    if timezone.is_naive(active_now):
        active_now = timezone.make_aware(active_now, timezone.get_current_timezone())
    return active_now


def _route_cache_for_day(tech, active_day):
    """Refresh one technician-day route geometry after dispatch.

    Live map/report endpoints are cache-first to avoid billing Google on every
    refresh. Dispatch changes a route immediately, so we refresh only the
    affected technician-day here. If Google is disabled or the cap is reached,
    the function safely returns a fallback source and the schedule still exists.
    """
    schedules = list(
        Schedule.objects
        .filter(technician=tech, start_time__date=active_day)
        .select_related("task__unit")
        .order_by("sequence_order", "start_time")
    )
    stops = []
    for s in schedules:
        u = s.task.unit
        if u and u.latitude is not None and u.longitude is not None:
            stops.append({"lat": float(u.latitude), "lng": float(u.longitude)})
    if not stops:
        return {"source": None, "points": []}
    if tech.current_latitude is not None and tech.current_longitude is not None:
        origin = {"lat": float(tech.current_latitude), "lng": float(tech.current_longitude)}
    else:
        origin = stops[0]
    try:
        return build_route_geometry(origin, stops, allow_google_call=True)
    except Exception as exc:
        return {"source": "ERROR", "error": str(exc), "points": []}


def _insert_dispatch_schedule(*, winner, task, priority, duration_min, active_now):
    """Create a same-day dispatch schedule visible on live map/reports.

    AA is inserted as the next possible job from the current roll clock.
    If the technician is already on site, it starts after that active visit.
    Future jobs are pushed forward. Normal B callbacks are appended after the
    current route, but never before the current roll clock.
    """
    active_day = timezone.localtime(active_now).date()
    day_start = timezone.make_aware(datetime.combine(active_day, time(9, 0)), timezone.get_current_timezone())
    base_start = max(active_now, day_start)

    existing = list(
        Schedule.objects
        .filter(technician=winner, start_time__date=active_day)
        .select_related("task")
        .order_by("sequence_order", "start_time")
    )

    if priority == CallbackPriority.AA:
        current = next((s for s in existing if s.start_time <= active_now < s.end_time), None)
        dispatch_start = max(current.end_time if current else base_start, day_start)
        past_count = sum(1 for s in existing if s.end_time <= dispatch_start)
        seq = past_count + 1
        dispatch_end = dispatch_start + timedelta(minutes=duration_min)

        # Push jobs that have not started after the insertion point. Keep their
        # original durations and add a small buffer after the emergency visit.
        cursor = dispatch_end + timedelta(minutes=5)
        for s in existing:
            if s.end_time <= dispatch_start:
                continue
            if s is current:
                continue
            original_duration = s.end_time - s.start_time
            s.sequence_order = s.sequence_order + 1 if s.sequence_order >= seq else s.sequence_order
            if s.start_time >= dispatch_start:
                s.start_time = cursor
                s.end_time = cursor + original_duration
                cursor = s.end_time + timedelta(minutes=5)
            s.save(update_fields=["sequence_order", "start_time", "end_time"])
    else:
        if existing:
            last = max(existing, key=lambda s: s.end_time)
            dispatch_start = max(last.end_time + timedelta(minutes=5), base_start)
            seq = max(s.sequence_order for s in existing) + 1
        else:
            dispatch_start = base_start
            seq = 1
        dispatch_end = dispatch_start + timedelta(minutes=duration_min)

    return Schedule.objects.create(
        task=task,
        technician=winner,
        start_time=dispatch_start,
        end_time=dispatch_end,
        sequence_order=seq,
        source="MANUAL",
        is_manual_override=True,
        notes="DISPATCH CALLBACK",
    )



class RepairDispatchUnitsView(APIView):
    """Return existing active units that a supervisor can use as dispatch targets.

    This prevents manual latitude/longitude entry in the Flutter dashboard. The
    supervisor selects a real portfolio unit; dispatch then uses that unit's
    stored coordinates.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        group = getattr(request.user, "supervised_group", None)

        units = Unit.objects.filter(is_active=True)

        # Prefer units already in this supervisor's operational scope. This is
        # inferred from schedules/tasks rather than hard-coded region names.
        if group is not None:
            scheduled_unit_ids = Schedule.objects.filter(
                technician__group=group,
                task__unit__isnull=False,
            ).values_list("task__unit_id", flat=True)
            task_unit_ids = Task.objects.filter(
                assigned_group=group,
                unit__isnull=False,
            ).values_list("unit_id", flat=True)
            scoped_ids = set(scheduled_unit_ids) | set(task_unit_ids)
            if scoped_ids:
                units = units.filter(id__in=scoped_ids)

        if q:
            units = units.filter(
                Q(unit_name__icontains=q)
                | Q(unit_code__icontains=q)
                | Q(address__icontains=q)
                | Q(city__icontains=q)
            )

        units = units.order_by("unit_name")[:500]

        unit_ids = [u.id for u in units]
        backlog_counts = {
            row["unit_id"]: row["count"]
            for row in Task.objects.filter(
                unit_id__in=unit_ids,
                is_active=True,
                is_unassigned=True,
                task_type__operation_type=OperationType.CALLBACK,
            ).values("unit_id").annotate(count=Count("id"))
        }
        callback_counts = {
            row["unit_id"]: row["count"]
            for row in Task.objects.filter(
                unit_id__in=unit_ids,
                is_active=True,
                task_type__operation_type=OperationType.CALLBACK,
            ).values("unit_id").annotate(count=Count("id"))
        }

        return Response({
            "units": [
                {
                    "id": u.id,
                    "name": u.unit_name,
                    "code": u.unit_code,
                    "unit_type": u.unit_type,
                    "address": u.address or "",
                    "city": u.city or "",
                    "latitude": float(u.latitude),
                    "longitude": float(u.longitude),
                    "callback_count": callback_counts.get(u.id, 0),
                    "unassigned_callback_count": backlog_counts.get(u.id, 0),
                }
                for u in units
                if u.latitude is not None and u.longitude is not None
            ]
        })

class RepairDispatchView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        # Prefer dispatching to an existing unit selected by the supervisor.
        # Manual lat/lng is kept only as a backwards-compatible fallback.
        selected_unit = None
        unit_id = request.data.get("unit_id")
        if unit_id:
            try:
                selected_unit = Unit.objects.get(id=int(unit_id), is_active=True)
                lat = float(selected_unit.latitude)
                lng = float(selected_unit.longitude)
            except (TypeError, ValueError, Unit.DoesNotExist):
                return Response({"error": "Selected unit was not found or has no coordinates."}, status=400)
        else:
            try:
                lat = float(request.data.get("latitude"))
                lng = float(request.data.get("longitude"))
            except (TypeError, ValueError):
                return Response({"error": "Select an existing unit for dispatch."}, status=400)

        fault = request.data.get("fault_type") or "Elevator Fault"
        prof = FAULT_TYPES.get(fault, FAULT_TYPES["Elevator Fault"])

        active_now = _aware_active_datetime(request)
        active_day = timezone.localtime(active_now).date()
        supervisor_group = _current_group_for_request(request)

        # eligible: callback technicians from the logged-in supervisor's group.
        # Previously this searched every callback group; a Yusuf dispatch could
        # be assigned to Can Doğan's technician, so Yusuf's live map/reports did
        # not show it.
        eligible_qs = Technician.objects.filter(
            is_available=True,
            is_active_employee=True,
            current_latitude__isnull=False,
            tech_role=TechnicianRole.CALLBACK,
        ).select_related("user", "group")
        if supervisor_group is not None:
            eligible_qs = eligible_qs.filter(group=supervisor_group)
        eligible = list(eligible_qs)
        if not eligible:
            return Response({"error": f"No active callback technician for {fault} in this supervisor group."}, status=400)

        # cheapest-insertion: who grows least when this fault is added, based on
        # the selected operating day, not old schedules from other dates.
        fault_stop = (lat, lng)
        scoreboard = []
        best = None
        for t in eligible:
            depot = _depot(t)
            cur = _tech_stops(t, active_day=active_day)
            cur_km = _route_km(depot, cur)
            new_km = _route_km(depot, cur + [fault_stop])
            added = max(new_km - cur_km, 0.0)
            scoreboard.append((t, added, len(cur)))
            if best is None or added < best[1]:
                best = (t, added, len(cur))

        winner = best[0]

        # planning period + task type + unit + task
        today = active_day
        period = (PlanningPeriod.objects.filter(start_date__lte=today, end_date__gte=today, is_active=True).first()
                  or PlanningPeriod.objects.filter(is_active=True).order_by("-start_date").first())
        if not period:
            return Response({"error": "No active PlanningPeriod."}, status=400)

        ttype, _ = TaskType.objects.get_or_create(
            code=f"REP-{prof['specialty']}",
            defaults={"name": f"Repair ({prof['specialty']})",
                      "operation_type": OperationType.CALLBACK,
                      "required_specialty": prof["specialty"],
                      "required_technician_role": TechnicianRole.CALLBACK,
                      "base_duration_min": prof["dur"], "is_active": True})

        if selected_unit is not None:
            unit = selected_unit
        else:
            unit = Unit.objects.create(
                unit_code=f"FAULT-{int(timezone.now().timestamp())}",
                unit_name=f"{fault} ({lat:.4f},{lng:.4f})", unit_type=prof["unit"],
                address=f"({lat:.4f},{lng:.4f})", city="Istanbul",
                latitude=lat, longitude=lng, is_active=True)

        task = Task.objects.create(
            task_no=f"REP-{int(timezone.now().timestamp())}",
            unit=unit, task_type=ttype, planning_period=period,
            created_by=(request.user if request.user.is_authenticated else winner.group.supervisor),
            assigned_group=winner.group, description=(request.data.get("description") or f"{fault} dispatched to existing unit"),
            status=TaskStatus.ASSIGNED, priority=prof["pr"],
            estimated_duration_min=prof["dur"],
            earliest_start=active_now,
            latest_finish=active_now + timedelta(minutes=(60 if prof["pr"] == CallbackPriority.AA else 240)),
            release_time=active_now,
            is_active=True)

        dispatch_schedule = _insert_dispatch_schedule(
            winner=winner,
            task=task,
            priority=prof["pr"],
            duration_min=int(prof["dur"]),
            active_now=active_now,
        )

        route_cache = _route_cache_for_day(winner, active_day)

        # Response shaped to match BOTH the standalone repair panel AND the
        # Flutter dashboard's DispatchResult.fromJson (task.unit.*, assigned_to.*).
        return Response({
            "fault_type": fault,
            "priority": prof["pr"],
            "assigned_to": {
                "id": winner.id, "name": winner.full_name,
                "username": winner.user.username if winner.user else None,
                "tech_role": winner.tech_role, "specialty": winner.specialty,
                "was_idle": best[2] == 0,
            },
            "schedule": {
                "id": dispatch_schedule.id,
                "date": active_day.isoformat(),
                "start_time": dispatch_schedule.start_time.isoformat(),
                "end_time": dispatch_schedule.end_time.isoformat(),
                "sequence_order": dispatch_schedule.sequence_order,
                "source": dispatch_schedule.source,
            },
            "route_cache": {
                "source": route_cache.get("source"),
                "cache_key": route_cache.get("cache_key"),
                "points": len(route_cache.get("points") or []),
                "error": route_cache.get("error"),
            },
            "task": {
                "id": task.id, "task_no": task.task_no, "priority": prof["pr"],
                "estimated_duration_min": prof["dur"],
                "unit": {"id": unit.id, "name": unit.unit_name, "code": unit.unit_code,
                         "latitude": float(unit.latitude),
                         "longitude": float(unit.longitude),
                         "address": unit.address or ""},
            },
            "reason": (
                f"Existing unit: {unit.unit_name}. "
                f"{len(scoreboard)} eligible callback technician(s). "
                f"{winner.full_name} had the smallest added travel "
                f"(+{round(best[1], 2)} km). "
                f"Scheduled for {active_day.isoformat()} at {timezone.localtime(dispatch_schedule.start_time).strftime('%H:%M')}. "
                + (" AA emergency placed first in the route." if prof["pr"] == CallbackPriority.AA else "")
            ),
            "scoreboard": [
                {"name": t.full_name, "role": t.tech_role, "specialty": t.specialty,
                 "current_stops": stops, "added_km": round(added, 2),
                 "km_from_dispatch": round(added, 2),
                 "winner": (t.id == winner.id)}
                for (t, added, stops) in sorted(scoreboard, key=lambda r: r[1])
            ],
        }, status=201)


class RepairPanelView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return HttpResponse(_PANEL_HTML, content_type="text/html")


class ClearRepairsView(APIView):
    """Delete all dispatched repairs (REP- tasks, their schedules, fault units).
    Called when the simulation is exited so each session starts at 0 dispatches."""
    permission_classes = [AllowAny]

    def post(self, request):
        from api.models import Schedule as _Sched
        repair_tasks = Task.objects.filter(task_no__startswith="REP-")
        n = repair_tasks.count()
        _Sched.objects.filter(task__in=repair_tasks).delete()
        repair_tasks.delete()
        Unit.objects.filter(unit_code__startswith="FAULT-").delete()
        return Response({"cleared": n})


_PANEL_HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Repair Dispatch</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html,body{margin:0;height:100%;font-family:system-ui,Segoe UI,Arial,sans-serif;background:#15151b;color:#eee;}
  #wrap{display:flex;height:100%;}
  #map{flex:1;}
  #side{width:380px;padding:18px;box-sizing:border-box;overflow:auto;}
  h2{margin:0 0 4px;} .sub{color:#9a9aa6;font-size:12px;margin-bottom:16px;}
  label{font-size:12px;color:#9a9aa6;display:block;margin:12px 0 4px;}
  select,input{width:100%;padding:10px;border-radius:8px;border:1px solid #333;background:#1e1e24;color:#eee;box-sizing:border-box;}
  button{width:100%;margin-top:16px;background:#E8C423;color:#000;border:0;border-radius:8px;padding:12px;font-weight:800;cursor:pointer;}
  .hint{font-size:11px;color:#7a7a85;margin-top:6px;}
  .winner{margin-top:18px;padding:14px;background:#13301f;border:1px solid #00d26a;border-radius:10px;}
  .winner b{color:#00d26a;}
  table{width:100%;border-collapse:collapse;margin-top:14px;font-size:12px;}
  th,td{text-align:left;padding:6px 4px;border-bottom:1px solid #26262e;}
  tr.win{background:#1d2a20;}
  .pill{font-size:10px;padding:2px 6px;border-radius:6px;background:#2a2a33;}
</style>
</head>
<body>
<div id="wrap">
  <div id="map"></div>
  <div id="side">
    <h2>Repair Dispatch</h2>
    <div class="sub">Click the map to set the fault location, pick a type, dispatch.</div>
    <label>Fault type</label>
    <select id="ftype">
      <option>Elevator Entrapment</option>
      <option>Elevator Fault</option>
      <option>Escalator Fault</option>
    </select>
    <label>Location (click map to set)</label>
    <input id="loc" readonly placeholder="no location yet"/>
    <div class="hint">Entrapment = AA priority (jumps to front of the chosen tech's route).</div>
    <button id="go">Dispatch repair</button>
    <div id="result"></div>
  </div>
</div>
<script>
const map = L.map('map').setView([41.075,29.01], 13);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom:19, attribution:'&copy; OpenStreetMap'}).addTo(map);
let faultMarker=null, lat=null, lng=null;
map.on('click', e=>{
  lat=e.latlng.lat; lng=e.latlng.lng;
  document.getElementById('loc').value = lat.toFixed(4)+', '+lng.toFixed(4);
  if(faultMarker) faultMarker.setLatLng(e.latlng);
  else faultMarker=L.marker(e.latlng).addTo(map);
});
document.getElementById('go').onclick=async ()=>{
  if(lat===null){ alert('Click the map to set the fault location first.'); return; }
  const ftype=document.getElementById('ftype').value;
  const res=document.getElementById('result');
  res.innerHTML='Dispatching...';
  try{
    const r=await fetch('/api/repair/dispatch/',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({fault_type:ftype, latitude:lat, longitude:lng})
    });
    const d=await r.json();
    if(!r.ok){ res.innerHTML='<div style="color:#ff6b6b">'+(d.error||'error')+'</div>'; return; }
    let html='<div class="winner">Assigned to <b>'+d.assigned_to.name+'</b>'
      +' <span class="pill">'+d.assigned_to.tech_role+' / '+d.assigned_to.specialty+'</span><br/>'
      +(d.assigned_to.was_idle?'was idle at HQ':'was already working')
      +' &middot; priority '+d.priority+'</div>';
    html+='<table><tr><th>Technician</th><th>Type</th><th>Stops</th><th>+km</th></tr>';
    d.scoreboard.forEach(s=>{
      html+='<tr class="'+(s.winner?'win':'')+'"><td>'+s.name+'</td><td>'+s.role[0]+'/'+s.specialty.slice(0,4)
        +'</td><td>'+s.current_stops+'</td><td>'+s.added_km+'</td></tr>';
    });
    html+='</table>';
    res.innerHTML=html;
    if(faultMarker) faultMarker.bindPopup('Assigned: '+d.assigned_to.name).openPopup();
  }catch(e){ res.innerHTML='<div style="color:#ff6b6b">'+e+'</div>'; }
};
</script>
</body>
</html>
"""
