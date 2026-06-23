"""
api/repair_views.py
=============================================================================
Real-time callback dispatch.

Supervisor workflow:
  1. Search/select an existing Unit instead of manually typing coordinates.
  2. Preview the nearest available callback technicians for that unit.
  3. Dispatch an AA or B callback.

Cost control for Google Maps:
  - first filter candidates locally by region + haversine distance
  - call Google Routes only for the top few candidates
  - if Google is disabled or fails, safely fall back to straight-line estimate
=============================================================================
"""
from datetime import timedelta
from math import radians, sin, cos, sqrt, atan2

from django.conf import settings
from django.db import transaction
from django.db.models import Q
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
from api.services.optimization.routing import optimal_open_route

REGION_THRESHOLD = 29.02
ROAD_FACTOR = 1.35
SPEED_KMH = 30.0
GOOGLE_CANDIDATE_CAP = 8
SEARCH_LIMIT = 12


def _active_datetime(request=None):
    try:
        from api.active_day import get_active_datetime
        return get_active_datetime(request)
    except Exception:
        return timezone.localtime()


def _haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    lat1, lng1, lat2, lng2 = map(radians, [float(lat1), float(lng1), float(lat2), float(lng2)])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return r * c


def _region(lng):
    return "ASIA" if float(lng) >= REGION_THRESHOLD else "EUROPE"


def _duration_text_to_seconds(value):
    if value is None:
        return None
    return int(str(value).replace("s", ""))


def _fallback_road_estimate(lat1, lng1, lat2, lng2):
    km = _haversine_km(lat1, lng1, lat2, lng2) * ROAD_FACTOR
    seconds = int((km / SPEED_KMH) * 3600)
    return {
        "distance_km": round(km, 2),
        "duration_seconds": max(seconds, 60),
        "duration_min": max(round(seconds / 60), 1),
        "source": "STRAIGHT_LINE_FALLBACK",
    }


def _google_or_fallback_estimate(origin_lat, origin_lng, dest_lat, dest_lng):
    """Use Google Routes for a single origin/destination if enabled; otherwise fallback.

    This function is called only after local candidate prefiltering, so we do not
    spend API calls on every callback technician in the city.
    """
    if not getattr(settings, "GOOGLE_MAPS_ENABLED", False):
        out = _fallback_road_estimate(origin_lat, origin_lng, dest_lat, dest_lng)
        out["source"] = "STRAIGHT_LINE_ESTIMATE"
        return out

    try:
        from api.services.maps.google_maps import get_route_matrix
        result = get_route_matrix(
            origins=[(origin_lat, origin_lng)],
            destinations=[(dest_lat, dest_lng)],
        )
        if not result:
            raise ValueError("Google Routes returned empty result")
        row = result[0]
        if row.get("status") and row["status"].get("code"):
            raise ValueError(f"Google Routes status: {row['status']}")
        meters = row.get("distanceMeters")
        seconds = _duration_text_to_seconds(row.get("duration"))
        if meters is None or seconds is None:
            raise ValueError(f"Missing distance/duration in Google result: {row}")
        return {
            "distance_km": round(float(meters) / 1000.0, 2),
            "duration_seconds": int(seconds),
            "duration_min": max(round(int(seconds) / 60), 1),
            "source": "GOOGLE_ROADS",
        }
    except Exception as exc:
        out = _fallback_road_estimate(origin_lat, origin_lng, dest_lat, dest_lng)
        out["source"] = "STRAIGHT_LINE_FALLBACK"
        out["fallback_reason"] = str(exc)[:160]
        return out


def _profile_from(priority, unit_type):
    priority = (priority or "B").upper()
    if priority in ("AA", "ENTRAPMENT"):
        return {
            "fault_type": "Elevator Entrapment",
            "priority": CallbackPriority.AA,
            "specialty": SpecialtyType.ELEVATOR,
            "duration": 60,
        }
    # Normal callbacks are B with 4-hour SLA; service duration stays 60 minutes.
    specialty = SpecialtyType.ESCALATOR if unit_type == UnitType.ESCALATOR else SpecialtyType.ELEVATOR
    return {
        "fault_type": "Escalator Fault" if specialty == SpecialtyType.ESCALATOR else "Elevator Fault",
        "priority": CallbackPriority.B,
        "specialty": specialty,
        "duration": 60,
    }


def _candidate_query_for_unit(unit):
    unit_region = _region(unit.longitude)
    out = []
    for t in (Technician.objects
              .filter(
                  tech_role=TechnicianRole.CALLBACK,
                  is_active_employee=True,
                  is_available=True,
                  current_latitude__isnull=False,
                  current_longitude__isnull=False,
              )
              .select_related("user", "group")):
        if _region(t.current_longitude) != unit_region:
            continue
        km = _haversine_km(t.current_latitude, t.current_longitude, unit.latitude, unit.longitude)
        out.append((t, km))
    return sorted(out, key=lambda x: x[1])


def _current_day_schedules(tech, active_dt):
    return list(
        Schedule.objects.filter(
            technician=tech,
            start_time__date=active_dt.date(),
        ).select_related("task", "task__unit").order_by("sequence_order", "start_time")
    )


def _remaining_same_day_tasks(tech, active_dt):
    return [s.task for s in _current_day_schedules(tech, active_dt) if not s.end_time or s.end_time > active_dt]


def _rank_candidates(unit, active_dt, limit=GOOGLE_CANDIDATE_CAP):
    nearest = _candidate_query_for_unit(unit)[:limit]
    ranked = []
    for tech, straight_km in nearest:
        estimate = _google_or_fallback_estimate(
            tech.current_latitude, tech.current_longitude,
            unit.latitude, unit.longitude,
        )
        current_count = len(_remaining_same_day_tasks(tech, active_dt))
        ranked.append({
            "technician": tech,
            "name": tech.full_name,
            "username": tech.user.username if tech.user else None,
            "group": tech.group.name if tech.group else None,
            "tech_role": tech.tech_role,
            "specialty": tech.specialty,
            "current_stops": current_count,
            "straight_km": round(straight_km, 2),
            "distance_km": estimate["distance_km"],
            "duration_seconds": estimate["duration_seconds"],
            "duration_min": estimate["duration_min"],
            "source": estimate["source"],
            "fallback_reason": estimate.get("fallback_reason"),
        })
    ranked.sort(key=lambda r: (r["duration_seconds"], r["current_stops"]))
    for i, r in enumerate(ranked):
        r["winner"] = (i == 0)
    return ranked


def _task_stops(tasks):
    return [{
        "id": t.id,
        "lat": float(t.unit.latitude),
        "lng": float(t.unit.longitude),
        "is_aa": (t.priority or "").upper() == CallbackPriority.AA,
        "payload": t,
    } for t in tasks]


def _rewrite_remaining_route(tech, tasks, active_dt):
    """Preserve completed history; rewrite only same-day remaining route."""
    day = active_dt.date()
    Schedule.objects.filter(
        technician=tech,
        start_time__date=day,
        end_time__gt=active_dt,
    ).delete()

    depot = (float(tech.current_latitude), float(tech.current_longitude))
    ordered, _km = optimal_open_route(depot, _task_stops(tasks))

    start = active_dt.replace(second=0, microsecond=0)
    for seq, stop in enumerate(ordered, start=1):
        task = stop["payload"]
        end = start + timedelta(minutes=task.estimated_duration_min or 60)
        Schedule.objects.create(
            task=task,
            technician=tech,
            start_time=start,
            end_time=end,
            sequence_order=seq,
            source="DISPATCH",
        )
        start = end + timedelta(minutes=15)
    return ordered


def _unit_json(unit):
    return {
        "id": unit.id,
        "unit_name": unit.unit_name,
        "unit_code": unit.unit_code,
        "unit_type": unit.unit_type,
        "address": unit.address,
        "district": unit.district,
        "latitude": float(unit.latitude),
        "longitude": float(unit.longitude),
        "region": _region(unit.longitude),
    }


def _candidate_json(r):
    return {
        "id": r["technician"].id,
        "name": r["name"],
        "username": r["username"],
        "group": r["group"],
        "tech_role": r["tech_role"],
        "specialty": r["specialty"],
        "current_stops": r["current_stops"],
        "straight_km": r["straight_km"],
        "distance_km": r["distance_km"],
        "duration_min": r["duration_min"],
        "source": r["source"],
        "winner": r["winner"],
    }


class DispatchUnitSearchView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        qs = Unit.objects.filter(is_active=True, latitude__isnull=False, longitude__isnull=False)
        if q:
            qs = qs.filter(
                Q(unit_name__icontains=q) |
                Q(unit_code__icontains=q) |
                Q(address__icontains=q) |
                Q(district__icontains=q)
            )
        qs = qs.order_by("unit_name", "unit_code")[:SEARCH_LIMIT]
        return Response({"units": [_unit_json(u) for u in qs]})


class DispatchPreviewView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        unit_id = request.data.get("unit_id")
        if not unit_id:
            return Response({"error": "unit_id is required"}, status=400)
        unit = Unit.objects.filter(id=unit_id, is_active=True).first()
        if not unit:
            return Response({"error": "Selected unit not found"}, status=404)

        priority = request.data.get("priority") or "B"
        profile = _profile_from(priority, unit.unit_type)
        active_dt = _active_datetime(request)
        ranked = _rank_candidates(unit, active_dt)
        if not ranked:
            return Response({
                "error": f"No available callback technicians in {_region(unit.longitude)} region",
                "unit": _unit_json(unit),
            }, status=400)

        google_used = any(r["source"] == "GOOGLE_ROADS" for r in ranked)
        return Response({
            "unit": _unit_json(unit),
            "priority": profile["priority"],
            "fault_type": profile["fault_type"],
            "active_time": active_dt.isoformat(),
            "candidate_count": len(ranked),
            "source_note": (
                "Google road travel time used for shortlisted candidates."
                if google_used else
                "Straight-line fallback/estimate used. Enable GOOGLE_MAPS_ENABLED for road travel time."
            ),
            "candidates": [_candidate_json(r) for r in ranked],
        })


class RepairDispatchView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        unit_id = request.data.get("unit_id")
        unit = None
        if unit_id:
            unit = Unit.objects.filter(id=unit_id, is_active=True).first()
            if not unit:
                return Response({"error": "Selected unit not found"}, status=404)
        else:
            # Backward-compatible manual coordinate fallback.
            try:
                lat = float(request.data.get("latitude"))
                lng = float(request.data.get("longitude"))
            except (TypeError, ValueError):
                return Response({"error": "unit_id or latitude/longitude required"}, status=400)
            unit = Unit.objects.create(
                unit_code=f"FAULT-{int(timezone.now().timestamp())}",
                unit_name=f"Manual dispatch ({lat:.4f},{lng:.4f})",
                unit_type=UnitType.ELEVATOR,
                address=f"({lat:.4f}, {lng:.4f})",
                city="Istanbul",
                latitude=lat,
                longitude=lng,
                is_active=True,
            )

        priority = request.data.get("priority") or "B"
        profile = _profile_from(priority, unit.unit_type)
        description = request.data.get("description") or ""
        active_dt = _active_datetime(request)

        ranked = _rank_candidates(unit, active_dt)
        if not ranked:
            return Response({"error": f"No available callback technician in {_region(unit.longitude)} region."}, status=400)
        winner_row = ranked[0]
        winner = winner_row["technician"]

        period = (
            PlanningPeriod.objects.filter(start_date__lte=active_dt.date(), end_date__gte=active_dt.date(), is_active=True).first()
            or PlanningPeriod.objects.filter(is_active=True).order_by("-start_date").first()
        )
        if not period:
            return Response({"error": "No active PlanningPeriod."}, status=400)

        ttype, _ = TaskType.objects.get_or_create(
            code=f"DISP-CB-{profile['specialty']}",
            defaults={
                "name": f"Dispatch Callback ({profile['specialty']})",
                "operation_type": OperationType.CALLBACK,
                "required_specialty": profile["specialty"],
                "required_technician_role": TechnicianRole.CALLBACK,
                "base_duration_min": profile["duration"],
                "sla_target_min": 60 if profile["priority"] == CallbackPriority.AA else 240,
                "is_active": True,
            },
        )

        task = Task.objects.create(
            task_no=f"REP-{int(timezone.now().timestamp())}",
            unit=unit,
            task_type=ttype,
            planning_period=period,
            created_by=(request.user if request.user.is_authenticated else winner.group.supervisor),
            assigned_group=winner.group,
            description=description or f"{profile['fault_type']} dispatched to existing unit",
            status=TaskStatus.ASSIGNED,
            priority=profile["priority"],
            estimated_duration_min=profile["duration"],
            release_time=active_dt,
            is_active=True,
        )

        remaining = _remaining_same_day_tasks(winner, active_dt)
        _rewrite_remaining_route(winner, remaining + [task], active_dt)

        scoreboard = [_candidate_json(r) for r in ranked]
        return Response({
            "fault_type": profile["fault_type"],
            "priority": profile["priority"],
            "assigned_to": {
                "id": winner.id,
                "name": winner.full_name,
                "username": winner.user.username if winner.user else None,
                "tech_role": winner.tech_role,
                "specialty": winner.specialty,
                "group": winner.group.name if winner.group else None,
            },
            "task": {
                "id": task.id,
                "task_no": task.task_no,
                "priority": task.priority,
                "estimated_duration_min": task.estimated_duration_min,
                "unit": {
                    "id": unit.id,
                    "name": unit.unit_name,
                    "unit_code": unit.unit_code,
                    "latitude": float(unit.latitude),
                    "longitude": float(unit.longitude),
                },
            },
            "reason": (
                f"{unit.unit_name} selected from existing units. "
                f"{len(ranked)} shortlisted callback technician(s) in {_region(unit.longitude)}. "
                f"{winner.full_name} had the fastest/lowest-cost travel estimate "
                f"({winner_row['duration_min']} min, {winner_row['distance_km']} km, {winner_row['source']}). "
                f"Remaining same-day route was rewritten from the operating clock time."
            ),
            "scoreboard": scoreboard,
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
