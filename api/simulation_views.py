"""
api/simulation_views.py
=============================================================================
Two endpoints for the moving-technician demo (no Google key, no CORS):

  GET /api/simulation/routes/  -> JSON: each routed technician's HQ + ordered
                                  stops with a reconstructed arrive/depart
                                  timeline (built from sequence_order +
                                  durations + haversine travel).

  GET /api/simulation/map/     -> a self-contained Leaflet page (OpenStreetMap
                                  tiles) that plays the day and animates the
                                  technicians along their Gurobi routes.

Wire up in api/urls.py:
    from .simulation_views import SimulationRoutesView, SimulationMapView
    path("simulation/routes/", SimulationRoutesView.as_view()),
    path("simulation/map/",    SimulationMapView.as_view()),

Then open:  http://localhost:8000/api/simulation/map/
=============================================================================
"""
from django.http import HttpResponse
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Technician
from api.services.maps.distance_service import haversine_distance_km

DAY_START_MIN = 9 * 60        # 09:00
DAY_END_CAP_MIN = 18 * 60     # 18:00 — maintenance stops past this are dropped
ROAD_FACTOR = 1.35
SPEED_KMH = 30.0
HQ_LAT, HQ_LNG = 41.07013, 29.02283


def _travel_min(lat1, lng1, lat2, lng2):
    km = haversine_distance_km(lat1, lng1, lat2, lng2) * ROAD_FACTOR
    return (km / SPEED_KMH) * 60.0


class SimulationRoutesView(APIView):
    """Reconstructed per-technician timeline from the written Schedule rows."""
    permission_classes = [AllowAny]

    def get(self, request):
        techs = (
            Technician.objects
            .filter(schedules__isnull=False, current_latitude__isnull=False)
            .distinct()
        )

        out = []
        day_end = DAY_START_MIN

        for t in techs:
            scheds = list(
                t.schedules.select_related("task__unit").order_by("sequence_order", "start_time")
            )
            if not scheds:
                continue

            hq_lat, hq_lng = float(t.current_latitude), float(t.current_longitude)
            clock = DAY_START_MIN
            prev_lat, prev_lng = hq_lat, hq_lng
            stops = []

            for s in scheds:
                u = s.task.unit
                if u.latitude is None or u.longitude is None:
                    continue
                ulat, ulng = float(u.latitude), float(u.longitude)
                arrive = clock + _travel_min(prev_lat, prev_lng, ulat, ulng)
                dur = s.task.estimated_duration_min or 45
                depart = arrive + dur
                stops.append({
                    "seq": s.sequence_order,
                    "name": u.unit_name,
                    "lat": ulat, "lng": ulng,
                    "arrive_min": round(arrive, 1),
                    "depart_min": round(depart, 1),
                })
                clock = depart
                prev_lat, prev_lng = ulat, ulng

            if not stops:
                continue
            day_end = max(day_end, clock)
            out.append({
                "id": t.id,
                "name": t.full_name,
                "specialty": t.specialty,
                "hq": {"lat": hq_lat, "lng": hq_lng},
                "stops": stops,
            })

        return Response({
            "day_start_min": DAY_START_MIN,
            "day_end_min": round(day_end, 1),
            "hq": {"lat": HQ_LAT, "lng": HQ_LNG},
            "technician_count": len(out),
            "technicians": out,
        })


DEMO_GROUP_NAME = "Demo Group"


class SimulationDemoRoutesView(APIView):
    """
    Supervisor-scoped timeline for the dashboard's Live Map animation.
    Returns the logged-in supervisor's group technicians: routed ones with a
    reconstructed arrive/depart timeline, idle ones with empty stops so they
    appear parked at HQ.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        group = getattr(request.user, "supervised_group", None)
        if group is None:
            return Response(
                {"error": "This account is not a supervisor of any group."},
                status=403,
            )

        techs = (
            Technician.objects
            .filter(group=group,
                    is_active_employee=True,
                    current_latitude__isnull=False)
            .order_by("full_name")
        )

        out = []
        day_end = DAY_START_MIN

        for t in techs:
            scheds = list(
                t.schedules.select_related("task__unit").order_by("sequence_order", "start_time")
            )
            hq_lat, hq_lng = float(t.current_latitude), float(t.current_longitude)
            clock = DAY_START_MIN
            prev_lat, prev_lng = hq_lat, hq_lng
            stops = []

            for s in scheds:
                u = s.task.unit
                if u.latitude is None or u.longitude is None:
                    continue
                ulat, ulng = float(u.latitude), float(u.longitude)
                arrive = clock + _travel_min(prev_lat, prev_lng, ulat, ulng)
                dur = s.task.estimated_duration_min or 45
                depart = arrive + dur
                is_repair = (s.task.task_type.operation_type == "CALLBACK") if s.task.task_type else False
                # Realistic shift: stop scheduling maintenance past 18:00.
                # Repairs (emergencies) always go through regardless of the cap.
                if not is_repair and arrive > DAY_END_CAP_MIN:
                    continue
                stops.append({
                    "seq": s.sequence_order,
                    "name": u.unit_name,
                    "lat": ulat, "lng": ulng,
                    "arrive_min": round(arrive, 1),
                    "depart_min": round(depart, 1),
                    "is_repair": is_repair,
                    "priority": s.task.priority or "NORMAL",
                })
                clock = depart
                prev_lat, prev_lng = ulat, ulng

            day_end = max(day_end, clock)
            out.append({
                "id": t.id,
                "name": t.full_name,
                "tech_role": t.tech_role,
                "specialty": t.specialty,
                "hq": {"lat": hq_lat, "lng": hq_lng},
                "stops": stops,
            })

        return Response({
            "day_start_min": DAY_START_MIN,
            "day_end_min": round(day_end, 1),
            "group": group.name,
            "technician_count": len(out),
            "technicians": out,
        })


class SimulationMapView(APIView):
    """Serves the standalone Leaflet animation page (same-origin: no CORS)."""
    permission_classes = [AllowAny]

    def get(self, request):
        return HttpResponse(_MAP_HTML, content_type="text/html")


_MAP_HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Technician Movement - One Day</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html,body{margin:0;height:100%;font-family:system-ui,Segoe UI,Arial,sans-serif;}
  #map{position:absolute;top:0;bottom:0;left:0;right:340px;}
  #panel{position:absolute;top:0;right:0;width:340px;bottom:0;background:#15151b;color:#eee;
         padding:16px;box-sizing:border-box;overflow:auto;}
  h2{margin:0 0 4px;font-size:18px;}
  .sub{color:#9a9aa6;font-size:12px;margin-bottom:14px;}
  .clock{font-size:34px;font-weight:800;letter-spacing:1px;margin:6px 0;}
  .row{display:flex;gap:8px;align-items:center;margin:10px 0;}
  button{background:#E8C423;color:#000;border:0;border-radius:8px;padding:10px 14px;
         font-weight:700;cursor:pointer;}
  button.sec{background:#2a2a33;color:#eee;}
  input[type=range]{width:100%;}
  .legend{font-size:12px;color:#cfcfd6;margin-top:8px;line-height:1.6;}
  .dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle;}
  .tlist{margin-top:14px;font-size:12px;}
  .tlist div{padding:3px 0;border-bottom:1px solid #26262e;}
  .badge{float:right;color:#9a9aa6;}
</style>
</head>
<body>
<div id="map"></div>
<div id="panel">
  <h2>Technician Movement</h2>
  <div class="sub">Gurobi-optimized routes, one compressed day</div>
  <div class="clock" id="clock">09:00</div>
  <div class="row">
    <button id="play">Play</button>
    <button id="reset" class="sec">Reset</button>
  </div>
  <div class="row">
    <span style="font-size:12px;color:#9a9aa6;">Speed</span>
    <input type="range" id="speed" min="2" max="60" value="12"/>
    <span id="speedval" style="font-size:12px;width:70px;">12 min/s</span>
  </div>
  <div class="legend">
    <span class="dot" style="background:#E8C423;"></span>HQ (depot)<br/>
    <span class="dot" style="background:#3da5ff;"></span>Traveling<br/>
    <span class="dot" style="background:#00d26a;"></span>Servicing a building
  </div>
  <div class="tlist" id="tlist"></div>
</div>

<script>
const ROUTES_URL = "/api/simulation/routes/";
let DATA=null, markers=[], dayStart=540, dayEnd=1080;
let simMin=540, playing=false, last=null, speed=12;

const map = L.map('map');
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom:19, attribution:'&copy; OpenStreetMap'}).addTo(map);

function fmt(t){const h=Math.floor(t/60),m=Math.floor(t%60);
  return String(h).padStart(2,'0')+':'+String(m).padStart(2,'0');}
function clamp(x,a,b){return Math.max(a,Math.min(b,x));}
function lerp(a,b,f){return [a.lat+(b.lat-a.lat)*f, a.lng+(b.lng-a.lng)*f];}

// position + state of one technician at sim-minute t
function posAt(tech,t){
  const hq=tech.hq, s=tech.stops;
  if(s.length===0) return {ll:[hq.lat,hq.lng],state:'idle'};
  if(t<=s[0].arrive_min){
    const f=clamp((t-dayStart)/Math.max(1,(s[0].arrive_min-dayStart)),0,1);
    return {ll:lerp(hq,s[0],f),state:'travel'};
  }
  for(let i=0;i<s.length;i++){
    if(t<=s[i].depart_min){
      if(t<=s[i].arrive_min){
        const p=s[i-1];
        const f=clamp((t-p.depart_min)/Math.max(1,(s[i].arrive_min-p.depart_min)),0,1);
        return {ll:lerp(p,s[i],f),state:'travel'};
      }
      return {ll:[s[i].lat,s[i].lng],state:'service'};
    }
  }
  const L0=s[s.length-1];
  return {ll:[L0.lat,L0.lng],state:'done'};
}

function build(){
  // HQ marker
  L.circleMarker([DATA.hq.lat,DATA.hq.lng],
    {radius:9,color:'#E8C423',fillColor:'#E8C423',fillOpacity:1,weight:2})
    .addTo(map).bindTooltip('HQ / Depot');
  const bounds=[[DATA.hq.lat,DATA.hq.lng]];
  DATA.technicians.forEach(tech=>{
    // route line HQ -> stops
    const line=[[tech.hq.lat,tech.hq.lng]];
    tech.stops.forEach(s=>{line.push([s.lat,s.lng]); bounds.push([s.lat,s.lng]);});
    L.polyline(line,{color:'#3da5ff',weight:2,opacity:0.35}).addTo(map);
    // moving marker
    const m=L.circleMarker([tech.hq.lat,tech.hq.lng],
      {radius:6,color:'#fff',weight:1,fillColor:'#3da5ff',fillOpacity:1})
      .addTo(map).bindTooltip(tech.name,{direction:'top'});
    markers.push({tech,m});
  });
  map.fitBounds(bounds,{padding:[40,40]});
  // side list
  const tl=document.getElementById('tlist');
  tl.innerHTML='<b>Routed technicians: '+DATA.technicians.length+'</b>';
  DATA.technicians.forEach(t=>{
    const d=document.createElement('div');
    d.innerHTML=t.name+'<span class="badge">'+t.stops.length+' stop'+(t.stops.length===1?'':'s')+'</span>';
    tl.appendChild(d);
  });
}

function tick(ts){
  if(playing){
    if(last!==null){ simMin += ((ts-last)/1000)*speed; }
    last=ts;
    if(simMin>=dayEnd){ simMin=dayEnd; playing=false; document.getElementById('play').textContent='Play'; }
  } else { last=ts; }
  document.getElementById('clock').textContent=fmt(simMin);
  const colors={travel:'#3da5ff',service:'#00d26a',done:'#7a7a85',idle:'#7a7a85'};
  markers.forEach(o=>{
    const p=posAt(o.tech,simMin);
    o.m.setLatLng(p.ll);
    o.m.setStyle({fillColor:colors[p.state]});
  });
  requestAnimationFrame(tick);
}

document.getElementById('play').onclick=()=>{
  playing=!playing;
  document.getElementById('play').textContent=playing?'Pause':'Play';
};
document.getElementById('reset').onclick=()=>{ simMin=dayStart; playing=false;
  document.getElementById('play').textContent='Play'; };
document.getElementById('speed').oninput=(e)=>{ speed=+e.target.value;
  document.getElementById('speedval').textContent=speed+' min/s'; };

fetch(ROUTES_URL).then(r=>r.json()).then(d=>{
  DATA=d; dayStart=d.day_start_min; dayEnd=d.day_end_min; simMin=dayStart;
  if(!d.technicians.length){
    document.getElementById('tlist').innerHTML='<b>No routes found.</b> Run solve_emre_demo first.';
  }
  build();
  requestAnimationFrame(tick);
}).catch(e=>{
  document.getElementById('tlist').innerHTML='<b style="color:#ff6b6b">Could not load routes:</b><br/>'+e;
});
</script>
</body>
</html>
"""
