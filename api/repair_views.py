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
from datetime import timedelta

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import (
    PlanningPeriod, Schedule, Task, TaskType, Technician, Unit,
    TaskStatus, OperationType, SpecialtyType, TechnicianRole, CallbackPriority,
    UnitType,
)
from api.services.maps.distance_service import haversine_distance_km

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


def _tech_stops(tech):
    out = []
    for s in (Schedule.objects.filter(technician=tech)
              .select_related("task__unit").order_by("sequence_order")):
        u = s.task.unit
        if u.latitude is not None and u.longitude is not None:
            out.append((float(u.latitude), float(u.longitude)))
    return out


class RepairDispatchView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        try:
            lat = float(request.data.get("latitude"))
            lng = float(request.data.get("longitude"))
        except (TypeError, ValueError):
            return Response({"error": "latitude/longitude required"}, status=400)

        fault = request.data.get("fault_type") or "Elevator Fault"
        prof = FAULT_TYPES.get(fault, FAULT_TYPES["Elevator Fault"])

        # eligible: callback technicians (cover both elevator & escalator)
        eligible = [
            t for t in Technician.objects.filter(
                is_available=True, is_active_employee=True,
                current_latitude__isnull=False,
            ).select_related("user", "group")
            if t.tech_role == TechnicianRole.CALLBACK
            # Callback techs cover both elevator & escalator, so role is enough.
        ]
        if not eligible:
            return Response({"error": f"No repair-capable technician for {fault}."}, status=400)

        # cheapest-insertion: who grows least when this fault is added
        fault_stop = (lat, lng)
        scoreboard = []
        best = None
        for t in eligible:
            depot = _depot(t)
            cur = _tech_stops(t)
            cur_km = _route_km(depot, cur)
            new_km = _route_km(depot, cur + [fault_stop])
            added = max(new_km - cur_km, 0.0)
            scoreboard.append((t, added, len(cur)))
            if best is None or added < best[1]:
                best = (t, added, len(cur))

        winner = best[0]

        # planning period + task type + unit + task
        today = timezone.now().date()
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

        unit = Unit.objects.create(
            unit_code=f"FAULT-{int(timezone.now().timestamp())}",
            unit_name=f"{fault} ({lat:.4f},{lng:.4f})", unit_type=prof["unit"],
            address=f"({lat:.4f},{lng:.4f})", city="Istanbul",
            latitude=lat, longitude=lng, is_active=True)

        task = Task.objects.create(
            task_no=f"REP-{int(timezone.now().timestamp())}",
            unit=unit, task_type=ttype, planning_period=period,
            created_by=(request.user if request.user.is_authenticated else winner.group.supervisor),
            assigned_group=winner.group, description=f"{fault} dispatched",
            status=TaskStatus.ASSIGNED, priority=prof["pr"],
            estimated_duration_min=prof["dur"], release_time=timezone.now(),
            is_active=True)

        # append to winner's schedule (AA goes first, else end)
        existing = list(Schedule.objects.filter(technician=winner).order_by("sequence_order"))
        if prof["pr"] == CallbackPriority.AA:
            seq = 1
            for i, s in enumerate(existing, start=2):
                s.sequence_order = i; s.save(update_fields=["sequence_order"])
        else:
            seq = (existing[-1].sequence_order + 1) if existing else 1
        start = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        Schedule.objects.create(
            task=task, technician=winner, start_time=start,
            end_time=start + timedelta(minutes=prof["dur"]),
            sequence_order=seq, source="DISPATCH")

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
            "task": {
                "id": task.id, "task_no": task.task_no, "priority": prof["pr"],
                "estimated_duration_min": prof["dur"],
                "unit": {"name": unit.unit_name,
                         "latitude": float(unit.latitude),
                         "longitude": float(unit.longitude)},
            },
            "reason": (
                f"{len(scoreboard)} eligible repair-capable technician(s). "
                f"{winner.full_name} had the smallest added travel "
                f"(+{round(best[1], 2)} km)."
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
