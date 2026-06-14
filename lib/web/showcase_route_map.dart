// showcase_route_map.dart
// =============================================================================
// Animated "showcase" route map for the Supervisor Dashboard.
//
// Calls GET /api/demo/showcase-routes/ (returns a LIMITED number of technicians
// for one day, each with a REAL road polyline when Google is on, else straight
// legs). Draws each route and animates a technician pin moving along it.
//
// Matches the existing dashboard: flutter_map ^6.1.0, latlong2, http, token auth.
//
// Add it as a tab in _tabsFor():
//   _TabDef(const _NavItem(Icons.route_outlined, Icons.route, 'Showcase'),
//       (st) => ShowcaseRouteMapView(baseUrl: kBaseUrl, token: kSupervisorToken)),
// =============================================================================
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';

const List<Color> _kRouteColors = [
  Color(0xFF00838F), // teal
  Color(0xFFD32F2F), // red
  Color(0xFF7B1FA2), // purple
  Color(0xFF558B2F), // lime-green
  Color(0xFF1976D2), // blue
  Color(0xFFC2185B), // pink
];
const Color _kAmber = Color(0xFFF9A825); // AA emergency

// --------------------------------------------------------------------------- //
// Models
// --------------------------------------------------------------------------- //
class ShowcaseStop {
  final int sequence;
  final String taskNo;
  final String taskType;
  final String unitName;
  final LatLng point;
  final bool isAA;
  final int durationMin;

  ShowcaseStop({
    required this.sequence,
    required this.taskNo,
    required this.taskType,
    required this.unitName,
    required this.point,
    required this.isAA,
    required this.durationMin,
  });

  factory ShowcaseStop.fromJson(Map<String, dynamic> j) => ShowcaseStop(
        sequence: (j['sequence'] as num?)?.toInt() ?? 0,
        taskNo: (j['task_no'] ?? '').toString(),
        taskType: (j['task_type'] ?? '').toString(),
        unitName: (j['unit_name'] ?? '').toString(),
        point: LatLng(
          (j['lat'] as num).toDouble(),
          (j['lng'] as num).toDouble(),
        ),
        isAA: j['is_aa'] == true,
        durationMin: (j['duration_min'] as num?)?.toInt() ?? 0,
      );
}

class ShowcaseRoute {
  final int technicianId;
  final String technicianName;
  final String techRole;
  final String specialty;
  final LatLng depot;
  final List<ShowcaseStop> stops;
  final List<LatLng> polyline;
  final double roadKm;
  final int roadMin;
  final String geometrySource;
  final bool hasAA;

  // precomputed for animation
  late final List<double> _cum;
  late final double _total;
  late final List<double> _stopDist;

  ShowcaseRoute({
    required this.technicianId,
    required this.technicianName,
    required this.techRole,
    required this.specialty,
    required this.depot,
    required this.stops,
    required this.polyline,
    required this.roadKm,
    required this.roadMin,
    required this.geometrySource,
    required this.hasAA,
  }) {
    const dist = Distance();
    _cum = [0];
    for (var i = 1; i < polyline.length; i++) {
      _cum.add(_cum[i - 1] + dist(polyline[i - 1], polyline[i]));
    }
    _total = _cum.isNotEmpty ? _cum.last : 0;
    _stopDist = stops.map((s) {
      var best = 0.0, bestD = double.infinity;
      for (var i = 0; i < polyline.length; i++) {
        final d = dist(polyline[i], s.point);
        if (d < bestD) {
          bestD = d;
          best = _cum[i];
        }
      }
      return best;
    }).toList();
  }

  bool get isReal => geometrySource == 'GOOGLE_ROADS' || geometrySource == 'CACHE';

  /// Position along the polyline at fraction t in [0,1].
  LatLng positionAt(double t) {
    if (polyline.isEmpty) return depot;
    if (_total == 0) return polyline.first;
    final d = (t.clamp(0.0, 1.0)) * _total;
    if (d <= 0) return polyline.first;
    if (d >= _total) return polyline.last;
    var i = 1;
    while (i < _cum.length && _cum[i] < d) i++;
    final segLen = (_cum[i] - _cum[i - 1]);
    final f = segLen == 0 ? 0.0 : (d - _cum[i - 1]) / segLen;
    final a = polyline[i - 1], b = polyline[i];
    return LatLng(a.latitude + (b.latitude - a.latitude) * f,
        a.longitude + (b.longitude - a.longitude) * f);
  }

  /// How many stops have been "passed" at fraction t -> live progress.
  int stopsDoneAt(double t) {
    final d = t.clamp(0.0, 1.0) * _total;
    return _stopDist.where((sd) => sd <= d).length;
  }

  factory ShowcaseRoute.fromJson(Map<String, dynamic> j) {
    final poly = ((j['polyline'] as List?) ?? [])
        .map((p) => LatLng((p[0] as num).toDouble(), (p[1] as num).toDouble()))
        .toList();
    final depotJson = j['depot'] as Map<String, dynamic>;
    return ShowcaseRoute(
      technicianId: (j['technician_id'] as num?)?.toInt() ?? 0,
      technicianName: (j['technician_name'] ?? '').toString(),
      techRole: (j['tech_role'] ?? '').toString(),
      specialty: (j['specialty'] ?? '').toString(),
      depot: LatLng((depotJson['lat'] as num).toDouble(),
          (depotJson['lng'] as num).toDouble()),
      stops: ((j['stops'] as List?) ?? [])
          .map((s) => ShowcaseStop.fromJson(s as Map<String, dynamic>))
          .toList(),
      polyline: poly,
      roadKm: (j['road_distance_km'] as num?)?.toDouble() ?? 0,
      roadMin: (j['road_duration_min'] as num?)?.toInt() ?? 0,
      geometrySource: (j['geometry_source'] ?? '').toString(),
      hasAA: j['has_aa'] == true,
    );
  }
}

class ShowcaseData {
  final String group;
  final String date;
  final int shown;
  final int available;
  final int googleCalls;
  final List<ShowcaseRoute> routes;

  ShowcaseData({
    required this.group,
    required this.date,
    required this.shown,
    required this.available,
    required this.googleCalls,
    required this.routes,
  });

  factory ShowcaseData.fromJson(Map<String, dynamic> j) => ShowcaseData(
        group: (j['group'] ?? '').toString(),
        date: (j['date'] ?? '').toString(),
        shown: (j['technicians_shown'] as num?)?.toInt() ?? 0,
        available: (j['technicians_available_that_day'] as num?)?.toInt() ?? 0,
        googleCalls: (j['google_calls_this_request'] as num?)?.toInt() ?? 0,
        routes: ((j['routes'] as List?) ?? [])
            .map((r) => ShowcaseRoute.fromJson(r as Map<String, dynamic>))
            .toList(),
      );
}

// --------------------------------------------------------------------------- //
// Widget
// --------------------------------------------------------------------------- //
class ShowcaseRouteMapView extends StatefulWidget {
  final String baseUrl;
  final String token;
  final String group;
  final int limit;

  const ShowcaseRouteMapView({
    super.key,
    this.baseUrl = 'http://localhost:8000',
    this.token = '',
    this.group = 'Ahmet',
    this.limit = 5,
  });

  @override
  State<ShowcaseRouteMapView> createState() => _ShowcaseRouteMapViewState();
}

class _ShowcaseRouteMapViewState extends State<ShowcaseRouteMapView>
    with SingleTickerProviderStateMixin {
  final MapController _map = MapController();
  late final AnimationController _anim;
  double _speed = 1.0;
  bool _playing = true;

  Future<ShowcaseData>? _future;
  ShowcaseData? _data;
  int? _focusedTechId;

  @override
  void initState() {
    super.initState();
    _anim = AnimationController(vsync: this, duration: const Duration(seconds: 9))
      ..repeat();
    _load();
  }

  @override
  void dispose() {
    _anim.dispose();
    super.dispose();
  }

  void _load() {
    setState(() {
      _future = _fetch();
    });
  }

  Future<ShowcaseData> _fetch() async {
    final uri = Uri.parse('${widget.baseUrl}/api/demo/showcase-routes/')
        .replace(queryParameters: {
      'group': widget.group,
      'limit': '${widget.limit}',
    });
    final r = await http.get(uri, headers: {
      'Content-Type': 'application/json',
      if (widget.token.isNotEmpty) 'Authorization': 'Token ${widget.token}',
    });
    if (r.statusCode != 200) {
      throw Exception('GET showcase-routes -> ${r.statusCode}: ${r.body}');
    }
    final data = ShowcaseData.fromJson(jsonDecode(r.body) as Map<String, dynamic>);
    _data = data;
    // fit camera once data is in
    WidgetsBinding.instance.addPostFrameCallback((_) => _fitAll(data));
    return data;
  }

  Color _colorFor(int idx) => _kRouteColors[idx % _kRouteColors.length];

  void _fitAll(ShowcaseData data) {
    final pts = <LatLng>[];
    for (final r in data.routes) {
      pts.addAll(r.polyline);
      pts.add(r.depot);
    }
    if (pts.isEmpty) return;
    try {
      _map.fitCamera(CameraFit.coordinates(
        coordinates: pts,
        padding: const EdgeInsets.all(48),
      ));
    } catch (_) {
      // map not laid out yet; ignore — user can tap "Fit all"
    }
  }

  void _focus(ShowcaseRoute r) {
    setState(() => _focusedTechId =
        _focusedTechId == r.technicianId ? null : r.technicianId);
    final pts = [...r.polyline, r.depot];
    if (pts.isNotEmpty) {
      _map.fitCamera(CameraFit.coordinates(
        coordinates: pts,
        padding: const EdgeInsets.all(60),
      ));
    }
  }

  void _togglePlay() {
    setState(() => _playing = !_playing);
    if (_playing) {
      _anim.repeat();
    } else {
      _anim.stop();
    }
  }

  void _setSpeed(double s) {
    setState(() => _speed = s);
    _anim.duration = Duration(milliseconds: (9000 / s).round());
    if (_playing) _anim.repeat();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<ShowcaseData>(
      future: _future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return _ErrorView(message: '${snap.error}', onRetry: _load);
        }
        final data = snap.data!;
        if (data.routes.isEmpty) {
          return _ErrorView(
            message: 'No routes for "${data.group}" on ${data.date}. '
                'Seed the Ahmet Yılmaz schedule first.',
            onRetry: _load,
          );
        }

        return LayoutBuilder(builder: (context, c) {
          final narrow = c.maxWidth < 900;
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _TopBar(
                data: data,
                playing: _playing,
                speed: _speed,
                onPlay: _togglePlay,
                onSpeed: _setSpeed,
                onFit: () => _fitAll(data),
                onRefresh: _load,
              ),
              const SizedBox(height: 12),
              Expanded(
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Expanded(flex: 3, child: _buildMap(data)),
                    const SizedBox(width: 16),
                    SizedBox(
                      width: narrow ? 280 : 360,
                      child: _SidePanel(
                        data: data,
                        anim: _anim,
                        colorFor: _colorFor,
                        focusedTechId: _focusedTechId,
                        onSelect: _focus,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          );
        });
      },
    );
  }

  Widget _buildMap(ShowcaseData data) {
    // Static layers (tiles, polylines, stop/depot pins) are built ONCE per
    // build — i.e. only when focus changes, NOT every animation frame. Only the
    // moving-pin layer is wrapped in AnimatedBuilder. Rebuilding the whole
    // FlutterMap each frame would cancel tile loads before they finish, leaving
    // a blank grey map.
    final polylines = <Polyline>[];
    final staticMarkers = <Marker>[];

    for (var i = 0; i < data.routes.length; i++) {
      final r = data.routes[i];
      final color = _colorFor(i);
      final dim = _focusedTechId != null && _focusedTechId != r.technicianId;
      final lineColor = dim ? color.withOpacity(0.12) : color.withOpacity(0.85);
      final op = dim ? 0.25 : 1.0;

      if (r.polyline.length >= 2) {
        polylines.add(Polyline(
          points: r.polyline,
          strokeWidth: dim ? 2 : 4,
          color: lineColor,
        ));
      }

      staticMarkers.add(Marker(
        point: r.depot,
        width: 30,
        height: 30,
        child: Opacity(opacity: op, child: _DepotPin(color: color)),
      ));
      for (final s in r.stops) {
        staticMarkers.add(Marker(
          point: s.point,
          width: 34,
          height: 34,
          child: Opacity(
            opacity: op,
            child: _StopPin(label: '${s.sequence}', color: color, isAA: s.isAA),
          ),
        ));
      }
    }

    return Card(
      clipBehavior: Clip.antiAlias,
      elevation: 1,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: FlutterMap(
        mapController: _map,
        options: const MapOptions(
          initialCenter: LatLng(41.04, 29.02),
          initialZoom: 11,
        ),
        children: [
          TileLayer(
            // CARTO basemap — sends CORS headers, so it renders on Flutter web's
            // canvas. (Plain OSM tiles stay blank on web because they don't.)
            urlTemplate:
                'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
            subdomains: const ['a', 'b', 'c', 'd'],
            maxZoom: 20,
            userAgentPackageName: 'com.example.supervisor_dashboard',
          ),
          PolylineLayer(polylines: polylines),
          MarkerLayer(markers: staticMarkers),
          // Only this layer rebuilds each frame -> tiles below load undisturbed.
          AnimatedBuilder(
            animation: _anim,
            builder: (context, _) {
              final t = _anim.value;
              final vehicles = <Marker>[];
              for (var i = 0; i < data.routes.length; i++) {
                final r = data.routes[i];
                final color = _colorFor(i);
                final dim =
                    _focusedTechId != null && _focusedTechId != r.technicianId;
                vehicles.add(Marker(
                  point: r.positionAt(t),
                  width: 26,
                  height: 26,
                  child: Opacity(
                    opacity: dim ? 0.4 : 1.0,
                    child: _VehiclePin(color: color),
                  ),
                ));
              }
              return MarkerLayer(markers: vehicles);
            },
          ),
        ],
      ),
    );
  }
}

// --------------------------------------------------------------------------- //
// Top bar
// --------------------------------------------------------------------------- //
class _TopBar extends StatelessWidget {
  final ShowcaseData data;
  final bool playing;
  final double speed;
  final VoidCallback onPlay;
  final ValueChanged<double> onSpeed;
  final VoidCallback onFit;
  final VoidCallback onRefresh;

  const _TopBar({
    required this.data,
    required this.playing,
    required this.speed,
    required this.onPlay,
    required this.onSpeed,
    required this.onFit,
    required this.onRefresh,
  });

  @override
  Widget build(BuildContext context) {
    final anyReal = data.routes.any((r) => r.isReal);
    return Card(
      elevation: 1,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Wrap(
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: 18,
          runSpacing: 8,
          children: [
            _meta('Group', data.group),
            _meta('Day', data.date),
            _meta('Showing', '${data.shown} / ${data.available}'),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
              decoration: BoxDecoration(
                color: (anyReal ? const Color(0xFF00838F) : _kAmber).withOpacity(0.12),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Text(
                anyReal ? 'Real road geometry' : 'Straight legs (mock)',
                style: TextStyle(
                  color: anyReal ? const Color(0xFF00838F) : const Color(0xFF8D6E00),
                  fontWeight: FontWeight.w700,
                  fontSize: 12,
                ),
              ),
            ),
            const Spacer(),
            IconButton(
              tooltip: playing ? 'Pause' : 'Play',
              onPressed: onPlay,
              icon: Icon(playing ? Icons.pause_circle : Icons.play_circle),
            ),
            Row(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.speed, size: 18, color: Colors.grey),
              SizedBox(
                width: 110,
                child: Slider(
                  min: 0.3,
                  max: 3,
                  value: speed,
                  onChanged: onSpeed,
                ),
              ),
            ]),
            IconButton(
              tooltip: 'Fit all',
              onPressed: onFit,
              icon: const Icon(Icons.fit_screen),
            ),
            IconButton(
              tooltip: 'Refresh',
              onPressed: onRefresh,
              icon: const Icon(Icons.refresh),
            ),
          ],
        ),
      ),
    );
  }

  Widget _meta(String label, String value) => Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label.toUpperCase(),
              style: const TextStyle(
                  fontSize: 10,
                  letterSpacing: 1.2,
                  color: Colors.grey,
                  fontWeight: FontWeight.w700)),
          Text(value,
              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
        ],
      );
}

// --------------------------------------------------------------------------- //
// Side panel (live progress)
// --------------------------------------------------------------------------- //
class _SidePanel extends StatelessWidget {
  final ShowcaseData data;
  final Animation<double> anim;
  final Color Function(int) colorFor;
  final int? focusedTechId;
  final ValueChanged<ShowcaseRoute> onSelect;

  const _SidePanel({
    required this.data,
    required this.anim,
    required this.colorFor,
    required this.focusedTechId,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 1,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: ListView.separated(
        padding: const EdgeInsets.all(10),
        itemCount: data.routes.length,
        separatorBuilder: (_, __) => const SizedBox(height: 6),
        itemBuilder: (context, i) {
          final r = data.routes[i];
          final color = colorFor(i);
          final active = focusedTechId == r.technicianId;
          return InkWell(
            borderRadius: BorderRadius.circular(11),
            onTap: () => onSelect(r),
            child: Container(
              padding: const EdgeInsets.all(11),
              decoration: BoxDecoration(
                color: active ? color.withOpacity(0.06) : null,
                borderRadius: BorderRadius.circular(11),
                border: Border.all(
                    color: active ? color.withOpacity(0.4) : Colors.transparent),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    width: 12,
                    height: 12,
                    margin: const EdgeInsets.only(top: 3, right: 10),
                    decoration: BoxDecoration(
                        color: color, borderRadius: BorderRadius.circular(4)),
                  ),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(r.technicianName,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                                fontWeight: FontWeight.w700, fontSize: 14)),
                        const SizedBox(height: 2),
                        Text('${r.techRole} · ${r.specialty} · ${r.stops.length} stops',
                            style: const TextStyle(
                                fontSize: 11, color: Colors.grey)),
                        const SizedBox(height: 4),
                        AnimatedBuilder(
                          animation: anim,
                          builder: (context, _) {
                            final done = r.stopsDoneAt(anim.value);
                            if (done >= r.stops.length) {
                              return Text('completed · ${r.stops.length}/${r.stops.length}',
                                  style: const TextStyle(
                                      fontSize: 11, color: Colors.green));
                            }
                            final next = r.stops[done];
                            return Row(children: [
                              Text('→ ${done + 1}/${r.stops.length} ',
                                  style: const TextStyle(
                                      fontSize: 11, fontWeight: FontWeight.w600)),
                              if (next.isAA)
                                const Text('AA ',
                                    style: TextStyle(
                                        fontSize: 11,
                                        color: _kAmber,
                                        fontWeight: FontWeight.w800)),
                              Expanded(
                                child: Text(next.unitName,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(fontSize: 11)),
                              ),
                            ]);
                          },
                        ),
                      ],
                    ),
                  ),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Text('${r.roadKm} km',
                          style: const TextStyle(
                              fontWeight: FontWeight.w700, fontSize: 13)),
                      Text('${r.roadMin} min',
                          style: const TextStyle(fontSize: 11, color: Colors.grey)),
                    ],
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

// --------------------------------------------------------------------------- //
// Pins
// --------------------------------------------------------------------------- //
class _VehiclePin extends StatelessWidget {
  final Color color;
  const _VehiclePin({required this.color});
  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: color,
        shape: BoxShape.circle,
        border: Border.all(color: Colors.white, width: 3),
        boxShadow: [
          BoxShadow(color: color.withOpacity(0.5), blurRadius: 8, spreadRadius: 1),
        ],
      ),
    );
  }
}

class _StopPin extends StatelessWidget {
  final String label;
  final Color color;
  final bool isAA;
  const _StopPin({required this.label, required this.color, required this.isAA});
  @override
  Widget build(BuildContext context) {
    return Container(
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: color,
        shape: BoxShape.circle,
        border: Border.all(color: isAA ? _kAmber : Colors.white, width: isAA ? 3 : 2),
      ),
      child: Text(label,
          style: const TextStyle(
              color: Colors.white, fontSize: 11, fontWeight: FontWeight.bold)),
    );
  }
}

class _DepotPin extends StatelessWidget {
  final Color color;
  const _DepotPin({required this.color});
  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(5),
        border: Border.all(color: color, width: 3),
      ),
      child: Icon(Icons.home, size: 14, color: color),
    );
  }
}

// --------------------------------------------------------------------------- //
// Error view
// --------------------------------------------------------------------------- //
class _ErrorView extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;
  const _ErrorView({required this.message, required this.onRetry});
  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.map_outlined, size: 44, color: Colors.grey),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }
}
