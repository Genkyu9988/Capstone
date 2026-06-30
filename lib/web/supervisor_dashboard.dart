// =============================================================================
//  Supervisor Dashboard  (Flutter Web)  -- LIVE BACKEND VERSION
//  - Polls Django every 5 seconds for technician state
//  - Renders real pins + polylines for every technician's route
//  - Dispatch form actually POSTs and shows which technician got the task
// -----------------------------------------------------------------------------
//  pubspec.yaml dependencies:
//      flutter_map: ^6.1.0
//      latlong2:    ^0.9.0
//      intl:        ^0.19.0
//      http:        ^1.2.0
//
//  Before running:
//    1) python setup_supervisor.py   (in your Django project root)
//       Paste the printed token into kSupervisorToken below.
//    2) Make sure Django is running:  python manage.py runserver 0.0.0.0:8000
//
//  Run with:    flutter run -t lib/web/supervisor_dashboard.dart -d chrome
// =============================================================================
import 'dart:async';
import 'dart:convert';
import 'dart:html' as html; // web download of the exported .xlsx
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'generate_schedule_tab.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:http/http.dart' as http;
import 'package:intl/intl.dart';
import 'package:latlong2/latlong.dart';

// ----- CONFIG ----------------------------------------------------------------
// The token is now obtained at runtime from the /api/login/ flow (see
// LoginScreen below). It starts empty and is filled in after a successful login.
const String kBaseUrl = 'http://localhost:8000';
// Full-schedule tabs ask the report endpoints with this as-of date, which lifts
// the operating-clock "hide the future" clamp and reveals the entire plan.
const String kFullAsOf = 'all';
String kSupervisorToken = '';          // set after login
String kSupervisorName = 'Supervisor'; // set after login (from /api/me/)
const Duration kPollInterval = Duration(seconds: 5);
// -----------------------------------------------------------------------------

void main() => runApp(const SupervisorDashboardApp());

class SupervisorDashboardApp extends StatelessWidget {
  const SupervisorDashboardApp({super.key});

  @override
  Widget build(BuildContext context) {
    final primary = Colors.blue.shade800;
    return MaterialApp(
      title: 'Supervisor Dashboard',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: primary, primary: primary),
        scaffoldBackgroundColor: Colors.grey[100],
      ),
      home: const SupervisorLoginScreen(),
    );
  }
}

// =============================================================================
//  Login screen -- calls /api/login/, stores token, opens the dashboard
// =============================================================================

class SupervisorLoginScreen extends StatefulWidget {
  const SupervisorLoginScreen({super.key});

  @override
  State<SupervisorLoginScreen> createState() => _SupervisorLoginScreenState();
}

class _SupervisorLoginScreenState extends State<SupervisorLoginScreen> {
  final TextEditingController _user = TextEditingController();
  final TextEditingController _pass = TextEditingController();
  bool _loading = false;
  String? _error;

  Future<void> _login() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      // 1) get the auth token
      final r = await http.post(
        Uri.parse('$kBaseUrl/api/login/'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'username': _user.text.trim(),
          'password': _pass.text.trim(),
        }),
      );
      if (r.statusCode != 200) {
        throw Exception('Invalid username or password.');
      }
      final j = jsonDecode(r.body) as Map<String, dynamic>;
      kSupervisorToken = (j['token'] ?? '').toString();
      if (kSupervisorToken.isEmpty) {
        throw Exception('No token returned by server.');
      }

      // 2) fetch who we are (name + group) from /api/me/
      try {
        final me = await http.get(
          Uri.parse('$kBaseUrl/api/me/'),
          headers: {'Authorization': 'Token $kSupervisorToken'},
        );
        if (me.statusCode == 200) {
          final mj = jsonDecode(me.body) as Map<String, dynamic>;
          kSupervisorName = (mj['full_name'] ??
                  mj['name'] ??
                  mj['username'] ??
                  _user.text.trim())
              .toString();
        } else {
          kSupervisorName = _user.text.trim();
        }
      } catch (_) {
        kSupervisorName = _user.text.trim();
      }

      if (!mounted) return;
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(
          builder: (_) =>
              SupervisorDashboardScreen(supervisorName: kSupervisorName),
        ),
      );
    } catch (e) {
      setState(() => _error = e.toString().replaceAll('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  void dispose() {
    _user.dispose();
    _pass.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final primary = Colors.blue.shade800;
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 380),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Icon(Icons.apartment, size: 72, color: primary),
                const SizedBox(height: 16),
                const Text('Supervisor Portal',
                    textAlign: TextAlign.center,
                    style:
                        TextStyle(fontSize: 26, fontWeight: FontWeight.bold)),
                const SizedBox(height: 6),
                const Text('Sign in to manage your group',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.grey)),
                const SizedBox(height: 32),
                TextField(
                  controller: _user,
                  decoration: const InputDecoration(
                    labelText: 'Username',
                    border: OutlineInputBorder(),
                    prefixIcon: Icon(Icons.person),
                  ),
                  onSubmitted: (_) => _login(),
                ),
                const SizedBox(height: 14),
                TextField(
                  controller: _pass,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: 'Password',
                    border: OutlineInputBorder(),
                    prefixIcon: Icon(Icons.lock),
                  ),
                  onSubmitted: (_) => _login(),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!,
                      style: const TextStyle(color: Colors.red, fontSize: 13)),
                ],
                const SizedBox(height: 24),
                FilledButton(
                  onPressed: _loading ? null : _login,
                  style: FilledButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    backgroundColor: primary,
                  ),
                  child: _loading
                      ? const SizedBox(
                          height: 20,
                          width: 20,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: Colors.white))
                      : const Text('Sign In',
                          style: TextStyle(
                              fontSize: 16, fontWeight: FontWeight.bold)),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// =============================================================================
//  API client + state controller
// =============================================================================

/// Snapshot of what the backend returned about every active technician.
class DashboardState {
  final List<TechnicianState> technicians;
  final DateTime fetchedAt;      // real wall-clock time of this fetch
  final DateTime activeDate;     // the OPERATING-CLOCK day the data is for
  final DateTime activeTime;     // the OPERATING-CLOCK instant (ticks in real time)
  DashboardState(this.technicians, this.fetchedAt, this.activeDate, this.activeTime);
  static DashboardState empty() =>
      DashboardState([], DateTime.now(), DateTime.now(), DateTime.now().toUtc());
}

class TechnicianState {
  final int id;
  final String? username;
  final String name;
  final String techRole;     // MAINTENANCE / CALLBACK
  final String specialty;    // ELEVATOR / ESCALATOR / BOTH
  final bool onLeave;
  final double? currentLat;
  final double? currentLng;
  final String status;       // available / onSite / enRoute / done / onLeave
  final List<TechnicianStop> stops;
  final int? nextStopNumber; // the stop they're heading to NOW (from the clock)
  final String? nextUnitName;
  final double? nextLat;
  final double? nextLng;
  final double? displayLat;     // the position to draw (gps OR estimated)
  final double? displayLng;
  final String positionSource;  // "gps" / "estimated_road" / "estimated"
  final bool isLive;            // a phone is currently reporting
  final List<LatLng> routePolyline;  // real road path (empty if none)
  final String? geometrySource;      // GOOGLE_ROADS / CACHE / STRAIGHT_* / null

  TechnicianState({
    required this.id,
    required this.username,
    required this.name,
    required this.techRole,
    required this.specialty,
    required this.onLeave,
    required this.currentLat,
    required this.currentLng,
    required this.status,
    required this.stops,
    required this.nextStopNumber,
    required this.nextUnitName,
    required this.nextLat,
    required this.nextLng,
    required this.displayLat,
    required this.displayLng,
    required this.positionSource,
    required this.isLive,
    required this.routePolyline,
    required this.geometrySource,
  });

  factory TechnicianState.fromJson(Map<String, dynamic> j) {
    return TechnicianState(
      id: j['id'] as int,
      username: j['username'] as String?,
      name: j['name'] ?? '?',
      techRole: j['tech_role'] ?? '',
      specialty: j['specialty'] ?? '',
      onLeave: j['on_leave'] == true,
      currentLat: (j['current_latitude'] as num?)?.toDouble(),
      currentLng: (j['current_longitude'] as num?)?.toDouble(),
      status: j['status'] ?? 'available',
      stops: ((j['stops'] as List?) ?? [])
          .map((s) => TechnicianStop.fromJson(s as Map<String, dynamic>))
          .toList(),
      nextStopNumber: (j['next_stop_number'] as num?)?.toInt(),
      nextUnitName: j['next_unit_name'] as String?,
      nextLat: (j['next_latitude'] as num?)?.toDouble(),
      nextLng: (j['next_longitude'] as num?)?.toDouble(),
      displayLat: (j['display_latitude'] as num?)?.toDouble(),
      displayLng: (j['display_longitude'] as num?)?.toDouble(),
      positionSource: (j['position_source'] ?? 'estimated').toString(),
      isLive: j['is_live'] == true,
      routePolyline: ((j['route_polyline'] as List?) ?? [])
          .map((p) => LatLng((p[0] as num).toDouble(), (p[1] as num).toDouble()))
          .toList(),
      geometrySource: j['geometry_source'] as String?,
    );
  }

  // the point to plot on the map: prefer the server's display position,
  // fall back to last-known GPS.
  double? get plotLat => displayLat ?? currentLat;
  double? get plotLng => displayLng ?? currentLng;

  // True when this technician has a real Google road-shaped route — either
  // fresh from the Routes API (GOOGLE_ROADS) or served from the day's cache
  // (CACHE). The capped/fallback ones (STRAIGHT_*, or no polyline at all) are
  // hidden from the Live Map; they remain scheduled in the backend/console.
  bool get isRoadOriented =>
      routePolyline.length >= 2 &&
      (geometrySource == 'GOOGLE_ROADS' || geometrySource == 'CACHE');
  bool get hasLivePosition => plotLat != null && plotLng != null;

  String? get currentTaskLabel =>
      stops.isEmpty ? null : '${stops.first.unitName} (#${stops.first.stopNumber})';
}

class TechnicianStop {
  final int stopNumber;
  final String taskNo;
  final String taskType;
  final String priority;
  final String unitName;
  final double latitude;
  final double longitude;
  final int durationMin;
  final String state; // done / current / on_route / upcoming
  final DateTime? scheduledStart;
  final DateTime? scheduledEnd;

  TechnicianStop({
    required this.stopNumber,
    required this.taskNo,
    required this.taskType,
    required this.priority,
    required this.unitName,
    required this.latitude,
    required this.longitude,
    required this.durationMin,
    required this.state,
    required this.scheduledStart,
    required this.scheduledEnd,
  });

  factory TechnicianStop.fromJson(Map<String, dynamic> j) => TechnicianStop(
        stopNumber: j['stop_number'] ?? 0,
        taskNo: j['task_no'] ?? '',
        taskType: j['task_type'] ?? '',
        priority: j['priority'] ?? 'NORMAL',
        unitName: j['unit_name'] ?? '',
        latitude: (j['latitude'] as num).toDouble(),
        longitude: (j['longitude'] as num).toDouble(),
        durationMin: j['duration_min'] ?? 0,
        state: (j['state'] ?? 'upcoming').toString(),
        scheduledStart: j['scheduled_start'] == null
            ? null
            : DateTime.tryParse(j['scheduled_start'].toString()),
        scheduledEnd: j['scheduled_end'] == null
            ? null
            : DateTime.tryParse(j['scheduled_end'].toString()),
      );
}

class DispatchUnitOption {
  final int id;
  final String name;
  final String code;
  final String unitType;
  final String address;
  final String city;
  final double latitude;
  final double longitude;
  final int callbackCount;
  final int unassignedCallbackCount;

  DispatchUnitOption({
    required this.id,
    required this.name,
    required this.code,
    required this.unitType,
    required this.address,
    required this.city,
    required this.latitude,
    required this.longitude,
    required this.callbackCount,
    required this.unassignedCallbackCount,
  });

  factory DispatchUnitOption.fromJson(Map<String, dynamic> j) => DispatchUnitOption(
        id: (j['id'] as num).toInt(),
        name: (j['name'] ?? '').toString(),
        code: (j['code'] ?? '').toString(),
        unitType: (j['unit_type'] ?? '').toString(),
        address: (j['address'] ?? '').toString(),
        city: (j['city'] ?? '').toString(),
        latitude: (j['latitude'] as num).toDouble(),
        longitude: (j['longitude'] as num).toDouble(),
        callbackCount: ((j['callback_count'] ?? 0) as num).toInt(),
        unassignedCallbackCount: ((j['unassigned_callback_count'] ?? 0) as num).toInt(),
      );
}


class DispatchResult {
  final String assignedToName;
  final String assignedToUsername;
  final String taskNo;
  final String priority;
  final String unitName;
  final double unitLat;
  final double unitLng;
  final String reason;
  final List<Map<String, dynamic>> scoreboard;

  DispatchResult({
    required this.assignedToName,
    required this.assignedToUsername,
    required this.taskNo,
    required this.priority,
    required this.unitName,
    required this.unitLat,
    required this.unitLng,
    required this.reason,
    required this.scoreboard,
  });

  factory DispatchResult.fromJson(Map<String, dynamic> j) {
    final task = j['task'] as Map<String, dynamic>;
    final unit = task['unit'] as Map<String, dynamic>;
    final assigned = j['assigned_to'] as Map<String, dynamic>;
    return DispatchResult(
      assignedToName: assigned['name'] ?? '?',
      assignedToUsername: assigned['username'] ?? '?',
      taskNo: task['task_no'] ?? '',
      priority: task['priority'] ?? 'NORMAL',
      unitName: unit['name'] ?? '',
      unitLat: (unit['latitude'] as num).toDouble(),
      unitLng: (unit['longitude'] as num).toDouble(),
      reason: j['reason'] ?? '',
      scoreboard: ((j['scoreboard'] as List?) ?? [])
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList(),
    );
  }
}

class ApiClient {
  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'Authorization': 'Token $kSupervisorToken',
      };

  Future<DashboardState> fetchDashboardState() async {
    final r = await http.get(
      Uri.parse('$kBaseUrl/api/dashboard/state/'),
      headers: _headers,
    );
    if (r.statusCode != 200) {
      throw Exception('GET /api/dashboard/state/ -> ${r.statusCode}: ${r.body}');
    }
    final j = jsonDecode(r.body) as Map<String, dynamic>;
    final techs = ((j['technicians'] as List?) ?? [])
        .map((t) => TechnicianState.fromJson(t as Map<String, dynamic>))
        .toList();
    // the OPERATING CLOCK the backend used (sim clock), NOT the device clock
    final activeDate = j['active_date'] != null
        ? DateTime.parse(j['active_date'] as String)
        : DateTime.now();
    final activeTime = j['active_time'] != null
        ? DateTime.parse(j['active_time'] as String).toUtc()
        : DateTime.now().toUtc();
    return DashboardState(techs, DateTime.now(), activeDate, activeTime);
  }

  Future<List<DispatchUnitOption>> fetchDispatchUnits({String query = ''}) async {
    final uri = Uri.parse('$kBaseUrl/api/repair/dispatch-units/').replace(
      queryParameters: query.trim().isEmpty ? null : {'q': query.trim()},
    );
    final r = await http.get(uri, headers: _headers);
    if (r.statusCode != 200) {
      throw Exception('GET /api/repair/dispatch-units/ -> ${r.statusCode}: ${r.body}');
    }
    final j = jsonDecode(r.body) as Map<String, dynamic>;
    return ((j['units'] as List?) ?? [])
        .map((e) => DispatchUnitOption.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<DispatchResult> dispatchTask({
    int? unitId,
    double? latitude,
    double? longitude,
    required String priority,
    required String faultType,
    String description = '',
  }) async {
    final payload = <String, dynamic>{
      'priority': priority,
      'fault_type': faultType,
      'description': description,
    };
    if (unitId != null) {
      payload['unit_id'] = unitId;
    } else {
      payload['latitude'] = latitude;
      payload['longitude'] = longitude;
    }
    final r = await http.post(
      Uri.parse('$kBaseUrl/api/repair/dispatch/'),
      headers: _headers,
      body: jsonEncode(payload),
    );
    if (r.statusCode != 201 && r.statusCode != 200) {
      throw Exception('POST /api/repair/dispatch/ -> ${r.statusCode}: ${r.body}');
    }
    return DispatchResult.fromJson(jsonDecode(r.body) as Map<String, dynamic>);
  }

  Future<List<LeaveRequestItem>> fetchLeaveRequests() async {
    final r = await http.get(
      Uri.parse('$kBaseUrl/api/leave-requests/'),
      headers: _headers,
    );
    if (r.statusCode != 200) {
      throw Exception('GET /api/leave-requests/ -> ${r.statusCode}: ${r.body}');
    }
    final j = jsonDecode(r.body) as Map<String, dynamic>;
    return ((j['requests'] as List?) ?? [])
        .map((e) => LeaveRequestItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> decideLeave(int id, String decision) async {
    final r = await http.post(
      Uri.parse('$kBaseUrl/api/leave-request/$id/decision/'),
      headers: _headers,
      body: jsonEncode({'decision': decision}), // APPROVE / REJECT / RETURN
    );
    if (r.statusCode != 200) {
      throw Exception('POST decision -> ${r.statusCode}: ${r.body}');
    }
  }

  Future<String> addTechnician({
    required String fullName,
    required String techRole,
    required String specialty,
    String addMode = 'NORMAL',
    double? latitude,
    double? longitude,
    DateTime? activeTime,
  }) async {
    final payload = <String, dynamic>{
      'full_name': fullName,
      'tech_role': techRole,
      'specialty': specialty,
      'add_mode': addMode,
      if (activeTime != null) 'as_of': activeTime.toUtc().toIso8601String(),
      if (latitude != null) 'current_latitude': latitude,
      if (longitude != null) 'current_longitude': longitude,
    };
    final r = await http.post(
      Uri.parse('$kBaseUrl/api/technicians/add/'),
      headers: _headers,
      body: jsonEncode(payload),
    );
    if (r.statusCode != 201 && r.statusCode != 200) {
      throw Exception('POST /api/technicians/add/ -> ${r.statusCode}: ${r.body}');
    }
    final j = jsonDecode(r.body) as Map<String, dynamic>;
    return (j['message'] ?? 'Technician added.').toString();
  }

  Future<String> removeTechnician(int id) async {
    final r = await http.post(
      Uri.parse('$kBaseUrl/api/technicians/$id/remove/'),
      headers: _headers,
    );
    if (r.statusCode != 200) {
      throw Exception('POST /api/technicians/$id/remove/ -> ${r.statusCode}: ${r.body}');
    }
    final j = jsonDecode(r.body) as Map<String, dynamic>;
    return (j['message'] ?? 'Technician removed.').toString();
  }

  Future<Map<String, dynamic>> previewTechnicianImpact({
    required String action,
    int? technicianId,
    String? techRole,
    String? specialty,
    String addMode = 'NORMAL',
    DateTime? activeTime,
  }) async {
    final payload = <String, dynamic>{
      'action': action,
      'add_mode': addMode,
      if (activeTime != null) 'as_of': activeTime.toUtc().toIso8601String(),
      if (technicianId != null) 'technician_id': technicianId,
      if (techRole != null) 'tech_role': techRole,
      if (specialty != null) 'specialty': specialty,
    };
    final r = await http.post(
      Uri.parse('$kBaseUrl/api/technicians/impact-preview/'),
      headers: _headers,
      body: jsonEncode(payload),
    );
    if (r.statusCode != 200) {
      throw Exception('POST /api/technicians/impact-preview/ -> ${r.statusCode}: ${r.body}');
    }
    return Map<String, dynamic>.from(jsonDecode(r.body) as Map);
  }

  Future<List<Map<String, dynamic>>> fetchReportMonths({String asOf = ''}) async {
    final uri = Uri.parse('$kBaseUrl/api/reports/months/').replace(
        queryParameters: {if (asOf.isNotEmpty) 'as_of': asOf});
    final r = await http.get(uri, headers: _headers);
    if (r.statusCode != 200) {
      throw Exception('GET /api/reports/months/ -> ${r.statusCode}: ${r.body}');
    }
    final j = jsonDecode(r.body) as Map<String, dynamic>;
    return ((j['months'] as List?) ?? [])
        .map((e) => Map<String, dynamic>.from(e as Map))
        .toList();
  }

  Future<Map<String, dynamic>> fetchMonthlyReport(int year, int month,
      {String asOf = '', String sort = '', String order = '', String search = ''}) async {
    final uri = Uri.parse('$kBaseUrl/api/reports/monthly/').replace(
        queryParameters: {
          'year': '$year', 'month': '$month',
          if (asOf.isNotEmpty) 'as_of': asOf,
          if (sort.isNotEmpty) 'sort': sort,
          if (order.isNotEmpty) 'order': order,
          if (search.isNotEmpty) 'search': search,
        });
    final r = await http.get(uri, headers: _headers);
    if (r.statusCode != 200) {
      throw Exception('GET /api/reports/monthly/ -> ${r.statusCode}: ${r.body}');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  String exportUrl(int year, int month,
      {String asOf = '', String sort = '', String order = '', String search = ''}) {
    return Uri.parse('$kBaseUrl/api/reports/monthly/export/').replace(
        queryParameters: {
          'year': '$year', 'month': '$month',
          if (asOf.isNotEmpty) 'as_of': asOf,
          if (sort.isNotEmpty) 'sort': sort,
          if (order.isNotEmpty) 'order': order,
          if (search.isNotEmpty) 'search': search,
        }).toString();
  }

  Future<Map<String, dynamic>> fetchUnitHistorySummary(
      {String search = '', int page = 1, int pageSize = 50, String asOf = '',
       String sort = '', String order = '', String status = 'all'}) async {
    final uri = Uri.parse('$kBaseUrl/api/units/history/').replace(
        queryParameters: {
          if (search.isNotEmpty) 'search': search,
          'page': '$page',
          'page_size': '$pageSize',
          if (asOf.isNotEmpty) 'as_of': asOf,
          if (sort.isNotEmpty) 'sort': sort,
          if (order.isNotEmpty) 'order': order,
          if (status.isNotEmpty && status != 'all') 'status': status,
        });
    final r = await http.get(uri, headers: _headers);
    if (r.statusCode != 200) {
      throw Exception('GET /api/units/history/ -> ${r.statusCode}: ${r.body}');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> fetchUnitHistoryDetail(int unitId,
      {String asOf = ''}) async {
    final uri = Uri.parse('$kBaseUrl/api/units/$unitId/history/').replace(
        queryParameters: {
          if (asOf.isNotEmpty) 'as_of': asOf,
        });
    final r = await http.get(uri, headers: _headers);
    if (r.statusCode != 200) {
      throw Exception('GET /api/units/$unitId/history/ -> ${r.statusCode}: ${r.body}');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  String unitHistoryExportUrl({String asOf = '', String sort = '', String order = '', String search = '', String status = 'all'}) {
    return Uri.parse('$kBaseUrl/api/units/history/export/').replace(
      queryParameters: {
        if (asOf.isNotEmpty) 'as_of': asOf,
        if (sort.isNotEmpty) 'sort': sort,
        if (order.isNotEmpty) 'order': order,
        if (search.isNotEmpty) 'search': search,
        if (status.isNotEmpty && status != 'all') 'status': status,
      },
    ).toString();
  }

  Future<Map<String, dynamic>> fetchMaintenanceOverview(
      {String type = '', String search = '', int page = 1, String asOf = '',
       String sort = '', String order = ''}) async {
    final uri = Uri.parse('$kBaseUrl/api/overview/maintenance/').replace(
        queryParameters: {
          if (type.isNotEmpty) 'type': type,
          if (search.isNotEmpty) 'search': search,
          'page': '$page',
          if (asOf.isNotEmpty) 'as_of': asOf,
          if (sort.isNotEmpty) 'sort': sort,
          if (order.isNotEmpty) 'order': order,
        });
    final r = await http.get(uri, headers: _headers);
    if (r.statusCode != 200) {
      throw Exception('GET maintenance overview -> ${r.statusCode}: ${r.body}');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> fetchCallbackOverview(
      {String priority = '', String status = '', String search = '', int page = 1, String asOf = '',
       String sort = '', String order = ''}) async {
    final uri = Uri.parse('$kBaseUrl/api/overview/callbacks/').replace(
        queryParameters: {
          if (priority.isNotEmpty) 'priority': priority,
          if (status.isNotEmpty) 'status': status,
          if (search.isNotEmpty) 'search': search,
          'page': '$page',
          if (asOf.isNotEmpty) 'as_of': asOf,
          if (sort.isNotEmpty) 'sort': sort,
          if (order.isNotEmpty) 'order': order,
        });
    final r = await http.get(uri, headers: _headers);
    if (r.statusCode != 200) {
      throw Exception('GET callback overview -> ${r.statusCode}: ${r.body}');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  String callbackOverviewExportUrl({String priority = '', String status = '', String search = '', String asOf = ''}) {
    return Uri.parse('$kBaseUrl/api/overview/callbacks/export/').replace(
      queryParameters: {
        if (priority.isNotEmpty) 'priority': priority,
        if (status.isNotEmpty) 'status': status,
        if (search.isNotEmpty) 'search': search,
        if (asOf.isNotEmpty) 'as_of': asOf,
      },
    ).toString();
  }

  Future<Map<String, dynamic>> fetchMonthlyLog(
      int year, int month, {int page = 1, String asOf = '',
      String search = '', String status = '', String priority = '',
      String sort = '', String order = ''}) async {
    final uri = Uri.parse('$kBaseUrl/api/overview/monthly-log/').replace(
        queryParameters: {
          'year': '$year', 'month': '$month', 'page': '$page',
          if (asOf.isNotEmpty) 'as_of': asOf,
          if (search.isNotEmpty) 'search': search,
          if (status.isNotEmpty) 'status': status,
          if (priority.isNotEmpty) 'priority': priority,
          if (sort.isNotEmpty) 'sort': sort,
          if (order.isNotEmpty) 'order': order,
        });
    final r = await http.get(uri, headers: _headers);
    if (r.statusCode != 200) {
      throw Exception('GET monthly log -> ${r.statusCode}: ${r.body}');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> fetchDailyReport(
      {String date = '', String technicianId = '', String asOf = '',
       String search = '', String status = '', String type = '',
       String sort = '', String order = ''}) async {
    final uri = Uri.parse('$kBaseUrl/api/overview/daily-report/').replace(
        queryParameters: {
          if (date.isNotEmpty) 'date': date,
          if (technicianId.isNotEmpty) 'technician_id': technicianId,
          if (asOf.isNotEmpty) 'as_of': asOf,
          if (search.isNotEmpty) 'search': search,
          if (status.isNotEmpty && status.toLowerCase() != 'all') 'status': status,
          if (type.isNotEmpty && type.toLowerCase() != 'all') 'type': type,
          if (sort.isNotEmpty) 'sort': sort,
          if (order.isNotEmpty) 'order': order,
        });
    final r = await http.get(uri, headers: _headers);
    if (r.statusCode != 200) {
      throw Exception('GET daily report -> ${r.statusCode}: ${r.body}');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }
}

/// Polls the backend and rebroadcasts updates so multiple views stay in sync.
class DashboardController extends ChangeNotifier {
  final ApiClient _api = ApiClient();
  DashboardState _state = DashboardState.empty();
  String? _error;
  bool _loadingFirstTime = true;
  Timer? _timer;

  DashboardState get state => _state;
  String? get error => _error;
  bool get loadingFirstTime => _loadingFirstTime;

  void start() {
    refresh();
    _timer ??= Timer.periodic(kPollInterval, (_) => refresh());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> refresh() async {
    try {
      _state = await _api.fetchDashboardState();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _loadingFirstTime = false;
      notifyListeners();
    }
  }

  Future<List<DispatchUnitOption>> fetchDispatchUnits({String query = ''}) {
    return _api.fetchDispatchUnits(query: query);
  }

  Future<DispatchResult> dispatch({
    int? unitId,
    double? latitude,
    double? longitude,
    required String priority,
    required String faultType,
    String description = '',
  }) async {
    final result = await _api.dispatchTask(
      unitId: unitId,
      latitude: latitude,
      longitude: longitude,
      priority: priority,
      faultType: faultType,
      description: description,
    );
    await refresh(); // immediately re-pull so map updates
    return result;
  }
}

// =============================================================================
//  Root screen — AppBar + NavigationRail + the selected view
// =============================================================================

class SupervisorDashboardScreen extends StatefulWidget {
  final String supervisorName;
  const SupervisorDashboardScreen({super.key, required this.supervisorName});

  @override
  State<SupervisorDashboardScreen> createState() =>
      _SupervisorDashboardScreenState();
}

class _SupervisorDashboardScreenState extends State<SupervisorDashboardScreen> {
  int _selectedIndex = 0;
  final DashboardController _controller = DashboardController();

  // Derive the supervisor's group type from the loaded technicians' roles.
  // MAINTENANCE/BOTH -> has maintenance; CALLBACK/BOTH -> has callback.
  bool _hasMaintenance(DashboardState s) =>
      s.technicians.any((t) =>
          t.techRole == 'MAINTENANCE' || t.techRole == 'BOTH');
  bool _hasCallback(DashboardState s) =>
      s.technicians.any((t) =>
          t.techRole == 'CALLBACK' || t.techRole == 'BOTH');

  /// Build the list of visible (navItem, body) pairs for this group type.
  /// Tabs that don't apply to the group are omitted entirely.
  List<_TabDef> _tabsFor(DashboardState s) {
    final hasM = _hasMaintenance(s);
    final hasC = _hasCallback(s);
    // before techs load, show everything so the UI isn't empty
    final unknown = s.technicians.isEmpty;
    final showM = unknown || hasM;
    final showC = unknown || hasC;

    final tabs = <_TabDef>[
      _TabDef(const _NavItem(Icons.map_outlined, Icons.map, 'Live Map'),
          (st) => LiveMapView(state: st, onChanged: () => _controller.refresh())),
      _TabDef(const _NavItem(Icons.event_busy_outlined, Icons.event_busy, 'Leave Requests'),
          (st) => LeaveRequestsView(
              activeDate: st.activeDate,
              onChanged: () => _controller.refresh())),
      _TabDef(const _NavItem(Icons.assessment_outlined, Icons.assessment, 'Reports'),
          (st) => MonthlyReportView(activeDate: st.activeDate)),
      _TabDef(const _NavItem(Icons.apartment_outlined, Icons.apartment, 'Unit History'),
          (st) => const UnitHistoryView()),
      if (showM)
        _TabDef(const _NavItem(Icons.build_outlined, Icons.build, 'Maintenance Overview'),
            (st) => const MaintenanceOverviewTab()),
      if (showC)
        _TabDef(const _NavItem(Icons.report_problem_outlined, Icons.report_problem, 'Repair / Callback'),
            (st) => const CallbackOverviewTab()),
      if (showC)
        _TabDef(const _NavItem(Icons.send_outlined, Icons.send, 'Dispatch'),
            (st) => DispatchTab(controller: _controller)),
      _TabDef(const _NavItem(Icons.calendar_month_outlined, Icons.calendar_month, 'Monthly Log'),
          (st) => MonthlyLogTab(activeDate: st.activeDate)),
      _TabDef(const _NavItem(Icons.today_outlined, Icons.today, 'Daily Report'),
          (st) => DailyReportTab(activeDate: st.activeDate, activeTime: st.activeTime)),
    ];
    return tabs;
  }

  // The bottom rail group: full-schedule twins of the roll-date report tabs.
  // Same widgets, fullSchedule: true -> they query with as-of = far future,
  // which lifts the operating-clock clamp and shows the entire generated plan.
  List<_TabDef> _fullTabsFor(DashboardState s) {
    final unknown = s.technicians.isEmpty;
    final showM = unknown || _hasMaintenance(s);
    final showC = unknown || _hasCallback(s);
    return <_TabDef>[
      _TabDef(const _NavItem(Icons.assessment_outlined, Icons.assessment, 'Full · Report'),
          (st) => MonthlyReportView(activeDate: st.activeDate, fullSchedule: true)),
      _TabDef(const _NavItem(Icons.apartment_outlined, Icons.apartment, 'Full · Unit History'),
          (st) => const UnitHistoryView(fullSchedule: true)),
      if (showM)
        _TabDef(const _NavItem(Icons.build_outlined, Icons.build, 'Full · Maintenance'),
            (st) => const MaintenanceOverviewTab(fullSchedule: true)),
      if (showC)
        _TabDef(const _NavItem(Icons.report_problem_outlined, Icons.report_problem, 'Full · Callback'),
            (st) => const CallbackOverviewTab(fullSchedule: true)),
      _TabDef(const _NavItem(Icons.calendar_month_outlined, Icons.calendar_month, 'Full · Monthly Log'),
          (st) => MonthlyLogTab(activeDate: st.activeDate, fullSchedule: true)),
      _TabDef(const _NavItem(Icons.today_outlined, Icons.today, 'Full · Daily Report'),
          (st) => DailyReportTab(activeDate: st.activeDate, activeTime: st.activeTime, fullSchedule: true)),
    ];
  }

  // One vertical button in the bottom "full schedule" rail group.
  Widget _fullRailButton(_TabDef t, int index, bool extended, Color primary) {
    final selected = _selectedIndex == index;
    final fg = selected ? primary : Colors.grey[700];
    return InkWell(
      onTap: () => setState(() => _selectedIndex = index),
      child: Container(
        width: double.infinity,
        color: selected ? primary.withOpacity(0.10) : null,
        padding: EdgeInsets.symmetric(
            horizontal: extended ? 16 : 0, vertical: 10),
        child: extended
            ? Row(children: [
                Icon(selected ? t.nav.selectedIcon : t.nav.icon, size: 22, color: fg),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(t.nav.label,
                      style: TextStyle(
                          color: fg,
                          fontSize: 13,
                          fontWeight:
                              selected ? FontWeight.w600 : FontWeight.w400)),
                ),
              ])
            : Tooltip(
                message: t.nav.label,
                child: Icon(selected ? t.nav.selectedIcon : t.nav.icon,
                    size: 24, color: fg),
              ),
      ),
    );
  }

  @override
  void initState() {
    super.initState();
    _controller.start();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  int _aaCount(DashboardState s) {
    int n = 0;
    for (final t in s.technicians) {
      for (final st in t.stops) {
        if (st.priority == 'AA') n++;
      }
    }
    return n;
  }

  @override
  Widget build(BuildContext context) {
    final primary = Colors.blue.shade800;
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, _) {
        final state = _controller.state;
        final top = _tabsFor(state);
        final full = _fullTabsFor(state);
        final tabs = [...top, ...full]; // one shared selection index space
        // keep the selected index in range as tabs appear/disappear
        if (_selectedIndex >= tabs.length) _selectedIndex = 0;
        return Scaffold(
          backgroundColor: Colors.grey[100],
          body: Column(
            children: [
              _DashboardAppBar(
                supervisorName: widget.supervisorName,
                notificationCount: _aaCount(state),
                lastRefresh: state.fetchedAt,
                activeDate: state.activeDate,
                activeTime: state.activeTime,
                error: _controller.error,
                onRefresh: _controller.refresh,
              ),
              Expanded(
                child: LayoutBuilder(
                  builder: (context, c) {
                    final extended = c.maxWidth >= 1200;
                    return Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        SizedBox(
                          width: extended ? 220 : 80,
                          child: Container(
                            color: Colors.white,
                            child: Column(
                              children: [
                                Expanded(
                                  child: NavigationRail(
                                    backgroundColor: Colors.white,
                                    extended: extended,
                                    minExtendedWidth: 220,
                                    // null when a bottom (full-schedule) tab is active
                                    selectedIndex: _selectedIndex < top.length
                                        ? _selectedIndex
                                        : null,
                                    labelType: extended
                                        ? NavigationRailLabelType.none
                                        : NavigationRailLabelType.all,
                                    onDestinationSelected: (i) =>
                                        setState(() => _selectedIndex = i),
                                    indicatorColor: primary.withOpacity(0.12),
                                    selectedIconTheme:
                                        IconThemeData(color: primary),
                                    selectedLabelTextStyle: TextStyle(
                                      color: primary,
                                      fontWeight: FontWeight.w600,
                                    ),
                                    unselectedIconTheme:
                                        IconThemeData(color: Colors.grey[700]),
                                    unselectedLabelTextStyle:
                                        TextStyle(color: Colors.grey[700]),
                                    destinations: [
                                      for (final t in top)
                                        NavigationRailDestination(
                                          icon: Icon(t.nav.icon),
                                          selectedIcon: Icon(t.nav.selectedIcon),
                                          label: Text(t.nav.label),
                                        ),
                                    ],
                                  ),
                                ),
                                const Divider(height: 1, thickness: 1),
                                Padding(
                                  padding: EdgeInsets.fromLTRB(
                                      extended ? 16 : 0, 10, 0, 4),
                                  child: extended
                                      ? Row(children: [
                                          Icon(Icons.all_inclusive,
                                              size: 14, color: Colors.grey[500]),
                                          const SizedBox(width: 6),
                                          Text('FULL SCHEDULE',
                                              style: TextStyle(
                                                  fontSize: 11,
                                                  letterSpacing: 1.0,
                                                  fontWeight: FontWeight.w700,
                                                  color: Colors.grey[500])),
                                        ])
                                      : Center(
                                          child: Icon(Icons.all_inclusive,
                                              size: 18, color: Colors.grey[500])),
                                ),
                                for (int i = 0; i < full.length; i++)
                                  _fullRailButton(full[i], top.length + i,
                                      extended, primary),
                                const SizedBox(height: 8),
                              ],
                            ),
                          ),
                        ),
                        Container(width: 1, color: Colors.grey[200]),
                        Expanded(
                          child: Padding(
                            padding: const EdgeInsets.all(20),
                            child: _controller.loadingFirstTime
                                ? const Center(child: CircularProgressIndicator())
                                : KeyedSubtree(
                                    // distinct key per tab so a roll-date tab and
                                    // its full-schedule twin (same widget type) get
                                    // separate State and each runs initState/_load
                                    key: ValueKey(_selectedIndex),
                                    child: tabs[_selectedIndex].body(state),
                                  ),
                          ),
                        ),
                      ],
                    );
                  },
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _TabDef {
  final _NavItem nav;
  final Widget Function(DashboardState) body;
  const _TabDef(this.nav, this.body);
}

class _NavItem {
  final IconData icon;
  final IconData selectedIcon;
  final String label;
  const _NavItem(this.icon, this.selectedIcon, this.label);
}

// =============================================================================
//  Top AppBar
// =============================================================================

class _DashboardAppBar extends StatelessWidget {
  final String supervisorName;
  final int notificationCount;
  final DateTime lastRefresh;
  final DateTime activeDate;
  final DateTime activeTime;
  final String? error;
  final VoidCallback onRefresh;

  const _DashboardAppBar({
    required this.supervisorName,
    required this.notificationCount,
    required this.lastRefresh,
    required this.activeDate,
    required this.activeTime,
    required this.error,
    required this.onRefresh,
  });

  @override
  Widget build(BuildContext context) {
    final primary = Colors.blue.shade800;
    final dateLabel = DateFormat('EEEE, d MMMM y').format(activeDate);
    final opTimeLabel = DateFormat('HH:mm').format(activeTime);   // operating clock
    final timeLabel = DateFormat('HH:mm:ss').format(lastRefresh); // real refresh

    return Container(
      height: 68,
      decoration: BoxDecoration(
        color: Colors.white,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.06),
            blurRadius: 8,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 24),
        child: Row(
          children: [
            Icon(Icons.elevator, color: primary, size: 28),
            const SizedBox(width: 12),
            Text(
              'Supervisor Dashboard',
              style: TextStyle(
                color: primary,
                fontSize: 20,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(width: 14),
            if (error != null)
              Tooltip(
                message: error!,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: Colors.red.shade50,
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: Colors.red.shade300),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.error_outline, color: Colors.red.shade700, size: 14),
                      const SizedBox(width: 6),
                      Text(
                        'Backend error',
                        style: TextStyle(color: Colors.red.shade700, fontSize: 12),
                      ),
                    ],
                  ),
                ),
              ),
            const Spacer(),
            Icon(Icons.sync, size: 16, color: Colors.grey[600]),
            const SizedBox(width: 6),
            Text(
              'Last update $timeLabel',
              style: TextStyle(color: Colors.grey[700], fontSize: 13),
            ),
            const SizedBox(width: 14),
            IconButton(
              tooltip: 'Refresh now',
              icon: const Icon(Icons.refresh, size: 20),
              onPressed: onRefresh,
            ),
            const SizedBox(width: 14),
            Icon(Icons.calendar_today_outlined, size: 16, color: Colors.grey[600]),
            const SizedBox(width: 6),
            Text(
              '$dateLabel · $opTimeLabel',
              style: TextStyle(color: Colors.grey[700], fontSize: 14),
            ),
            const SizedBox(width: 24),
            Container(height: 32, width: 1, color: Colors.grey[300]),
            const SizedBox(width: 24),
            _NotificationBell(count: notificationCount),
            const SizedBox(width: 24),
            CircleAvatar(
              backgroundColor: primary,
              radius: 18,
              child: Text(
                supervisorName.isNotEmpty
                    ? supervisorName[0].toUpperCase()
                    : '?',
                style: const TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
            const SizedBox(width: 10),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  supervisorName,
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    fontSize: 14,
                  ),
                ),
                Text(
                  'Supervisor',
                  style: TextStyle(color: Colors.grey[600], fontSize: 12),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _NotificationBell extends StatelessWidget {
  final int count;
  const _NotificationBell({required this.count});

  @override
  Widget build(BuildContext context) {
    final hasAlerts = count > 0;
    return Tooltip(
      message: hasAlerts ? '$count AA emergencies in schedule' : 'No AA emergencies',
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          Padding(
            padding: const EdgeInsets.all(6),
            child: Icon(
              Icons.notifications_outlined,
              color: hasAlerts ? Colors.red.shade700 : Colors.grey[700],
              size: 26,
            ),
          ),
          if (hasAlerts)
            Positioned(
              right: 0,
              top: 0,
              child: Container(
                padding: const EdgeInsets.all(4),
                decoration: BoxDecoration(
                  color: Colors.red.shade700,
                  shape: BoxShape.circle,
                  border: Border.all(color: Colors.white, width: 1.5),
                ),
                constraints: const BoxConstraints(minWidth: 18, minHeight: 18),
                child: Text(
                  '$count',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

// =============================================================================
//  Live Map view — map with real polylines on the left, technician list right
// =============================================================================

class LiveMapView extends StatefulWidget {
  final DashboardState state;
  final VoidCallback? onChanged;
  const LiveMapView({super.key, required this.state, this.onChanged});

  @override
  State<LiveMapView> createState() => _LiveMapViewState();
}

class _LiveMapViewState extends State<LiveMapView> {
  int? _selectedTechId; // null = show everyone

  Color _colorForTech(TechnicianState t) {
    // Stable color per technician so each keeps a distinct route colour.
    const palette = [
      Color(0xFF1976D2), // blue
      Color(0xFFD32F2F), // red
      Color(0xFF388E3C), // green
      Color(0xFFF57C00), // orange
      Color(0xFF7B1FA2), // purple
      Color(0xFF00838F), // teal
    ];
    return palette[t.name.hashCode.abs() % palette.length];
  }

  void _toggle(int id) {
    setState(() => _selectedTechId = (_selectedTechId == id) ? null : id);
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final narrow = constraints.maxWidth < 900;
        // LIVE MAP DECLUTTER: show only technicians whose route is real Google
        // road geometry (GOOGLE_ROADS fresh, or CACHE on later polls). The rest
        // of the fleet is still scheduled in the backend and visible in the
        // API/console — they're just hidden from this map view.
        // To show everyone again, delete the `.where(...)` below.
        final mapTechs = widget.state.technicians
            .where((t) => t.isRoadOriented)
            .toList();
        return Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(
              flex: 3,
              child: _MapPanel(
                technicians: mapTechs,
                totalFleet: widget.state.technicians.length,
                colorFor: _colorForTech,
                selectedTechId: _selectedTechId,
              ),
            ),
            const SizedBox(width: 16),
            SizedBox(
              width: narrow ? 280 : 360,
              child: _TechniciansSidePanel(
                technicians: mapTechs,
                colorFor: _colorForTech,
                selectedTechId: _selectedTechId,
                onSelect: _toggle,
                onChanged: widget.onChanged,
                activeTime: widget.state.activeTime,
              ),
            ),
          ],
        );
      },
    );
  }
}

class _MapPanel extends StatelessWidget {
  final List<TechnicianState> technicians;
  final int totalFleet;
  final Color Function(TechnicianState) colorFor;
  final int? selectedTechId;
  const _MapPanel({
    required this.technicians,
    required this.totalFleet,
    required this.colorFor,
    required this.selectedTechId,
  });

  Marker _regionLabel(LatLng p, String text, Color c) => Marker(
        point: p,
        width: 92,
        height: 26,
        child: Container(
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: Colors.white.withOpacity(0.85),
            borderRadius: BorderRadius.circular(13),
            border: Border.all(color: c.withOpacity(0.5)),
          ),
          child: Text(
            text,
            style: TextStyle(
              color: c,
              fontWeight: FontWeight.bold,
              fontSize: 11,
              letterSpacing: 1.5,
            ),
          ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final polylines = <Polyline>[];
    final markers = <Marker>[];

    // Bosphorus region divider (~29.02 E) — always visible, never dimmed.
    polylines.add(Polyline(
      points: const [LatLng(40.80, 29.02), LatLng(41.25, 29.02)],
      strokeWidth: 2,
      color: Colors.indigo.withOpacity(0.30),
    ));

    // Draw the selected technician last so its route sits on top.
    final ordered = [...technicians];
    if (selectedTechId != null) {
      ordered.sort((a, b) =>
          (a.id == selectedTechId ? 1 : 0).compareTo(b.id == selectedTechId ? 1 : 0));
    }

    for (final t in ordered) {
      final selected = selectedTechId == null || selectedTechId == t.id;
      final color = colorFor(t);
      final lineColor = selected ? color.withOpacity(0.9) : color.withOpacity(0.10);
      final markerOpacity = selected ? 1.0 : 0.22;

      final depot = (t.plotLat != null && t.plotLng != null)
          ? LatLng(t.plotLat!, t.plotLng!)
          : null;
      // Real Google road geometry when we have it (the capped few); otherwise
      // straight legs from the dot through the stops.
      final route = (t.routePolyline.length >= 2)
          ? t.routePolyline
          : <LatLng>[
              if (depot != null) depot,
              for (final s in t.stops) LatLng(s.latitude, s.longitude),
            ];
      if (route.length >= 2) {
        polylines.add(Polyline(
          points: route,
          strokeWidth: selected ? 4 : 2,
          color: lineColor,
        ));
      }
      // Where this technician is heading NOW: position -> next stop.
      if (depot != null && t.nextLat != null && t.nextLng != null) {
        polylines.add(Polyline(
          points: [depot, LatLng(t.nextLat!, t.nextLng!)],
          strokeWidth: selected ? 5 : 2,
          color: selected
              ? const Color(0xFFF59E0B)
              : const Color(0xFFF59E0B).withOpacity(0.15),
        ));
      }
      if (depot != null) {
        markers.add(Marker(
          point: depot,
          width: 44,
          height: 44,
          child: Opacity(
            opacity: markerOpacity,
            child: _DepotPin(
              label: t.name.isNotEmpty ? t.name[0] : '?',
              color: color,
              live: t.isLive,
            ),
          ),
        ));
      }
      for (final s in t.stops) {
        markers.add(Marker(
          point: LatLng(s.latitude, s.longitude),
          width: 40,
          height: 40,
          child: Opacity(
            opacity: markerOpacity,
            child: _StopPin(
              label: '${s.stopNumber}',
              color: color,
              isAA: s.priority == 'AA',
            ),
          ),
        ));
      }
    }

    // Region labels on top.
    markers.add(_regionLabel(const LatLng(41.205, 28.88), 'EUROPE', Colors.blue.shade700));
    markers.add(_regionLabel(const LatLng(41.205, 29.18), 'ASIA', Colors.deepOrange.shade700));

    const center = LatLng(41.04, 29.02);

    return _DashboardCard(
      padding: EdgeInsets.zero,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: Stack(
          children: [
            FlutterMap(
              options: MapOptions(
                initialCenter: center,
                initialZoom: 11,
              ),
              children: [
                TileLayer(
                  urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                  userAgentPackageName: 'com.example.supervisor_dashboard',
                ),
                PolylineLayer(polylines: polylines),
                MarkerLayer(markers: markers),
              ],
            ),
            if (selectedTechId != null)
              Positioned(
                top: 12,
                left: 12,
                child: Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(
                    color: Colors.black.withOpacity(0.7),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: const Text(
                    'Focused on one technician · tap their name again to show all',
                    style: TextStyle(color: Colors.white, fontSize: 12),
                  ),
                ),
              ),
            if (technicians.isEmpty)
              Positioned.fill(
                child: Center(
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 14, vertical: 10),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      totalFleet == 0
                          ? 'No active technicians — run seed_demo_fleet.py'
                          : 'No cached Google routes to show yet.\n'
                              'All $totalFleet are still scheduled, but this date needs '
                              'precache_google_routes or the cache was overwritten.',
                      textAlign: TextAlign.center,
                      style: const TextStyle(fontSize: 14),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _DepotPin extends StatelessWidget {
  final String label;
  final Color color;
  final bool live;
  const _DepotPin({required this.label, required this.color, this.live = false});
  @override
  Widget build(BuildContext context) {
    // live GPS: solid coloured pin + green "reporting" dot.
    // last-known (not reporting): muted/hollow pin, no green dot.
    return Tooltip(
      message: live ? '$label · live GPS' : '$label · last known location',
      child: Stack(
        clipBehavior: Clip.none,
        alignment: Alignment.center,
        children: [
          Container(
            decoration: BoxDecoration(
              color: live ? color : Colors.white,
              shape: BoxShape.circle,
              border: Border.all(
                color: live ? color : color.withOpacity(0.5),
                width: 3,
              ),
              boxShadow: const [BoxShadow(color: Colors.black26, blurRadius: 4)],
            ),
            child: Center(
              child: Icon(
                Icons.person_pin_circle,
                color: live ? Colors.white : color.withOpacity(0.6),
                size: 22,
              ),
            ),
          ),
          if (live)
            Positioned(
              right: -1,
              bottom: -1,
              child: Container(
                width: 12,
                height: 12,
                decoration: BoxDecoration(
                  color: Colors.greenAccent.shade700,
                  shape: BoxShape.circle,
                  border: Border.all(color: Colors.white, width: 2),
                ),
              ),
            ),
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
      decoration: BoxDecoration(
        color: color,
        shape: BoxShape.circle,
        border: Border.all(
          color: isAA ? Colors.yellow : Colors.white,
          width: isAA ? 3.5 : 2.5,
        ),
        boxShadow: const [BoxShadow(color: Colors.black26, blurRadius: 4)],
      ),
      child: Center(
        child: Text(
          label,
          style: const TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.bold,
            fontSize: 13,
          ),
        ),
      ),
    );
  }
}


class _ImpactPreviewBox extends StatelessWidget {
  final String action; // ADD / REMOVE
  final int? technicianId;
  final String? techRole;
  final String? specialty;
  final String addMode;
  final DateTime? activeTime;

  const _ImpactPreviewBox({
    required this.action,
    this.technicianId,
    this.techRole,
    this.specialty,
    this.addMode = 'NORMAL',
    this.activeTime,
    super.key,
  });

  Color _riskColor(String risk) {
    switch (risk) {
      case 'BALANCED':
        return Colors.green.shade700;
      case 'OVERLOAD':
        return Colors.red.shade700;
      case 'UNDERLOAD':
        return Colors.orange.shade800;
      default:
        return Colors.blueGrey.shade700;
    }
  }

  Color _riskBackground(String risk) {
    switch (risk) {
      case 'BALANCED':
        return Colors.green.shade50;
      case 'OVERLOAD':
        return Colors.red.shade50;
      case 'UNDERLOAD':
        return Colors.orange.shade50;
      default:
        return Colors.blueGrey.shade50;
    }
  }

  Widget _metric(String label, String value, {Color? valueColor}) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.blueGrey.shade100),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: TextStyle(color: Colors.grey.shade600, fontSize: 11)),
          const SizedBox(height: 4),
          Text(value, style: TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w800,
            color: valueColor ?? Colors.blueGrey.shade900,
          )),
        ],
      ),
    );
  }

  String _fmtPct(dynamic v) {
    if (v == null) return 'N/A';
    return '${v.toString()}%';
  }

  Widget _backlogTasksPreview(List<dynamic> tasks, {required bool isCallback}) {
    if (tasks.isEmpty) return const SizedBox.shrink();
    final title = isCallback
        ? 'Unassigned callback tasks used for suggested location'
        : 'Unassigned maintenance tasks used for suggested location';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: 8),
        Text(title,
            style: TextStyle(fontWeight: FontWeight.w700, color: Colors.blueGrey.shade800, fontSize: 12)),
        const SizedBox(height: 4),
        for (final raw in tasks.take(4))
          Builder(builder: (_) {
            final t = Map<String, dynamic>.from(raw as Map);
            final priority = (t['priority'] ?? '').toString();
            return Padding(
              padding: const EdgeInsets.only(bottom: 3),
              child: Text(
                '${t['task_no'] ?? '-'} · ${t['unit_name'] ?? '-'}${priority.isNotEmpty ? ' · $priority' : ''}',
                overflow: TextOverflow.ellipsis,
                style: TextStyle(color: Colors.blueGrey.shade700, fontSize: 11),
              ),
            );
          }),
        if (tasks.length > 4)
          Text('+${tasks.length - 4} more backlog task(s)',
              style: TextStyle(color: Colors.blueGrey.shade600, fontSize: 11)),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Map<String, dynamic>>(
      future: ApiClient().previewTechnicianImpact(
        action: action,
        technicianId: technicianId,
        techRole: techRole,
        specialty: specialty,
        addMode: addMode,
        activeTime: activeTime,
      ),
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.blueGrey.shade50,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: Colors.blueGrey.shade100),
            ),
            child: const Row(
              children: [
                SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
                SizedBox(width: 10),
                Text('Calculating add/remove impact...'),
              ],
            ),
          );
        }
        if (snap.hasError) {
          return Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.red.shade50,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: Colors.red.shade100),
            ),
            child: Text('Impact preview unavailable: ${snap.error}',
                style: TextStyle(color: Colors.red.shade700, fontSize: 12)),
          );
        }
        final m = snap.data ?? <String, dynamic>{};
        final risk = (m['risk'] ?? 'WATCH').toString();
        final riskColor = _riskColor(risk);
        final isCallback = (m['role'] ?? '') == 'CALLBACK';
        final current = m['current_active'] ?? '-';
        final proposed = m['proposed_active'] ?? '-';
        final rec = m['recommended_active'] ?? '-';
        final projectedUtil = m['projected_utilization_pct'];
        final dutyUtil = m['projected_duty_utilization_pct'];
        final serviceUtil = m['projected_service_utilization_pct'];
        final sla = m['sla_pct'];
        final scopeLabel = (m['scope_label'] ?? '').toString();
        return Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: _riskBackground(risk),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: riskColor.withOpacity(0.25)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Icon(Icons.insights, color: riskColor, size: 18),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text('Impact preview',
                        style: TextStyle(fontWeight: FontWeight.w800, color: riskColor)),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: riskColor.withOpacity(0.12),
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Text((m['risk_label'] ?? risk).toString(),
                        style: TextStyle(color: riskColor, fontWeight: FontWeight.w800, fontSize: 11)),
                  ),
                ],
              ),
              if (scopeLabel.isNotEmpty) ...[
                const SizedBox(height: 4),
                Text('Scope: $scopeLabel', style: TextStyle(color: Colors.blueGrey.shade600, fontSize: 11)),
              ],
              const SizedBox(height: 10),
              GridView.count(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                crossAxisCount: 2,
                mainAxisSpacing: 8,
                crossAxisSpacing: 8,
                childAspectRatio: 2.7,
                children: [
                  _metric('Active technicians', '$current → $proposed'),
                  _metric('Recommended', '$rec'),
                  _metric(isCallback ? 'Duty utilization' : 'Utilization', _fmtPct(projectedUtil), valueColor: riskColor),
                  _metric(isCallback ? 'Service util.' : 'Avg load', _fmtPct(isCallback ? serviceUtil : projectedUtil)),
                  if (isCallback) _metric('SLA now', _fmtPct(sla)),
                  if (isCallback) _metric('AA / B', '${m['aa_count'] ?? 0} / ${m['b_count'] ?? 0}'),
                  if (!isCallback) _metric('Jobs', '${m['jobs'] ?? 0}'),
                  if (!isCallback) _metric('Days', '${m['scheduled_days'] ?? 0}'),
                ],
              ),
              if (action == 'ADD') ...[
                const SizedBox(height: 8),
                Container(
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: Colors.white.withOpacity(0.65),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: Colors.blueGrey.shade100),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Row(
                        children: [
                          Icon(addMode == 'BACKLOG' ? Icons.place : Icons.home_work_outlined, size: 16, color: Colors.blueGrey.shade700),
                          const SizedBox(width: 6),
                          Expanded(
                            child: Text(
                              (m['placement_note'] ?? '').toString(),
                              style: TextStyle(color: Colors.blueGrey.shade800, fontWeight: FontWeight.w600, fontSize: 12),
                            ),
                          ),
                        ],
                      ),
                      if (addMode == 'BACKLOG') ...[
                        const SizedBox(height: 6),
                        Wrap(spacing: 6, runSpacing: 6, children: [
                          Chip(
                            label: Text(isCallback
                                ? "Unassigned callbacks: ${m['unassigned_count'] ?? 0}"
                                : "Maintenance backlog: ${m['unassigned_count'] ?? 0}"),
                            visualDensity: VisualDensity.compact,
                          ),
                          if (isCallback) Chip(label: Text("AA: ${m['unassigned_aa_count'] ?? 0}"), visualDensity: VisualDensity.compact),
                          if (isCallback) Chip(label: Text("B: ${m['unassigned_b_count'] ?? 0}"), visualDensity: VisualDensity.compact),
                        ]),
                        _backlogTasksPreview(((m['unassigned_tasks'] as List?) ?? const []), isCallback: isCallback),
                      ],
                    ],
                  ),
                ),
              ],
              const SizedBox(height: 8),
              Text((m['optimal_text'] ?? '').toString(),
                  style: TextStyle(color: Colors.blueGrey.shade800, fontWeight: FontWeight.w600, fontSize: 12)),
              const SizedBox(height: 4),
              Text((isCallback ? m['sla_note'] : m['recommendation'] ?? '').toString(),
                  style: TextStyle(color: Colors.blueGrey.shade700, fontSize: 12)),
              const SizedBox(height: 4),
              Text('Preview only. Supervisor still chooses whether to apply the change.',
                  style: TextStyle(color: Colors.grey.shade600, fontSize: 11)),
            ],
          ),
        );
      },
    );
  }
}

class _TechniciansSidePanel extends StatefulWidget {
  final List<TechnicianState> technicians;
  final Color Function(TechnicianState) colorFor;
  final int? selectedTechId;
  final void Function(int id) onSelect;
  final VoidCallback? onChanged;
  final DateTime activeTime;
  const _TechniciansSidePanel({
    required this.technicians,
    required this.colorFor,
    required this.selectedTechId,
    required this.onSelect,
    required this.activeTime,
    this.onChanged,
  });

  @override
  State<_TechniciansSidePanel> createState() => _TechniciansSidePanelState();
}

class _TechniciansSidePanelState extends State<_TechniciansSidePanel> {
  String _query = '';
  String _roleFilter = 'ALL';      // ALL / MAINTENANCE / CALLBACK
  String _specFilter = 'ALL';      // ALL / ELEVATOR / ESCALATOR / BOTH (only under Maintenance)
  bool _busy = false;

  // --- group composition, derived from the actual technicians present -------
  bool get _hasMaintenance =>
      widget.technicians.any((t) => t.techRole == 'MAINTENANCE');
  bool get _hasCallback =>
      widget.technicians.any((t) => t.techRole == 'CALLBACK');
  bool get _isMixed => _hasMaintenance && _hasCallback;
  bool get _isMaintenanceOnly => _hasMaintenance && !_hasCallback;
  bool get _isCallbackOnly => _hasCallback && !_hasMaintenance;

  // Whether the Elevator/Escalator/Both sub-filter should be visible right now.
  //  - mixed group:        only when Maintenance is the active role
  //  - maintenance-only:   always (it's the main control)
  //  - callback-only:      never
  bool get _showSpecFilter {
    if (_isCallbackOnly) return false;
    if (_isMaintenanceOnly) return true;
    return _roleFilter == 'MAINTENANCE'; // mixed
  }

  List<TechnicianState> get _filtered {
    return widget.technicians.where((t) {
      final q = _query.trim().toLowerCase();
      final matchesQuery = q.isEmpty || t.name.toLowerCase().contains(q);
      final matchesRole = _roleFilter == 'ALL' || t.techRole == _roleFilter;
      // Specialty sub-filter only applies to maintenance technicians.
      // (Callback technicians always cover BOTH, so the sub-filter is ignored
      //  unless we're specifically looking at the Maintenance group.)
      final specApplies = _showSpecFilter && t.techRole == 'MAINTENANCE';
      final matchesSpec =
          !specApplies || _specFilter == 'ALL' || t.specialty == _specFilter;
      return matchesQuery && matchesRole && matchesSpec;
    }).toList();
  }

  Widget _filterChip(String label, String value, String group, void Function(String) onPick) {
    final selected = group == value;
    return Padding(
      padding: const EdgeInsets.only(right: 6),
      child: ChoiceChip(
        label: Text(label, style: TextStyle(
            fontSize: 11,
            color: selected ? Colors.white : Colors.blueGrey.shade700,
            fontWeight: FontWeight.w600)),
        selected: selected,
        showCheckmark: false,
        selectedColor: Colors.blue.shade700,
        backgroundColor: Colors.blueGrey.shade50,
        visualDensity: VisualDensity.compact,
        onSelected: (_) => onPick(value),
      ),
    );
  }

  TechnicianState? get _selectedVisibleTech {
    final selected = widget.selectedTechId;
    if (selected == null) return null;
    for (final t in _filtered) {
      if (t.id == selected) return t;
    }
    return null;
  }

  Future<void> _confirmRemoveSelectedTechnician(BuildContext context) async {
    final tech = _selectedVisibleTech;
    if (tech == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Select a technician first.')),
      );
      return;
    }

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Remove technician?'),
        content: SizedBox(
          width: 460,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  '${tech.name} will be removed from the active roster.\n\n'
                  'Their work history is kept for reports, and the schedule can be rebuilt '
                  'without deleting any historical data.',
                ),
                const SizedBox(height: 12),
                _ImpactPreviewBox(
                  key: ValueKey('remove-${tech.id}'),
                  action: 'REMOVE',
                  technicianId: tech.id,
                  activeTime: widget.activeTime,
                ),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton.icon(
            style: FilledButton.styleFrom(backgroundColor: Colors.red.shade600),
            onPressed: () => Navigator.pop(ctx, true),
            icon: const Icon(Icons.person_remove_alt_1, size: 18),
            label: const Text('Remove'),
          ),
        ],
      ),
    );
    if (ok != true) return;

    setState(() => _busy = true);
    try {
      final msg = await ApiClient().removeTechnician(tech.id);
      widget.onChanged?.call();
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
      }
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not remove technician: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _showAddTechnicianDialog(BuildContext context) async {
    final nameCtrl = TextEditingController();

    // Which roles can this supervisor add? Depends on their group type:
    //  - maintenance-only HQ -> can only add MAINTENANCE
    //  - callback-only HQ    -> can only add CALLBACK
    //  - mixed HQ            -> can add either
    final List<String> allowedRoles = _isMixed
        ? ['MAINTENANCE', 'CALLBACK']
        : (_isCallbackOnly ? ['CALLBACK'] : ['MAINTENANCE']);

    String role = allowedRoles.first;
    String spec = role == 'CALLBACK' ? 'BOTH' : 'ELEVATOR';
    String addMode = 'NORMAL'; // NORMAL / BACKLOG
    bool saving = false;
    String? err;

    String _nearBacklogLabel(String r) =>
        r == 'CALLBACK' ? 'Near callback backlog' : 'Near maintenance backlog';

    String _addModeHelp(String r, String mode) {
      if (mode != 'BACKLOG') {
        return 'Adds the technician at the normal supervisor group/base location.';
      }
      return r == 'CALLBACK'
          ? 'Adds the callback technician near current unassigned callback backlog. Use this when AA/B callbacks need nearby capacity.'
          : 'Adds the maintenance technician near current unassigned maintenance backlog. Use this when planned maintenance tasks need nearby capacity.';
    }

    await showDialog<void>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('Add Technician'),
          content: SizedBox(
            width: 480,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                const Text('Add mode', style: TextStyle(fontWeight: FontWeight.w600)),
                const SizedBox(height: 6),
                Wrap(spacing: 6, runSpacing: 6, children: [
                  ChoiceChip(
                    label: const Text('Normal add'),
                    selected: addMode == 'NORMAL',
                    onSelected: (_) => setLocal(() => addMode = 'NORMAL'),
                  ),
                  ChoiceChip(
                    label: Text(_nearBacklogLabel(role)),
                    selected: addMode == 'BACKLOG',
                    onSelected: (_) => setLocal(() => addMode = 'BACKLOG'),
                  ),
                ]),
                Padding(
                  padding: const EdgeInsets.only(top: 6, bottom: 12),
                  child: Text(
                    _addModeHelp(role, addMode),
                    style: TextStyle(color: Colors.blueGrey.shade600, fontSize: 12),
                  ),
                ),
                TextField(
                  controller: nameCtrl,
                  decoration: const InputDecoration(
                    labelText: 'Full name (e.g. Anıl Yıldırım)',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 14),
                const Text('Role', style: TextStyle(fontWeight: FontWeight.w600)),
                const SizedBox(height: 6),
                // Only roles valid for THIS group are offered. A single-role
                // group shows just its one role (no invalid choice possible).
                if (allowedRoles.length == 1)
                  Align(
                    alignment: Alignment.centerLeft,
                    child: Chip(
                      label: Text(allowedRoles.first[0] +
                          allowedRoles.first.substring(1).toLowerCase()),
                    ),
                  )
                else
                  Wrap(spacing: 6, children: [
                    for (final r in allowedRoles)
                      ChoiceChip(
                        label: Text(r[0] + r.substring(1).toLowerCase()),
                        selected: role == r,
                        onSelected: (_) => setLocal(() {
                          role = r;
                          // Callback technicians always cover BOTH specialties.
                          if (r == 'CALLBACK') spec = 'BOTH';
                        }),
                      ),
                  ]),
                const SizedBox(height: 14),
                const Text('Specialty', style: TextStyle(fontWeight: FontWeight.w600)),
                const SizedBox(height: 6),
                if (role == 'CALLBACK')
                  // locked: callbacks are always BOTH
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 4),
                    child: Text(
                      'Callback technicians automatically cover Both '
                      '(elevator + escalator).',
                      style: TextStyle(color: Colors.grey, fontSize: 12),
                    ),
                  )
                else
                  Wrap(spacing: 6, children: [
                    for (final s in ['ELEVATOR', 'ESCALATOR', 'BOTH'])
                      ChoiceChip(
                        label: Text(s[0] + s.substring(1).toLowerCase()),
                        selected: spec == s,
                        onSelected: (_) => setLocal(() => spec = s),
                      ),
                  ]),
                const SizedBox(height: 12),
                _ImpactPreviewBox(
                  key: ValueKey('add-$role-$spec-$addMode'),
                  action: 'ADD',
                  techRole: role,
                  specialty: spec,
                  addMode: addMode,
                  activeTime: widget.activeTime,
                ),
                if (err != null) ...[
                  const SizedBox(height: 10),
                  Text(err!, style: const TextStyle(color: Colors.red, fontSize: 12)),
                ],
              ],
            ),
          ),
          ),
          actions: [
            TextButton(
              onPressed: saving ? null : () => Navigator.pop(ctx),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: saving
                  ? null
                  : () async {
                      if (nameCtrl.text.trim().isEmpty) {
                        setLocal(() => err = 'Please enter a name.');
                        return;
                      }
                      setLocal(() { saving = true; err = null; });
                      try {
                        final msg = await ApiClient().addTechnician(
                          fullName: nameCtrl.text.trim(),
                          techRole: role,
                          specialty: spec,
                          addMode: addMode,
                          activeTime: widget.activeTime,
                        );
                        if (ctx.mounted) Navigator.pop(ctx);
                        widget.onChanged?.call();
                        if (context.mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(content: Text(msg)),
                          );
                        }
                      } catch (e) {
                        setLocal(() { saving = false; err = '$e'; });
                      }
                    },
              child: saving
                  ? const SizedBox(
                      width: 18, height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : Text(addMode == 'BACKLOG' ? 'Add near backlog' : 'Add'),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final list = _filtered;
    return _DashboardCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Icon(Icons.engineering, color: Colors.blue.shade800),
              const SizedBox(width: 8),
              const Text(
                'Active Technicians',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
              ),
              const Spacer(),
              if (_busy)
                const Padding(
                  padding: EdgeInsets.only(right: 6),
                  child: SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                ),
              IconButton(
                tooltip: 'Add technician',
                icon: Icon(Icons.person_add_alt_1, color: Colors.blue.shade800, size: 20),
                onPressed: _busy ? null : () => _showAddTechnicianDialog(context),
              ),
              IconButton(
                tooltip: _selectedVisibleTech == null
                    ? 'Select a technician to remove'
                    : 'Remove selected technician',
                icon: Icon(
                  Icons.person_remove_alt_1,
                  color: _selectedVisibleTech == null
                      ? Colors.grey.shade400
                      : Colors.red.shade500,
                  size: 20,
                ),
                onPressed: _busy || _selectedVisibleTech == null
                    ? null
                    : () => _confirmRemoveSelectedTechnician(context),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: Colors.blue.shade50,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  '${list.length}/${widget.technicians.length}',
                  style: TextStyle(
                    color: Colors.blue.shade800,
                    fontWeight: FontWeight.bold,
                    fontSize: 12,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          // search by name/surname
          TextField(
            onChanged: (v) => setState(() => _query = v),
            decoration: InputDecoration(
              isDense: true,
              hintText: 'Search by name…',
              prefixIcon: const Icon(Icons.search, size: 18),
              contentPadding: const EdgeInsets.symmetric(vertical: 8, horizontal: 8),
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
            ),
          ),
          const SizedBox(height: 10),
          // PRIMARY role filter (All / Maintenance / Callback) -- only useful
          // for a MIXED group. For single-role groups it's hidden entirely.
          if (_isMixed)
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(children: [
                _filterChip('All roles', 'ALL', _roleFilter, (v) => setState(() {
                      _roleFilter = v;
                      _specFilter = 'ALL';
                    })),
                _filterChip('Maintenance', 'MAINTENANCE', _roleFilter,
                    (v) => setState(() => _roleFilter = v)),
                _filterChip('Callback', 'CALLBACK', _roleFilter, (v) => setState(() {
                      _roleFilter = v;
                      _specFilter = 'ALL'; // callbacks always cover BOTH
                    })),
              ]),
            ),
          // SECONDARY sub-filter (Elevator/Escalator/Both) for maintenance techs.
          //  - maintenance-only group: always shown
          //  - mixed group: only when Maintenance is the active role
          //  - callback-only group: never
          if (_showSpecFilter) ...[
            if (_isMixed) const SizedBox(height: 6),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(children: [
                _filterChip('All types', 'ALL', _specFilter,
                    (v) => setState(() => _specFilter = v)),
                _filterChip('Elevator', 'ELEVATOR', _specFilter,
                    (v) => setState(() => _specFilter = v)),
                _filterChip('Escalator', 'ESCALATOR', _specFilter,
                    (v) => setState(() => _specFilter = v)),
                _filterChip('Both', 'BOTH', _specFilter,
                    (v) => setState(() => _specFilter = v)),
              ]),
            ),
          ],
          const SizedBox(height: 12),
          Expanded(
            child: list.isEmpty
                ? const Center(
                    child: Text(
                      'No technicians match.',
                      style: TextStyle(color: Colors.grey),
                    ),
                  )
                : ListView.separated(
                    itemCount: list.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (_, i) => _TechnicianTile(
                      tech: list[i],
                      color: widget.colorFor(list[i]),
                      isSelected: widget.selectedTechId == list[i].id,
                      anySelected: widget.selectedTechId != null,
                      onTap: () => widget.onSelect(list[i].id),
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}

class _TechnicianTile extends StatelessWidget {
  final TechnicianState tech;
  final Color color;
  final bool isSelected;
  final bool anySelected;
  final bool alwaysExpand; // for the dedicated Technicians tab: always show stops
  final VoidCallback? onTap;
  final VoidCallback? onRemove; // when set, shows a remove (soft-delete) button
  const _TechnicianTile({
    required this.tech,
    required this.color,
    this.isSelected = false,
    this.anySelected = false,
    this.alwaysExpand = false,
    this.onTap,
    this.onRemove,
  });

  String _stopStatusText(TechnicianStop s) {
    switch (s.state) {
      case 'done':
        return 'DONE';
      case 'current':
        return 'ON SITE';
      case 'on_route':
        return 'ON ROUTE';
      default:
        return 'ON PLAN';
    }
  }

  Color _stopStatusColor(TechnicianStop s) {
    switch (s.state) {
      case 'done':
        return Colors.green.shade700;
      case 'current':
        return Colors.blue.shade700;
      case 'on_route':
        return Colors.orange.shade800;
      default:
        return Colors.grey.shade600;
    }
  }

  IconData _stopStatusIcon(TechnicianStop s) {
    switch (s.state) {
      case 'done':
        return Icons.check;
      case 'current':
        return Icons.build_circle_outlined;
      case 'on_route':
        return Icons.near_me;
      default:
        return Icons.schedule;
    }
  }

  String _hm(DateTime? dt) {
    if (dt == null) return '';
    // The backend active clock is an operating/simulation clock. Do not call
    // toLocal(), otherwise Windows/Istanbul timezone adds +3 hours and the
    // row can say 16:46 while the backend correctly marks it DONE at 14:50.
    final h = dt.hour.toString().padLeft(2, '0');
    final m = dt.minute.toString().padLeft(2, '0');
    return '$h:$m';
  }

  @override
  Widget build(BuildContext context) {
    // On the Live Map side panel, expand stops only for the selected tech.
    // On the dedicated Technicians tab, alwaysExpand shows them all.
    final showStops = tech.stops.isNotEmpty && (isSelected || alwaysExpand);
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(10),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 8),
        decoration: BoxDecoration(
          color: isSelected ? color.withOpacity(0.08) : Colors.transparent,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(
            color: isSelected ? color.withOpacity(0.5) : Colors.transparent,
          ),
        ),
        child: Opacity(
          opacity: (anySelected && !isSelected) ? 0.55 : 1.0,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  CircleAvatar(
                    radius: 20,
                    backgroundColor: color.withOpacity(0.18),
                    child: Text(
                      tech.name.isNotEmpty ? tech.name[0] : '?',
                      style:
                          TextStyle(color: color, fontWeight: FontWeight.bold),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          tech.name,
                          style: const TextStyle(
                            fontWeight: FontWeight.bold,
                            fontSize: 14,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          '${tech.techRole} • ${tech.specialty}',
                          style:
                              TextStyle(color: Colors.grey[600], fontSize: 12),
                        ),
                      ],
                    ),
                  ),
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: tech.onLeave
                          ? Colors.orange.withOpacity(0.18)
                          : color.withOpacity(0.12),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Text(
                      tech.onLeave
                          ? 'On Leave'
                          : '${tech.stops.length} stop${tech.stops.length == 1 ? "" : "s"}',
                      style: TextStyle(
                        color: tech.onLeave ? Colors.orange.shade900 : color,
                        fontSize: 10,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                  if (onRemove != null)
                    IconButton(
                      tooltip: 'Remove technician',
                      icon: Icon(Icons.person_remove_alt_1,
                          size: 18, color: Colors.red.shade400),
                      onPressed: onRemove,
                    ),
                ],
              ),
              if (showStops) ...[
                const SizedBox(height: 8),
                for (final s in tech.stops)
                  Padding(
                    padding: const EdgeInsets.only(left: 52, top: 2),
                    child: Row(
                      children: [
                        Container(
                          width: 18,
                          height: 18,
                          alignment: Alignment.center,
                          decoration: BoxDecoration(
                            color: color,
                            shape: BoxShape.circle,
                            border: Border.all(
                              color: s.priority == 'AA'
                                  ? Colors.yellow
                                  : Colors.transparent,
                              width: 2,
                            ),
                          ),
                          child: Text(
                            '${s.stopNumber}',
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 10,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                s.unitName,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(
                                  fontSize: 12,
                                  decoration: s.state == 'done'
                                      ? TextDecoration.lineThrough
                                      : TextDecoration.none,
                                  color: s.state == 'done'
                                      ? Colors.grey.shade600
                                      : Colors.grey.shade900,
                                ),
                              ),
                              if (s.scheduledStart != null && s.scheduledEnd != null)
                                Text(
                                  '${_hm(s.scheduledStart)}–${_hm(s.scheduledEnd)}',
                                  style: TextStyle(
                                    fontSize: 10,
                                    color: Colors.grey.shade500,
                                  ),
                                ),
                            ],
                          ),
                        ),
                        const SizedBox(width: 6),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
                          decoration: BoxDecoration(
                            color: _stopStatusColor(s).withOpacity(0.12),
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(color: _stopStatusColor(s).withOpacity(0.35)),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(_stopStatusIcon(s), size: 11, color: _stopStatusColor(s)),
                              const SizedBox(width: 3),
                              Text(
                                _stopStatusText(s),
                                style: TextStyle(
                                  color: _stopStatusColor(s),
                                  fontSize: 9,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            ],
                          ),
                        ),
                        if (s.priority == 'AA') ...[
                          const SizedBox(width: 4),
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 6, vertical: 2),
                            decoration: BoxDecoration(
                              color: Colors.red.shade700,
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: const Text(
                              'AA',
                              style: TextStyle(
                                color: Colors.white,
                                fontSize: 9,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
              ] else if (tech.stops.isNotEmpty && !anySelected) ...[
                const SizedBox(height: 6),
                Padding(
                  padding: const EdgeInsets.only(left: 52),
                  child: Text(
                    'Tap to see route',
                    style: TextStyle(color: Colors.grey[500], fontSize: 11),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

// =============================================================================
//  Technicians view
// =============================================================================

class TechniciansView extends StatefulWidget {
  final DashboardState state;
  final VoidCallback? onChanged;
  const TechniciansView({super.key, required this.state, this.onChanged});

  @override
  State<TechniciansView> createState() => _TechniciansViewState();
}

class _TechniciansViewState extends State<TechniciansView> {
  bool _busy = false;

  Future<void> _confirmRemove(TechnicianState tech) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Remove technician?'),
        content: Text(
          '${tech.name} will be removed from the active roster.\n\n'
          'Their work history is kept (for reports), and you can reactivate '
          'them later. This does not delete any data.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Colors.red.shade600),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (ok != true) return;

    setState(() => _busy = true);
    try {
      final msg = await ApiClient().removeTechnician(tech.id);
      widget.onChanged?.call();
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(msg)));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not remove: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    return _DashboardCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Icon(Icons.engineering, color: Colors.blue.shade800),
              const SizedBox(width: 8),
              const Text(
                'All Technicians',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
              const Spacer(),
              if (_busy)
                const Padding(
                  padding: EdgeInsets.only(right: 10),
                  child: SizedBox(
                      height: 16,
                      width: 16,
                      child: CircularProgressIndicator(strokeWidth: 2)),
                ),
              Text(
                '${state.technicians.length} active',
                style: TextStyle(color: Colors.grey[600], fontSize: 13),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Expanded(
            child: state.technicians.isEmpty
                ? const Center(child: Text('No technicians', style: TextStyle(color: Colors.grey)))
                : ListView.separated(
                    itemCount: state.technicians.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (_, i) => _TechnicianTile(
                      tech: state.technicians[i],
                      color: Colors.blue.shade800,
                      alwaysExpand: true,
                      onRemove: () => _confirmRemove(state.technicians[i]),
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}

// =============================================================================
//  Shared
// =============================================================================

// =============================================================================
//  Monthly Report view  — per-technician: days, buildings, hours, intervals
// =============================================================================

// =============================================================================
//  Reusable sort control: a "Sort by <field>" dropdown + asc/desc toggle.
//  Used by the report / overview / history tabs to drive server-side sorting.
// =============================================================================
class _SortControls extends StatelessWidget {
  final Map<String, String> options; // value -> label
  final String sort;
  final String order; // 'asc' | 'desc'
  final ValueChanged<String> onSort;
  final ValueChanged<String> onOrder;
  const _SortControls({
    required this.options,
    required this.sort,
    required this.order,
    required this.onSort,
    required this.onOrder,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Text('Sort', style: TextStyle(color: Colors.grey, fontSize: 12)),
        const SizedBox(width: 6),
        DropdownButton<String>(
          value: options.containsKey(sort) ? sort : options.keys.first,
          underline: const SizedBox.shrink(),
          items: options.entries
              .map((e) => DropdownMenuItem(value: e.key, child: Text(e.value)))
              .toList(),
          onChanged: (v) { if (v != null) onSort(v); },
        ),
        IconButton(
          tooltip: order == 'asc' ? 'Ascending' : 'Descending',
          visualDensity: VisualDensity.compact,
          icon: Icon(order == 'asc' ? Icons.arrow_upward : Icons.arrow_downward,
              size: 18),
          onPressed: () => onOrder(order == 'asc' ? 'desc' : 'asc'),
        ),
      ],
    );
  }
}

class MonthlyReportView extends StatefulWidget {
  final DateTime activeDate;   // operating-clock day; top report is clamped here
  final bool fullSchedule;     // true = whole generated plan for selected month
  const MonthlyReportView({super.key, required this.activeDate, this.fullSchedule = false});

  @override
  State<MonthlyReportView> createState() => _MonthlyReportViewState();
}

class _MonthlyReportViewState extends State<MonthlyReportView> {
  final ApiClient _api = ApiClient();
  List<Map<String, dynamic>> _months = [];
  Map<String, dynamic>? _selectedMonth;
  Map<String, dynamic>? _report;
  bool _loading = true;
  bool _exporting = false;
  String? _error;
  int? _expandedTechId;
  String _sort = 'name';
  String _order = 'asc';
  final TextEditingController _searchCtrl = TextEditingController();
  String _search = '';

  @override
  void initState() {
    super.initState();
    _loadMonths();
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadMonths() async {
    setState(() { _loading = true; _error = null; });
    try {
      final months = await _api.fetchReportMonths(
          asOf: widget.fullSchedule ? kFullAsOf : '');
      if (widget.fullSchedule) {
        _months = months;
      } else {
        final ad = widget.activeDate;
        _months = months.where((m) {
          final y = (m['year'] as num).toInt();
          final mo = (m['month'] as num).toInt();
          return y < ad.year || (y == ad.year && mo <= ad.month);
        }).toList();
      }
      if (_months.isNotEmpty) {
        _selectedMonth = _months.last;
        await _loadReport();
      } else {
        setState(() => _loading = false);
      }
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  Future<void> _loadReport() async {
    if (_selectedMonth == null) return;
    setState(() { _loading = true; _error = null; });
    try {
      final rep = await _api.fetchMonthlyReport(
          _selectedMonth!['year'], _selectedMonth!['month'],
          asOf: widget.fullSchedule ? kFullAsOf : '',
          sort: _sort, order: _order, search: _search);
      setState(() { _report = rep; _loading = false; });
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  Future<void> _export() async {
    if (_selectedMonth == null) return;
    setState(() => _exporting = true);
    try {
      final r = await http.get(
        Uri.parse(_api.exportUrl(
            _selectedMonth!['year'], _selectedMonth!['month'],
            asOf: widget.fullSchedule ? kFullAsOf : '',
            sort: _sort, order: _order, search: _search)),
        headers: {'Authorization': 'Token $kSupervisorToken'},
      );
      if (r.statusCode != 200) {
        throw Exception('Export failed: ${r.statusCode}');
      }
      final blob = html.Blob([r.bodyBytes],
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
      final url = html.Url.createObjectUrlFromBlob(blob);
      final label = (_selectedMonth!['label'] ?? 'report')
          .toString()
          .replaceAll(' ', '_');
      final prefix = widget.fullSchedule ? 'full_report' : 'roll_report';
      html.AnchorElement(href: url)
        ..setAttribute('download', '${prefix}_$label.xlsx')
        ..click();
      html.Url.revokeObjectUrl(url);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Export error: $e')));
      }
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  double _toDouble(dynamic v) {
    if (v is num) return v.toDouble();
    return double.tryParse('$v') ?? 0.0;
  }

  int _toInt(dynamic v) {
    if (v is num) return v.toInt();
    return int.tryParse('$v') ?? 0;
  }

  String _fmt1(dynamic v) => _toDouble(v).toStringAsFixed(1);
  String _fmt0(dynamic v) => _toDouble(v).round().toString();

  Map<String, dynamic> _computedSummary(List techs) {
    final apiSummary = _report?['summary'];
    if (apiSummary is Map) return Map<String, dynamic>.from(apiSummary);

    final unitCodes = <String>{};
    final dates = <String>{};
    var jobs = 0;
    var hours = 0.0;
    var travelMin = 0.0;
    var routeKm = 0.0;
    var techDays = 0;
    var slaMet = 0;
    var slaTotal = 0;
    var aa = 0;
    var b = 0;

    for (final tRaw in techs) {
      final t = Map<String, dynamic>.from(tRaw as Map);
      hours += _toDouble(t['total_hours']);
      routeKm += _toDouble(t['route_km']);
      travelMin += _toDouble(t['travel_minutes']);
      techDays += _toInt(t['days_worked']);
      slaMet += _toInt(t['sla_met']);
      slaTotal += _toInt(t['sla_total']);
      aa += _toInt(t['aa_count']);
      b += _toInt(t['b_count']);
      final days = ((t['days'] as List?) ?? []);
      for (final dRaw in days) {
        final d = Map<String, dynamic>.from(dRaw as Map);
        dates.add('${d['date']}');
        final visits = ((d['visits'] as List?) ?? []);
        jobs += visits.length;
        for (final vRaw in visits) {
          final v = Map<String, dynamic>.from(vRaw as Map);
          final code = v['unit_code'];
          if (code != null) unitCodes.add('$code');
        }
      }
    }
    final avgDay = techDays == 0 ? 0.0 : hours / techDays;
    return {
      'technician_count': techs.length,
      'jobs': jobs,
      'units': unitCodes.length,
      'hours': double.parse(hours.toStringAsFixed(1)),
      'avg_day_hours': double.parse(avgDay.toStringAsFixed(1)),
      'utilization_pct': double.parse(((avgDay / 8.0) * 100).toStringAsFixed(1)),
      'route_km': double.parse(routeKm.toStringAsFixed(1)),
      'travel_hours': double.parse((travelMin / 60).toStringAsFixed(1)),
      'sla_met': slaMet,
      'sla_total': slaTotal,
      'aa_count': aa,
      'b_count': b,
      'scheduled_days': dates.length,
    };
  }

  String _scopeText() {
    final monthLabel = _selectedMonth?['label']?.toString() ?? '';
    if (widget.fullSchedule) {
      return 'Full generated schedule for $monthLabel. This ignores the roll-date clamp and is used for final / all-period reporting.';
    }
    final d = DateFormat('yyyy-MM-dd').format(widget.activeDate);
    return 'Roll-date report for $monthLabel. Shows generated work from the selected month start up to $d only.';
  }

  String _titleText() => widget.fullSchedule ? 'Full Schedule Report' : 'Roll-Date Report';

  String _jobsHeader(Map<String, dynamic> summary) {
    final slaTotal = _toInt(summary['sla_total']);
    return slaTotal > 0 ? 'Callbacks' : 'Jobs';
  }

  Color _utilColor(double pct) {
    if (pct < 60) return Colors.red.shade600;
    if (pct < 80) return Colors.orange.shade700;
    if (pct <= 105) return Colors.green.shade700;
    return Colors.deepOrange.shade700;
  }

  Widget _metricCard({
    required String label,
    required String value,
    IconData icon = Icons.analytics_outlined,
    Color? color,
    String? subtitle,
  }) {
    final c = color ?? Colors.blue.shade800;
    return Expanded(
      child: Container(
        constraints: const BoxConstraints(minHeight: 82),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: c.withOpacity(0.08),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: c.withOpacity(0.18)),
        ),
        child: Row(
          children: [
            Container(
              width: 36,
              height: 36,
              decoration: BoxDecoration(
                color: c.withOpacity(0.14),
                shape: BoxShape.circle,
              ),
              child: Icon(icon, color: c, size: 19),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(label, maxLines: 1, overflow: TextOverflow.ellipsis,
                      style: TextStyle(color: Colors.grey.shade700, fontSize: 11)),
                  const SizedBox(height: 2),
                  Text(value, maxLines: 1, overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
                  if (subtitle != null) ...[
                    const SizedBox(height: 2),
                    Text(subtitle, maxLines: 1, overflow: TextOverflow.ellipsis,
                        style: TextStyle(color: Colors.grey.shade600, fontSize: 10)),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return _DashboardCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Icon(Icons.assessment, color: Colors.blue.shade800),
              const SizedBox(width: 8),
              Text(_titleText(),
                  style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(width: 12),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: widget.fullSchedule ? Colors.indigo.shade50 : Colors.green.shade50,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(widget.fullSchedule ? 'FULL PLAN' : 'TO ROLL DATE',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w800,
                      color: widget.fullSchedule ? Colors.indigo.shade700 : Colors.green.shade700,
                    )),
              ),
              const SizedBox(width: 16),
              SizedBox(
                width: 200,
                child: TextField(
                  controller: _searchCtrl,
                  decoration: const InputDecoration(
                    hintText: 'Search technician…',
                    isDense: true,
                    prefixIcon: Icon(Icons.search, size: 18),
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: (v) { _search = v.trim(); _loadReport(); },
                ),
              ),
              const Spacer(),
              _SortControls(
                options: const {
                  'name': 'Name',
                  'hours': 'Hours',
                  'jobs': 'Jobs',
                  'days': 'Days',
                  'utilization': 'Utilization',
                  'route_km': 'Route KM',
                  'sla': 'SLA',
                },
                sort: _sort,
                order: _order,
                onSort: (v) {
                  setState(() {
                    _sort = v;
                    _order = v == 'name' ? 'asc' : 'desc';
                  });
                  _loadReport();
                },
                onOrder: (v) { setState(() => _order = v); _loadReport(); },
              ),
              const SizedBox(width: 12),
              if (_months.isNotEmpty)
                DropdownButton<Map<String, dynamic>>(
                  value: _selectedMonth,
                  items: _months
                      .map((m) => DropdownMenuItem(
                            value: m,
                            child: Text(m['label'].toString()),
                          ))
                      .toList(),
                  onChanged: (m) {
                    setState(() { _selectedMonth = m; _expandedTechId = null; });
                    _loadReport();
                  },
                ),
              const SizedBox(width: 12),
              FilledButton.icon(
                onPressed: (_report == null || _exporting) ? null : _export,
                icon: _exporting
                    ? const SizedBox(
                        height: 16, width: 16,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white))
                    : const Icon(Icons.download, size: 18),
                label: const Text('Export Excel'),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(_scopeText(), style: TextStyle(color: Colors.grey.shade700, fontSize: 12)),
          const SizedBox(height: 12),
          Expanded(child: _buildBody()),
        ],
      ),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return Center(child: Text('Error: $_error',
          style: const TextStyle(color: Colors.red)));
    }
    if (_months.isEmpty) {
      return const Center(
        child: Text('No schedule data yet. Run a schedule generation first.',
            style: TextStyle(color: Colors.grey)),
      );
    }
    final techs = ((_report?['technicians'] as List?) ?? []);
    if (techs.isEmpty) {
      return const Center(
        child: Text('No activity for this report scope.',
            style: TextStyle(color: Colors.grey)),
      );
    }
    final summary = _computedSummary(techs);
    final util = _toDouble(summary['utilization_pct']);
    final hasSla = _toInt(summary['sla_total']) > 0;
    return ListView(
      children: [
        Row(
          children: [
            _metricCard(label: 'Technicians', value: '${summary['technician_count']}',
                icon: Icons.engineering_outlined, subtitle: 'with scheduled work'),
            const SizedBox(width: 10),
            _metricCard(label: _jobsHeader(summary), value: '${summary['jobs']}',
                icon: hasSla ? Icons.report_problem_outlined : Icons.apartment_outlined,
                subtitle: hasSla ? 'AA ${summary['aa_count']} · B ${summary['b_count']}' : '${summary['units']} unique units'),
            const SizedBox(width: 10),
            _metricCard(label: 'Hours', value: '${_fmt1(summary['hours'])} h',
                icon: Icons.timer_outlined, subtitle: '${summary['scheduled_days']} scheduled days'),
            const SizedBox(width: 10),
            _metricCard(label: 'Avg / Day', value: '${_fmt1(summary['avg_day_hours'])} h',
                icon: Icons.today_outlined, subtitle: 'per worked tech-day'),
          ],
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            _metricCard(label: 'Utilization', value: '${_fmt1(util)}%',
                icon: Icons.speed_outlined, color: _utilColor(util),
                subtitle: '8h/day target base'),
            const SizedBox(width: 10),
            _metricCard(label: 'Route KM', value: '${_fmt1(summary['route_km'])} km',
                icon: Icons.route_outlined, subtitle: 'cached/google route data'),
            const SizedBox(width: 10),
            _metricCard(label: 'Travel Time', value: '${_fmt1(summary['travel_hours'])} h',
                icon: Icons.directions_car_outlined, subtitle: 'between scheduled stops'),
            const SizedBox(width: 10),
            _metricCard(
              label: hasSla ? 'SLA Success' : 'Balance Signal',
              value: hasSla
                  ? '${_fmt1((_toInt(summary['sla_total']) == 0 ? 0 : (_toInt(summary['sla_met']) / _toInt(summary['sla_total']) * 100)))}%'
                  : (util < 60 ? 'Underused' : util > 105 ? 'Overloaded' : 'Balanced'),
              icon: hasSla ? Icons.verified_outlined : Icons.balance_outlined,
              color: hasSla
                  ? ((_toInt(summary['sla_total']) == 0 || (_toInt(summary['sla_met']) / _toInt(summary['sla_total']) >= 0.9))
                      ? Colors.green.shade700 : Colors.red.shade600)
                  : _utilColor(util),
              subtitle: hasSla ? '${summary['sla_met']}/${summary['sla_total']} inside window' : 'based on avg/day',
            ),
          ],
        ),
        const SizedBox(height: 16),
        Container(
          padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
          color: Colors.grey.shade100,
          child: Row(
            children: [
              const Expanded(flex: 3, child: Text('Technician',
                  style: TextStyle(fontWeight: FontWeight.bold))),
              const Expanded(child: Text('Days',
                  style: TextStyle(fontWeight: FontWeight.bold))),
              Expanded(child: Text(_jobsHeader(summary),
                  style: const TextStyle(fontWeight: FontWeight.bold))),
              const Expanded(child: Text('Hours',
                  style: TextStyle(fontWeight: FontWeight.bold))),
              const Expanded(child: Text('Avg/Day',
                  style: TextStyle(fontWeight: FontWeight.bold))),
              const Expanded(child: Text('Route KM',
                  style: TextStyle(fontWeight: FontWeight.bold))),
              const Expanded(child: Text('Util.',
                  style: TextStyle(fontWeight: FontWeight.bold))),
              if (hasSla)
                const Expanded(child: Text('SLA',
                    style: TextStyle(fontWeight: FontWeight.bold))),
              const SizedBox(width: 24),
            ],
          ),
        ),
        for (final t in techs) _techRow(Map<String, dynamic>.from(t as Map), hasSla),
      ],
    );
  }

  Widget _utilPill(double pct) {
    final c = _utilColor(pct);
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(
          color: c.withOpacity(0.12),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: c.withOpacity(0.25)),
        ),
        child: Text('${pct.toStringAsFixed(0)}%',
            style: TextStyle(color: c, fontSize: 11, fontWeight: FontWeight.bold)),
      ),
    );
  }

  Widget _techRow(Map<String, dynamic> t, bool hasSla) {
    final expanded = _expandedTechId == t['id'];
    final days = _toInt(t['days_worked']);
    final hours = _toDouble(t['total_hours']);
    final avgDay = _toDouble(t['avg_day_hours'] ?? (days == 0 ? 0 : hours / days));
    final util = _toDouble(t['utilization_pct'] ?? ((avgDay / 8.0) * 100));
    final role = (t['role'] ?? t['tech_role'] ?? '').toString();
    final spec = (t['specialty'] ?? '').toString();
    final jobs = t['jobs'] ?? t['buildings_visited'];
    final routeKm = _toDouble(t['route_km']);
    final slaTotal = _toInt(t['sla_total']);
    final slaMet = _toInt(t['sla_met']);
    final slaPct = slaTotal == 0 ? 0.0 : (slaMet / slaTotal * 100);

    return Column(
      children: [
        InkWell(
          onTap: () => setState(
              () => _expandedTechId = expanded ? null : t['id'] as int),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 12),
            child: Row(
              children: [
                Expanded(flex: 3, child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(t['name'].toString(),
                        style: const TextStyle(fontWeight: FontWeight.w600)),
                    if (role.isNotEmpty || spec.isNotEmpty)
                      Text([role, spec].where((x) => x.isNotEmpty).join(' · '),
                          style: TextStyle(color: Colors.grey.shade600, fontSize: 11)),
                  ],
                )),
                Expanded(child: Text('$days')),
                Expanded(child: Text('$jobs')),
                Expanded(child: Text('${hours.toStringAsFixed(1)} h')),
                Expanded(child: Text('${avgDay.toStringAsFixed(1)} h')),
                Expanded(child: Text(routeKm == 0 ? '—' : '${routeKm.toStringAsFixed(1)}')),
                Expanded(child: _utilPill(util)),
                if (hasSla)
                  Expanded(child: Text(slaTotal == 0 ? '—' : '${slaPct.toStringAsFixed(0)}%')),
                Icon(expanded ? Icons.expand_less : Icons.expand_more,
                    size: 20, color: Colors.grey),
              ],
            ),
          ),
        ),
        if (expanded) _techDetail(t),
        const Divider(height: 1),
      ],
    );
  }

  Widget _techDetail(Map<String, dynamic> t) {
    final days = ((t['days'] as List?) ?? []);
    return Container(
      color: Colors.blue.shade50.withOpacity(0.3),
      padding: const EdgeInsets.fromLTRB(24, 8, 12, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Scheduled work detail. This report does not mark DONE / ON ROUTE; live status belongs to Live Map and Monthly Log after execution.',
              style: TextStyle(color: Colors.grey.shade700, fontSize: 12)),
          const SizedBox(height: 8),
          for (final dRaw in days)
            _dayBlock(Map<String, dynamic>.from(dRaw as Map)),
        ],
      ),
    );
  }

  Widget _dayBlock(Map<String, dynamic> day) {
    final visits = ((day['visits'] as List?) ?? []);
    final routeKm = _toDouble(day['route_km']);
    final travelMin = _toDouble(day['travel_minutes']);
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(day['date'].toString(),
                  style: const TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(width: 10),
              Text('${day['buildings']} jobs · '
                  '${(_toDouble(day['work_minutes']) / 60).toStringAsFixed(1)} h service · '
                  '${(travelMin / 60).toStringAsFixed(1)} h travel · '
                  '${routeKm.toStringAsFixed(1)} km · '
                  'window ${day['window']}',
                  style: TextStyle(color: Colors.grey.shade700, fontSize: 12)),
            ],
          ),
          const SizedBox(height: 4),
          for (final vRaw in visits)
            _visitRow(Map<String, dynamic>.from(vRaw as Map)),
        ],
      ),
    );
  }

  Widget _visitRow(Map<String, dynamic> v) {
    final op = (v['operation_type'] ?? '').toString();
    final priority = (v['priority'] ?? '').toString();
    final label = priority.isNotEmpty
        ? priority
        : ((v['maintenance_type'] ?? op).toString().isNotEmpty
            ? (v['maintenance_type'] ?? op).toString()
            : '?');
    return Padding(
      padding: const EdgeInsets.only(left: 12, top: 2),
      child: Row(
        children: [
          SizedBox(
            width: 110,
            child: Text('${v['start']}–${v['end'] ?? '—'}',
                style: const TextStyle(fontSize: 12, color: Colors.black87)),
          ),
          Container(
            margin: const EdgeInsets.only(right: 8),
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
            decoration: BoxDecoration(
              color: priority.isNotEmpty ? _priorityColor(priority) : _typeColor(v['maintenance_type']),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(label,
                style: const TextStyle(
                    color: Colors.white, fontSize: 10,
                    fontWeight: FontWeight.bold)),
          ),
          Expanded(
            child: Text(v['building'].toString(),
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 12)),
          ),
          Text('${v['minutes']}m',
              style: TextStyle(color: Colors.grey.shade600, fontSize: 11)),
          const SizedBox(width: 8),
          Text('${_fmt1(v['route_km'])} km',
              style: TextStyle(color: Colors.grey.shade600, fontSize: 11)),
        ],
      ),
    );
  }

  Color _priorityColor(String p) {
    switch (p) {
      case 'AA': return Colors.red.shade700;
      case 'A': return Colors.deepOrange.shade600;
      case 'B': return Colors.orange.shade700;
      case 'C': return Colors.blueGrey.shade600;
      default: return Colors.grey;
    }
  }

  Color _typeColor(dynamic t) {
    switch (t) {
      case 'A': return Colors.red.shade600;
      case 'B': return Colors.orange.shade700;
      case 'C': return Colors.green.shade600;
      default: return Colors.grey;
    }
  }
}


// =============================================================================
//  Unit History view — risk-aware unit health + backlog history
// =============================================================================

class UnitHistoryView extends StatefulWidget {
  final bool fullSchedule;
  const UnitHistoryView({super.key, this.fullSchedule = false});

  @override
  State<UnitHistoryView> createState() => _UnitHistoryViewState();
}

class _UnitHistoryViewState extends State<UnitHistoryView> {
  final ApiClient _api = ApiClient();
  final TextEditingController _searchCtrl = TextEditingController();
  Map<String, dynamic>? _summary;
  bool _loading = true;
  bool _exporting = false;
  String? _error;
  int _page = 1;
  String _search = '';
  String _sort = 'status';
  String _order = 'asc';
  String _status = 'all';

  int? _openUnitId;
  Map<String, dynamic>? _detail;
  bool _detailLoading = false;

  String get _asOf => widget.fullSchedule ? kFullAsOf : '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final s = await _api.fetchUnitHistorySummary(
        search: _search,
        page: _page,
        pageSize: 50,
        asOf: _asOf,
        sort: _sort,
        order: _order,
        status: _status,
      );
      setState(() { _summary = s; _loading = false; });
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  Future<void> _openUnit(int unitId) async {
    if (_openUnitId == unitId) {
      setState(() { _openUnitId = null; _detail = null; });
      return;
    }
    setState(() { _openUnitId = unitId; _detailLoading = true; _detail = null; });
    try {
      final d = await _api.fetchUnitHistoryDetail(unitId, asOf: _asOf);
      setState(() { _detail = d; _detailLoading = false; });
    } catch (e) {
      setState(() { _detailLoading = false; });
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Detail error: $e')));
      }
    }
  }

  Future<void> _export() async {
    setState(() => _exporting = true);
    try {
      final r = await http.get(
        Uri.parse(_api.unitHistoryExportUrl(
          asOf: _asOf,
          sort: _sort,
          order: _order,
          search: _search,
          status: _status,
        )),
        headers: {'Authorization': 'Token $kSupervisorToken'},
      );
      if (r.statusCode != 200) throw Exception('Export failed: ${r.statusCode}');
      final blob = html.Blob([r.bodyBytes],
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
      final url = html.Url.createObjectUrlFromBlob(blob);
      html.AnchorElement(href: url)
        ..setAttribute('download', 'unit_history_enhanced.xlsx')
        ..click();
      html.Url.revokeObjectUrl(url);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Export error: $e')));
      }
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  bool get _isCallback => (_summary?['group_type'] ?? '') == 'CALLBACK';
  Map<String, dynamic> get _metrics =>
      Map<String, dynamic>.from((_summary?['summary'] as Map?) ?? const {});

  String _n(dynamic v) => v == null ? '0' : '$v';
  String _pct(dynamic v) => v == null ? 'N/A' : '${v}%';

  @override
  Widget build(BuildContext context) {
    final units = ((_summary?['units'] as List?) ?? []);
    final total = _summary?['total_units'] ?? 0;
    final gtype = _summary?['group_type'] ?? '';
    final scope = _summary?['as_of'] ?? (widget.fullSchedule ? 'all' : 'roll date');
    return _DashboardCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _header(gtype, scope),
          const SizedBox(height: 12),
          if (!_loading && _error == null) _summaryCards(),
          const SizedBox(height: 12),
          if (!_loading && _error == null) _filterRow(),
          const SizedBox(height: 12),
          Expanded(child: _buildBody(units)),
          if (!_loading && _error == null) _pager(total),
        ],
      ),
    );
  }

  Widget _header(dynamic gtype, dynamic scope) {
    return Row(
      children: [
        Icon(Icons.apartment, color: Colors.blue.shade800),
        const SizedBox(width: 8),
        Text(widget.fullSchedule ? 'Full · Unit History' : 'Unit History',
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
        const SizedBox(width: 10),
        _softBadge('$gtype', Colors.blue),
        const SizedBox(width: 8),
        _softBadge(widget.fullSchedule ? 'Full generated schedule' : 'Roll-date scope: $scope', Colors.indigo),
        const Spacer(),
        SizedBox(
          width: 240,
          child: TextField(
            controller: _searchCtrl,
            decoration: const InputDecoration(
              hintText: 'Search unit name/code…',
              isDense: true,
              prefixIcon: Icon(Icons.search, size: 18),
              border: OutlineInputBorder(),
            ),
            onSubmitted: (v) {
              _search = v.trim();
              _page = 1;
              _load();
            },
          ),
        ),
        const SizedBox(width: 12),
        _SortControls(
          options: const {
            'status': 'Risk',
            'last_service': 'Last Service',
            'next_service': 'Next Service',
            'name': 'Name',
            'maint': 'Maintenance',
            'callback': 'Callbacks',
            'unassigned': 'Backlog',
            'sla': 'SLA',
          },
          sort: _sort,
          order: _order,
          onSort: (v) {
            setState(() {
              _sort = v;
              _order = v == 'name' ? 'asc' : 'desc';
              if (v == 'status') _order = 'asc';
              _page = 1;
            });
            _load();
          },
          onOrder: (v) { setState(() => _order = v); _load(); },
        ),
        const SizedBox(width: 12),
        FilledButton.icon(
          onPressed: _exporting ? null : _export,
          icon: _exporting
              ? const SizedBox(height: 16, width: 16,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Icon(Icons.download, size: 18),
          label: const Text('Export Excel'),
        ),
      ],
    );
  }

  Widget _summaryCards() {
    final m = _metrics;
    final cards = _isCallback
        ? [
            ['Units', _n(m['units']), Icons.apartment, Colors.blue],
            ['Callback incidents', _n((m['aa_count'] ?? 0) + (m['b_count'] ?? 0)), Icons.report_problem, Colors.purple],
            ['AA / B', '${_n(m['aa_count'])} / ${_n(m['b_count'])}', Icons.priority_high, Colors.red],
            ['Repeat callback units', _n(m['repeat_callback_units']), Icons.repeat, Colors.orange],
            ['Unassigned callbacks', _n(m['unassigned']), Icons.assignment_late, Colors.red],
            ['AA backlog', _n(m['aa_unassigned']), Icons.warning_amber, Colors.red],
          ]
        : [
            ['Units', _n(m['units']), Icons.apartment, Colors.blue],
            ['Serviced units', _n(m['serviced_units']), Icons.check_circle, Colors.green],
            ['Due soon', _n(m['due_soon']), Icons.schedule, Colors.orange],
            ['Overdue', _n(m['overdue']), Icons.error_outline, Colors.red],
            ['Maintenance backlog', _n(m['unassigned']), Icons.assignment_late, Colors.red],
            ['Risk units', '${(m['due_soon'] ?? 0) + (m['overdue'] ?? 0) + (m['unassigned'] ?? 0)}', Icons.analytics, Colors.indigo],
          ];
    return LayoutBuilder(builder: (context, c) {
      final width = (c.maxWidth - 50) / 6;
      return Wrap(
        spacing: 10,
        runSpacing: 10,
        children: [
          for (final card in cards)
            SizedBox(
              width: width < 150 ? 150 : width,
              child: _unitMetricCard(
                label: card[0] as String,
                value: card[1] as String,
                icon: card[2] as IconData,
                color: card[3] as Color,
              ),
            ),
        ],
      );
    });
  }

  Widget _filterRow() {
    final filters = _isCallback
        ? const {
            'all': 'All',
            'risk': 'Risk only',
            'unassigned': 'Backlog',
            'sla_risk': 'SLA risk',
            'callback_risk': 'Repeat callback',
            'healthy': 'Healthy',
          }
        : const {
            'all': 'All',
            'risk': 'Risk only',
            'unassigned': 'Backlog',
            'overdue': 'Overdue',
            'due_soon': 'Due soon',
            'healthy': 'Healthy',
          };
    return Row(
      children: [
        Text('${_summary?['total_units'] ?? 0} units in scope',
            style: TextStyle(color: Colors.grey[600], fontSize: 12)),
        const Spacer(),
        for (final e in filters.entries)
          Padding(
            padding: const EdgeInsets.only(left: 6),
            child: ChoiceChip(
              label: Text(e.value),
              selected: _status == e.key,
              onSelected: (_) {
                setState(() { _status = e.key; _page = 1; });
                _load();
              },
            ),
          ),
      ],
    );
  }

  Widget _buildBody(List units) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) {
      return Center(child: Text('Error: $_error',
          style: const TextStyle(color: Colors.red)));
    }
    if (units.isEmpty) {
      return const Center(
        child: Text('No unit history found for this filter.',
            style: TextStyle(color: Colors.grey)),
      );
    }
    return ListView(
      children: [
        _tableHeader(),
        for (final uRaw in units) _unitRow(Map<String, dynamic>.from(uRaw as Map)),
      ],
    );
  }

  Widget _tableHeader() {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
      color: Colors.grey.shade100,
      child: Row(children: [
        const Expanded(flex: 4, child: Text('Unit', style: TextStyle(fontWeight: FontWeight.bold))),
        Expanded(flex: 2, child: Text(_isCallback ? 'Callbacks' : 'Maintenance', style: const TextStyle(fontWeight: FontWeight.bold))),
        Expanded(flex: 2, child: Text(_isCallback ? 'AA / B' : 'Last service', style: const TextStyle(fontWeight: FontWeight.bold))),
        Expanded(flex: 2, child: Text(_isCallback ? 'SLA / Repeat' : 'Next service', style: const TextStyle(fontWeight: FontWeight.bold))),
        const Expanded(flex: 2, child: Text('Backlog', style: TextStyle(fontWeight: FontWeight.bold))),
        const Expanded(flex: 2, child: Text('Status', style: TextStyle(fontWeight: FontWeight.bold))),
        const SizedBox(width: 24),
      ]),
    );
  }

  Widget _unitRow(Map<String, dynamic> u) {
    final open = _openUnitId == u['id'];
    return Column(
      children: [
        InkWell(
          onTap: () => _openUnit(u['id'] as int),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 12),
            child: Row(children: [
              Expanded(
                flex: 4,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text('${u['name']}', style: const TextStyle(fontWeight: FontWeight.w600), overflow: TextOverflow.ellipsis),
                    const SizedBox(height: 2),
                    Wrap(spacing: 6, runSpacing: 4, children: [
                      Text('${u['code']}', style: TextStyle(fontSize: 11, color: Colors.grey.shade600)),
                      if ((u['district'] ?? '').toString().isNotEmpty)
                        Text('· ${u['district']}', style: TextStyle(fontSize: 11, color: Colors.grey.shade500)),
                    ]),
                  ],
                ),
              ),
              Expanded(flex: 2, child: Text(_isCallback ? '${u['callback']}' : '${u['maint']}')),
              Expanded(flex: 2, child: Text(_isCallback ? '${u['aa_count']} / ${u['b_count']}' : '${u['last'] ?? '—'}', style: const TextStyle(fontSize: 12))),
              Expanded(flex: 2, child: Text(_isCallback ? '${_pct(u['sla_pct'])} · ${u['repeat_callbacks']}x' : '${u['next_service'] ?? '—'}', style: const TextStyle(fontSize: 12))),
              Expanded(flex: 2, child: _backlogBadge(u)),
              Expanded(flex: 2, child: _statusBadge('${u['status']}', '${u['status_label']}')),
              Icon(open ? Icons.expand_less : Icons.expand_more, size: 20, color: Colors.grey),
            ]),
          ),
        ),
        if (open) _detailPanel(),
        const Divider(height: 1),
      ],
    );
  }

  Widget _backlogBadge(Map<String, dynamic> u) {
    final count = (u['unassigned_count'] ?? 0) as int;
    if (count <= 0) return Text('0', style: TextStyle(color: Colors.grey.shade600));
    final aa = u['aa_unassigned'] ?? 0;
    final b = u['b_unassigned'] ?? 0;
    final label = _isCallback ? '$count · AA $aa / B $b' : '$count';
    return _softBadge(label, aa > 0 ? Colors.red : Colors.orange);
  }

  Widget _detailPanel() {
    if (_detailLoading) {
      return const Padding(
        padding: EdgeInsets.all(16),
        child: Center(child: SizedBox(height: 20, width: 20,
            child: CircularProgressIndicator(strokeWidth: 2))),
      );
    }
    final visits = ((_detail?['visits'] as List?) ?? []);
    final unassigned = ((_detail?['unassigned'] as List?) ?? []);
    if (visits.isEmpty && unassigned.isEmpty) {
      return const Padding(
        padding: EdgeInsets.all(16),
        child: Text('No visits or backlog recorded.', style: TextStyle(color: Colors.grey)),
      );
    }
    return Container(
      color: Colors.blue.shade50.withOpacity(0.3),
      padding: const EdgeInsets.fromLTRB(24, 10, 12, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (unassigned.isNotEmpty) ...[
            Row(children: [
              Icon(Icons.assignment_late, color: Colors.red.shade700, size: 18),
              const SizedBox(width: 6),
              Text(_isCallback ? 'Unassigned callback backlog' : 'Unassigned maintenance backlog',
                  style: const TextStyle(fontWeight: FontWeight.bold)),
            ]),
            const SizedBox(height: 6),
            for (final tRaw in unassigned) _unassignedRow(Map<String, dynamic>.from(tRaw as Map)),
            const Divider(height: 18),
          ],
          if (visits.isNotEmpty) ...[
            Row(children: [
              Icon(_isCallback ? Icons.history_toggle_off : Icons.build_circle_outlined, color: Colors.blue.shade800, size: 18),
              const SizedBox(width: 6),
              Text(_isCallback ? 'Callback incident history' : 'Maintenance visit history',
                  style: const TextStyle(fontWeight: FontWeight.bold)),
            ]),
            const SizedBox(height: 6),
            for (final vRaw in visits) _visitRow(Map<String, dynamic>.from(vRaw as Map)),
          ],
        ],
      ),
    );
  }

  Widget _unassignedRow(Map<String, dynamic> t) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(children: [
        SizedBox(width: 120, child: Text('${t['task_no']}', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600))),
        Container(
          margin: const EdgeInsets.only(right: 8),
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
          decoration: BoxDecoration(color: Colors.red.shade600, borderRadius: BorderRadius.circular(4)),
          child: Text('${t['type']}', style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.bold)),
        ),
        SizedBox(width: 130, child: Text('${t['release_time'] ?? '—'}', style: const TextStyle(fontSize: 12))),
        Expanded(child: Text('${t['reason']}', style: const TextStyle(fontSize: 12), overflow: TextOverflow.ellipsis)),
        Text('${t['duration_min']}m', style: TextStyle(color: Colors.grey.shade600, fontSize: 11)),
      ]),
    );
  }

  Widget _visitRow(Map<String, dynamic> v) {
    final isCallback = v['kind'] == 'Callback';
    final sla = v['sla_met'];
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(children: [
        SizedBox(width: 90, child: Text('${v['date']}', style: const TextStyle(fontSize: 12))),
        Container(
          margin: const EdgeInsets.only(right: 8),
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
          decoration: BoxDecoration(
            color: isCallback ? Colors.purple.shade400 : _typeColor(v['type']),
            borderRadius: BorderRadius.circular(4),
          ),
          child: Text(isCallback ? 'CB ${v['type']}' : '${v['type']}',
              style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.bold)),
        ),
        SizedBox(width: 110, child: Text('${v['start']}–${v['end'] ?? '—'}', style: const TextStyle(fontSize: 12))),
        Expanded(child: Text('${v['technician'] ?? ''}', style: const TextStyle(fontSize: 12), overflow: TextOverflow.ellipsis)),
        if (isCallback) SizedBox(width: 85, child: Text('Resp ${v['response_min'] ?? '—'}m', style: const TextStyle(fontSize: 11))),
        if (isCallback) SizedBox(width: 70, child: _softBadge(sla == true ? 'SLA YES' : (sla == false ? 'SLA NO' : 'SLA N/A'), sla == true ? Colors.green : (sla == false ? Colors.red : Colors.grey))),
        SizedBox(width: 75, child: Text('${v['travel_min'] ?? 0} travel', style: TextStyle(color: Colors.grey.shade600, fontSize: 11))),
        SizedBox(width: 75, child: Text('${v['route_km'] ?? 0} km', style: TextStyle(color: Colors.grey.shade600, fontSize: 11))),
        Text('${v['duration_min']}m', style: TextStyle(color: Colors.grey.shade600, fontSize: 11)),
      ]),
    );
  }

  Widget _unitMetricCard({required String label, required String value, required IconData icon, required Color color}) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withOpacity(0.08),
        border: Border.all(color: color.withOpacity(0.22)),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(children: [
        Container(
          height: 34, width: 34,
          decoration: BoxDecoration(color: color.withOpacity(0.14), shape: BoxShape.circle),
          child: Icon(icon, size: 18, color: color),
        ),
        const SizedBox(width: 10),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: TextStyle(fontSize: 11, color: Colors.grey.shade700), overflow: TextOverflow.ellipsis),
          const SizedBox(height: 3),
          Text(value, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
        ])),
      ]),
    );
  }

  Widget _statusBadge(String status, String label) {
    Color c;
    switch (status) {
      case 'critical': c = Colors.red.shade800; break;
      case 'unassigned': c = Colors.red.shade600; break;
      case 'overdue': c = Colors.deepOrange; break;
      case 'sla_risk': c = Colors.orange.shade800; break;
      case 'callback_risk': c = Colors.orange; break;
      case 'due_soon': c = Colors.amber.shade800; break;
      default: c = Colors.green.shade700;
    }
    return _softBadge(label, c);
  }

  Widget _softBadge(String label, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withOpacity(0.25)),
      ),
      child: Text(label, style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w700), overflow: TextOverflow.ellipsis),
    );
  }

  Color _typeColor(dynamic t) {
    switch (t) {
      case 'A': return Colors.red.shade600;
      case 'B': return Colors.orange.shade700;
      case 'C': return Colors.green.shade600;
      default: return Colors.grey;
    }
  }

  Widget _pager(int total) {
    final pages = (total / 50).ceil();
    if (pages <= 1) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          IconButton(
            onPressed: _page > 1 ? () { setState(() => _page--); _load(); } : null,
            icon: const Icon(Icons.chevron_left),
          ),
          Text('Page $_page of $pages'),
          IconButton(
            onPressed: _page < pages ? () { setState(() => _page++); _load(); } : null,
            icon: const Icon(Icons.chevron_right),
          ),
        ],
      ),
    );
  }
}

// =============================================================================
//  Maintenance Overview / Callback / Monthly Log / Daily Report tabs
// =============================================================================

// shared task-row table used by the overview tabs
Widget _taskTable(List rows, {bool showType = true}) {
  Color typeColor(dynamic t, String kind) {
    if (kind == 'Callback') return Colors.purple.shade400;
    switch (t) {
      case 'A': return Colors.red.shade600;
      case 'B': return Colors.orange.shade700;
      case 'C': return Colors.green.shade600;
      default: return Colors.grey;
    }
  }

  return Column(
    children: [
      Container(
        padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
        color: Colors.grey.shade100,
        child: Row(children: const [
          Expanded(flex: 4, child: Text('Unit', style: TextStyle(fontWeight: FontWeight.bold))),
          Expanded(flex: 2, child: Text('Type', style: TextStyle(fontWeight: FontWeight.bold))),
          Expanded(flex: 3, child: Text('Technician', style: TextStyle(fontWeight: FontWeight.bold))),
          Expanded(flex: 2, child: Text('Date', style: TextStyle(fontWeight: FontWeight.bold))),
          Expanded(flex: 2, child: Text('Time', style: TextStyle(fontWeight: FontWeight.bold))),
        ]),
      ),
      for (final rRaw in rows)
        Builder(builder: (_) {
          final r = Map<String, dynamic>.from(rRaw as Map);
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
            child: Row(children: [
              Expanded(
                flex: 4,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('${r['unit_name']}',
                        style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13),
                        overflow: TextOverflow.ellipsis),
                    Text('${r['unit_code']}',
                        style: TextStyle(fontSize: 11, color: Colors.grey.shade600)),
                  ],
                ),
              ),
              Expanded(
                flex: 2,
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                    decoration: BoxDecoration(
                      color: typeColor(r['type'], '${r['kind']}'),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                        r['kind'] == 'Callback' ? 'CB ${r['type']}' : '${r['type']}',
                        style: const TextStyle(color: Colors.white, fontSize: 10,
                            fontWeight: FontWeight.bold)),
                  ),
                ),
              ),
              Expanded(flex: 3, child: Text('${r['technician'] ?? '—'}',
                  style: const TextStyle(fontSize: 13), overflow: TextOverflow.ellipsis)),
              Expanded(flex: 2, child: Text('${r['date'] ?? ''}',
                  style: const TextStyle(fontSize: 12))),
              Expanded(flex: 2, child: Text('${r['start'] ?? ''}–${r['end'] ?? ''}',
                  style: const TextStyle(fontSize: 12))),
            ]),
          );
        }),
    ],
  );
}

Widget _pagerBar(int total, int page, int pageSize, VoidCallback? onPrev, VoidCallback? onNext) {
  final pages = (total / pageSize).ceil();
  if (pages <= 1) return const SizedBox.shrink();
  return Padding(
    padding: const EdgeInsets.only(top: 8),
    child: Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        IconButton(onPressed: onPrev, icon: const Icon(Icons.chevron_left)),
        Text('Page $page of $pages'),
        IconButton(onPressed: onNext, icon: const Icon(Icons.chevron_right)),
      ],
    ),
  );
}

// ---------------------------------------------------- Maintenance Overview
class MaintenanceOverviewTab extends StatefulWidget {
  final bool fullSchedule;
  const MaintenanceOverviewTab({super.key, this.fullSchedule = false});
  @override
  State<MaintenanceOverviewTab> createState() => _MaintenanceOverviewTabState();
}

class _MaintenanceOverviewTabState extends State<MaintenanceOverviewTab> {
  final ApiClient _api = ApiClient();
  final TextEditingController _searchCtrl = TextEditingController();
  Map<String, dynamic>? _data;
  bool _loading = true;
  String? _error;
  String _type = '';
  String _search = '';
  int _page = 1;

  @override
  void initState() { super.initState(); _load(); }
  @override
  void dispose() { _searchCtrl.dispose(); super.dispose(); }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final d = await _api.fetchMaintenanceOverview(
          type: _type, search: _search, page: _page,
          asOf: widget.fullSchedule ? kFullAsOf : '');
      setState(() { _data = d; _loading = false; });
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    final rows = ((_data?['tasks'] as List?) ?? []);
    final total = _data?['total'] ?? 0;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // Cumulative maintenance KPI / SLA summary for this group, summed from
        // the monthly-report endpoint. Same scope as the list below (up to the
        // roll day, or the whole plan on the Full · twin) via fullSchedule.
        _MaintenanceKpiBand(fullSchedule: widget.fullSchedule),
        const SizedBox(height: 16),
        Expanded(
          child: _DashboardCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(children: [
                  Icon(Icons.build, color: Colors.blue.shade800),
                  const SizedBox(width: 8),
                  const Text('Maintenance Overview',
                      style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                  const Spacer(),
                  for (final t in ['', 'A', 'B', 'C'])
                    Padding(
                      padding: const EdgeInsets.only(left: 6),
                      child: ChoiceChip(
                        label: Text(t.isEmpty ? 'All' : t),
                        selected: _type == t,
                        onSelected: (_) { setState(() { _type = t; _page = 1; }); _load(); },
                      ),
                    ),
                ]),
                const SizedBox(height: 10),
                TextField(
                  controller: _searchCtrl,
                  decoration: const InputDecoration(
                    hintText: 'Search unit or technician…',
                    isDense: true, prefixIcon: Icon(Icons.search, size: 18),
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: (v) { _search = v.trim(); _page = 1; _load(); },
                ),
                const SizedBox(height: 8),
                Text('$total maintenance tasks', style: TextStyle(color: Colors.grey[600], fontSize: 12)),
                const SizedBox(height: 8),
                Expanded(
                  child: _loading
                      ? const Center(child: CircularProgressIndicator())
                      : _error != null
                          ? Center(child: Text('Error: $_error', style: const TextStyle(color: Colors.red)))
                          : rows.isEmpty
                              ? const Center(child: Text('No maintenance tasks found.', style: TextStyle(color: Colors.grey)))
                              : ListView(children: [_taskTable(rows)]),
                ),
                if (!_loading && _error == null)
                  _pagerBar(total, _page, _data?['page_size'] ?? 50,
                      _page > 1 ? () { setState(() => _page--); _load(); } : null,
                      _page * (_data?['page_size'] ?? 50) < total ? () { setState(() => _page++); _load(); } : null),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------- Maintenance KPI band
// A self-contained performance / SLA summary shown at the top of the
// Maintenance Overview tab. It reads ONLY through the existing monthly-report
// endpoint (api/reports/months + api/reports/monthly), summing every in-scope
// month into cumulative, maintenance-only, group-scoped KPIs. It needs no
// optimizer internals, so it survives solver changes: as long as schedule rows
// exist the numbers populate, and if a future solver stops writing
// travel_time_min the travel metrics degrade gracefully to "n/a".
//
// Scope follows the tab: on the roll-date tab the report endpoints are queried
// with no as-of (server clamps to the operating-clock day); on the Full ·
// Maintenance twin they are queried with as-of = all (whole plan). Cost is one
// /reports/months call plus one /reports/monthly call per month in scope.
class _MaintenanceKpiBand extends StatefulWidget {
  final bool fullSchedule;
  const _MaintenanceKpiBand({required this.fullSchedule});
  @override
  State<_MaintenanceKpiBand> createState() => _MaintenanceKpiBandState();
}

class _MaintenanceKpiBandState extends State<_MaintenanceKpiBand> {
  // --- configurable SLA targets (defaults; later driven by UC1 admin data) --
  static const double _slaTravelSharePct = 30.0; // travel ≤ 30% of on-clock time
  static const double _slaAvgTravelMin = 20.0;   // ≤ 20 min between jobs
  static const double _slaMaxTechDayHrs = 9.0;   // no tech over 9h in a day

  final ApiClient _api = ApiClient();
  bool _loading = true;
  bool _expanded = true;
  String? _error;

  // cumulative aggregates (summed across every in-scope month)
  int _visits = 0;
  int _workMin = 0;
  int _travelMin = 0;
  int _techDays = 0;
  bool _sawTravel = false;
  double _maxTechDayHrs = 0;
  final Set<dynamic> _techIds = {};
  final Set<String> _dates = {};
  final Set<String> _units = {};
  int _monthsCounted = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    // reset accumulators
    _visits = _workMin = _travelMin = _techDays = 0;
    _sawTravel = false;
    _maxTechDayHrs = 0;
    _techIds.clear();
    _dates.clear();
    _units.clear();
    _monthsCounted = 0;
    try {
      final asOf = widget.fullSchedule ? kFullAsOf : '';
      final months = await _api.fetchReportMonths(asOf: asOf);
      _monthsCounted = months.length;
      for (final m in months) {
        final rep = await _api.fetchMonthlyReport(
            (m['year'] as num).toInt(), (m['month'] as num).toInt(),
            asOf: asOf);
        final techs = ((rep['technicians'] as List?) ?? []);
        for (final tRaw in techs) {
          final t = Map<String, dynamic>.from(tRaw as Map);
          _techIds.add(t['id']);
          _techDays += (t['days_worked'] as num?)?.toInt() ?? 0;
          final days = ((t['days'] as List?) ?? []);
          for (final dRaw in days) {
            final d = Map<String, dynamic>.from(dRaw as Map);
            _dates.add('${d['date']}');
            final dayHrs =
                ((d['work_minutes'] as num?)?.toDouble() ?? 0) / 60.0;
            if (dayHrs > _maxTechDayHrs) _maxTechDayHrs = dayHrs;
            final visits = ((d['visits'] as List?) ?? []);
            for (final vRaw in visits) {
              final v = Map<String, dynamic>.from(vRaw as Map);
              _visits += 1;
              _workMin += (v['minutes'] as num?)?.toInt() ?? 0;
              if (v.containsKey('travel_min') && v['travel_min'] != null) {
                _sawTravel = true;
                _travelMin += (v['travel_min'] as num).toInt();
              }
              final code = v['unit_code'];
              if (code != null) _units.add(code.toString());
            }
          }
        }
      }
      if (mounted) setState(() => _loading = false);
    } catch (e) {
      if (mounted) setState(() { _error = e.toString(); _loading = false; });
    }
  }

  // --- derived metrics -------------------------------------------------------
  double get _workHrs => _workMin / 60.0;
  double get _travelHrs => _travelMin / 60.0;
  double? get _travelSharePct {
    if (!_sawTravel) return null;
    final denom = _travelMin + _workMin;
    if (denom <= 0) return null;
    return _travelMin / denom * 100.0;
  }
  double? get _avgTravelPerVisit =>
      (_sawTravel && _visits > 0) ? _travelMin / _visits : null;
  double get _avgStopsPerTechDay => _techDays > 0 ? _visits / _techDays : 0;
  double get _avgHrsPerTechDay => _techDays > 0 ? _workHrs / _techDays : 0;

  String _fmtHrs(double h) =>
      h >= 100 ? '${h.round()} h' : '${h.toStringAsFixed(1)} h';

  @override
  Widget build(BuildContext context) {
    final primary = Colors.blue.shade800;
    final scope = widget.fullSchedule ? 'Whole plan' : 'Up to roll day';
    return _DashboardCard(
      padding: const EdgeInsets.fromLTRB(20, 14, 20, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            Icon(Icons.insights, color: primary),
            const SizedBox(width: 8),
            const Text('Performance & SLA',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(width: 10),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: Colors.blue.shade50,
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(scope,
                  style: TextStyle(
                      color: primary, fontSize: 11, fontWeight: FontWeight.w600)),
            ),
            const Spacer(),
            if (_loading)
              const SizedBox(
                  height: 16, width: 16,
                  child: CircularProgressIndicator(strokeWidth: 2))
            else
              IconButton(
                tooltip: 'Refresh',
                icon: const Icon(Icons.refresh, size: 18),
                onPressed: _load,
              ),
            IconButton(
              tooltip: _expanded ? 'Collapse' : 'Expand',
              icon: Icon(_expanded ? Icons.expand_less : Icons.expand_more,
                  size: 22),
              onPressed: () => setState(() => _expanded = !_expanded),
            ),
          ]),
          if (_expanded) ...[
            const SizedBox(height: 6),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 10),
                child: Text('Could not load metrics: $_error',
                    style: TextStyle(color: Colors.red.shade700, fontSize: 13)),
              )
            else if (_loading)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 18),
                child: Center(
                    child: Text('Summing the schedule…',
                        style: TextStyle(color: Colors.grey))),
              )
            else if (_monthsCounted == 0 || _visits == 0)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 14),
                child: Text('No maintenance activity in scope yet.',
                    style: TextStyle(color: Colors.grey)),
              )
            else ...[
              Wrap(
                spacing: 10, runSpacing: 10,
                children: [
                  _stat('Visits', '$_visits', Icons.place_outlined),
                  _stat('Buildings', '${_units.length}', Icons.apartment_outlined),
                  _stat('Work time', _fmtHrs(_workHrs), Icons.schedule),
                  _stat('Travel time', _sawTravel ? _fmtHrs(_travelHrs) : 'n/a',
                      Icons.alt_route, muted: !_sawTravel),
                  _stat('Technicians', '${_techIds.length}',
                      Icons.engineering_outlined),
                  _stat('Days covered', '${_dates.length}', Icons.event_outlined),
                ],
              ),
              const SizedBox(height: 14),
              const Divider(height: 1),
              const SizedBox(height: 12),
              Wrap(
                spacing: 22, runSpacing: 10,
                children: [
                  _eff('Travel share',
                      _travelSharePct == null
                          ? 'n/a'
                          : '${_travelSharePct!.toStringAsFixed(1)}%'),
                  _eff('Avg stops / tech·day',
                      _avgStopsPerTechDay.toStringAsFixed(1)),
                  _eff('Avg hours / tech·day',
                      _avgHrsPerTechDay.toStringAsFixed(1)),
                  _eff('Avg travel / visit',
                      _avgTravelPerVisit == null
                          ? 'n/a'
                          : '${_avgTravelPerVisit!.toStringAsFixed(0)} min'),
                ],
              ),
              const SizedBox(height: 14),
              const Divider(height: 1),
              const SizedBox(height: 10),
              Row(children: [
                Icon(Icons.verified_outlined,
                    size: 16, color: Colors.grey.shade600),
                const SizedBox(width: 6),
                Text('Service-level checks',
                    style: TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 13,
                        color: Colors.grey.shade800)),
              ]),
              const SizedBox(height: 8),
              _sla(
                pass: _travelSharePct == null
                    ? null
                    : _travelSharePct! <= _slaTravelSharePct,
                label: 'Travel share within budget',
                detail: _travelSharePct == null
                    ? 'travel not recorded'
                    : '${_travelSharePct!.toStringAsFixed(1)}% · target ≤ ${_slaTravelSharePct.toStringAsFixed(0)}%',
              ),
              _sla(
                pass: _avgTravelPerVisit == null
                    ? null
                    : _avgTravelPerVisit! <= _slaAvgTravelMin,
                label: 'Short hops between jobs',
                detail: _avgTravelPerVisit == null
                    ? 'travel not recorded'
                    : '${_avgTravelPerVisit!.toStringAsFixed(0)} min avg · target ≤ ${_slaAvgTravelMin.toStringAsFixed(0)} min',
              ),
              _sla(
                pass: _maxTechDayHrs <= _slaMaxTechDayHrs,
                label: 'No technician over the daily cap',
                detail:
                    'busiest day ${_maxTechDayHrs.toStringAsFixed(1)} h · cap ${_slaMaxTechDayHrs.toStringAsFixed(0)} h',
              ),
              const SizedBox(height: 8),
              Text(
                  'SLA targets are defaults; they can be configured later via '
                  'system settings (UC1).',
                  style: TextStyle(color: Colors.grey.shade500, fontSize: 11)),
            ],
          ],
        ],
      ),
    );
  }

  Widget _stat(String label, String value, IconData icon,
      {bool muted = false}) {
    final c = muted ? Colors.grey.shade500 : Colors.blue.shade800;
    return Container(
      width: 150,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: muted ? Colors.grey.shade50 : Colors.blue.shade50,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
            color: muted ? Colors.grey.shade200 : Colors.blue.shade100),
      ),
      child: Row(
        children: [
          Icon(icon, size: 20, color: c),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(value,
                    style: TextStyle(
                        fontSize: 18, fontWeight: FontWeight.bold, color: c)),
                Text(label,
                    style: TextStyle(
                        fontSize: 11, color: Colors.grey.shade600)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _eff(String label, String value) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(value,
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
        Text(label,
            style: TextStyle(fontSize: 11, color: Colors.grey.shade600)),
      ],
    );
  }

  Widget _sla(
      {required bool? pass, required String label, required String detail}) {
    // pass == null -> not measurable (e.g. travel not recorded) -> neutral
    final Color c;
    final IconData icon;
    if (pass == null) {
      c = Colors.grey.shade500;
      icon = Icons.remove_circle_outline;
    } else if (pass) {
      c = Colors.green.shade700;
      icon = Icons.check_circle;
    } else {
      c = Colors.orange.shade800;
      icon = Icons.error_outline;
    }
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Icon(icon, size: 18, color: c),
          const SizedBox(width: 10),
          Expanded(
            child: Text(label,
                style: const TextStyle(
                    fontSize: 13, fontWeight: FontWeight.w500)),
          ),
          Text(detail,
              style: TextStyle(fontSize: 12, color: Colors.grey.shade600)),
        ],
      ),
    );
  }
}

// ---------------------------------------------------- Repair / Callback
class CallbackOverviewTab extends StatefulWidget {
  final bool fullSchedule;
  const CallbackOverviewTab({super.key, this.fullSchedule = false});
  @override
  State<CallbackOverviewTab> createState() => _CallbackOverviewTabState();
}

class _CallbackOverviewTabState extends State<CallbackOverviewTab> {
  final ApiClient _api = ApiClient();
  final TextEditingController _searchCtrl = TextEditingController();
  Map<String, dynamic>? _data;
  bool _loading = true;
  bool _exporting = false;
  String? _error;
  String _priority = '';
  String _status = '';
  String _search = '';
  int _page = 1;

  @override
  void initState() { super.initState(); _load(); }
  @override
  void dispose() { _searchCtrl.dispose(); super.dispose(); }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final d = await _api.fetchCallbackOverview(
          priority: _priority, status: _status, search: _search, page: _page,
          asOf: widget.fullSchedule ? kFullAsOf : '');
      setState(() { _data = d; _loading = false; });
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  Future<void> _export() async {
    setState(() => _exporting = true);
    try {
      final url = _api.callbackOverviewExportUrl(
        priority: _priority,
        status: _status,
        search: _search,
        asOf: widget.fullSchedule ? kFullAsOf : '',
      );
      final r = await http.get(Uri.parse(url), headers: {'Authorization': 'Token $kSupervisorToken'});
      if (r.statusCode != 200) throw Exception('Export failed: ${r.statusCode}');
      final blob = html.Blob([r.bodyBytes],
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
      final href = html.Url.createObjectUrlFromBlob(blob);
      html.AnchorElement(href: href)
        ..setAttribute('download', widget.fullSchedule
            ? 'full_callback_incident_center.xlsx'
            : 'callback_incident_center.xlsx')
        ..click();
      html.Url.revokeObjectUrl(href);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Export error: $e')));
      }
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final rows = ((_data?['tasks'] as List?) ?? []);
    final total = _data?['total'] ?? 0;
    final summary = Map<String, dynamic>.from((_data?['summary'] as Map?) ?? {});
    final scopeStart = summary['scope_start'] ?? '';
    final scopeEnd = summary['scope_end'] ?? '';
    final title = widget.fullSchedule ? 'Full · Callback Incident Center' : 'Callback Incident Center';
    return _DashboardCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            Icon(Icons.report_problem, color: Colors.purple.shade700),
            const SizedBox(width: 8),
            Text(title, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(width: 10),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: Colors.purple.shade50,
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(widget.fullSchedule ? 'whole generated plan' : 'to roll date',
                  style: TextStyle(color: Colors.purple.shade800, fontSize: 11, fontWeight: FontWeight.w600)),
            ),
            const Spacer(),
            FilledButton.icon(
              onPressed: _exporting ? null : _export,
              icon: _exporting
                  ? const SizedBox(width: 16, height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  : const Icon(Icons.download, size: 18),
              label: const Text('Export Excel'),
            ),
          ]),
          const SizedBox(height: 6),
          Text('Scope: $scopeStart → $scopeEnd. Incidents, SLA, assigned work, and unassigned callback backlog.',
              style: TextStyle(color: Colors.grey.shade600, fontSize: 12)),
          const SizedBox(height: 12),
          _summaryBand(summary),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
              child: TextField(
                controller: _searchCtrl,
                decoration: const InputDecoration(
                  hintText: 'Search incident, unit, technician…',
                  isDense: true, prefixIcon: Icon(Icons.search, size: 18),
                  border: OutlineInputBorder(),
                ),
                onSubmitted: (v) { _search = v.trim(); _page = 1; _load(); },
              ),
            ),
            const SizedBox(width: 10),
            for (final item in const [
              ['', 'All'], ['AA', 'AA'], ['B', 'B'],
            ])
              Padding(
                padding: const EdgeInsets.only(left: 6),
                child: ChoiceChip(
                  label: Text(item[1]),
                  selected: _priority == item[0],
                  onSelected: (_) { setState(() { _priority = item[0]; _page = 1; }); _load(); },
                ),
              ),
          ]),
          const SizedBox(height: 8),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(children: [
              for (final item in const [
                ['', 'All incidents'],
                ['UNASSIGNED', 'Unassigned'],
                ['SLA_MISSED', 'SLA missed'],
                ['SLA_MET', 'SLA met'],
                ['ASSIGNED', 'Assigned'],
                ['ON_SITE', 'On site'],
                ['ON_PLAN', 'On plan'],
                ['DONE', 'Done'],
              ])
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: ChoiceChip(
                    label: Text(item[1]),
                    selected: _status == item[0],
                    onSelected: (_) { setState(() { _status = item[0]; _page = 1; }); _load(); },
                  ),
                ),
            ]),
          ),
          const SizedBox(height: 8),
          Text('$total incident rows shown', style: TextStyle(color: Colors.grey[600], fontSize: 12)),
          const SizedBox(height: 8),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _error != null
                    ? Center(child: Text('Error: $_error', style: const TextStyle(color: Colors.red)))
                    : rows.isEmpty
                        ? const Center(child: Text('No callback incidents found.', style: TextStyle(color: Colors.grey)))
                        : ListView(children: [_callbackIncidentTable(rows)]),
          ),
          if (!_loading && _error == null)
            _pagerBar(total, _page, _data?['page_size'] ?? 50,
                _page > 1 ? () { setState(() => _page--); _load(); } : null,
                _page * (_data?['page_size'] ?? 50) < total ? () { setState(() => _page++); _load(); } : null),
        ],
      ),
    );
  }

  Widget _summaryBand(Map<String, dynamic> s) {
    final total = s['total'] ?? 0;
    final aa = s['aa'] ?? 0;
    final b = s['b'] ?? 0;
    final unassigned = s['unassigned'] ?? 0;
    final slaPct = (s['sla_pct'] as num?)?.toDouble() ?? 0;
    final missed = s['sla_missed'] ?? 0;
    final avgResp = (s['avg_response_min'] as num?)?.toDouble() ?? 0;
    return Wrap(
      spacing: 10, runSpacing: 10,
      children: [
        _callbackStat('Incidents', '$total', 'AA $aa · B $b', Icons.warning_amber, Colors.purple),
        _callbackStat('Unassigned', '$unassigned', unassigned == 0 ? 'no backlog' : 'needs action', Icons.inventory_2_outlined, unassigned == 0 ? Colors.green : Colors.red),
        _callbackStat('SLA success', '${slaPct.toStringAsFixed(1)}%', '$missed missed', Icons.verified_outlined, slaPct >= 85 ? Colors.green : Colors.red),
        _callbackStat('Avg response', '${avgResp.toStringAsFixed(0)}m', 'report → arrival', Icons.timer_outlined, Colors.blue),
      ],
    );
  }

  Widget _callbackStat(String label, String value, String sub, IconData icon, MaterialColor c) {
    return Container(
      width: 210,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: c.shade50,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: c.shade100),
      ),
      child: Row(children: [
        CircleAvatar(backgroundColor: c.shade100, child: Icon(icon, color: c.shade700, size: 20)),
        const SizedBox(width: 10),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: TextStyle(color: Colors.grey.shade700, fontSize: 11)),
          Text(value, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
          Text(sub, style: TextStyle(color: Colors.grey.shade600, fontSize: 11)),
        ])),
      ]),
    );
  }

  Widget _callbackIncidentTable(List rows) {
    return Column(children: [
      Container(
        padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
        color: Colors.grey.shade100,
        child: Row(children: const [
          Expanded(flex: 4, child: Text('Incident / Unit', style: TextStyle(fontWeight: FontWeight.bold))),
          Expanded(flex: 1, child: Text('Priority', style: TextStyle(fontWeight: FontWeight.bold))),
          Expanded(flex: 2, child: Text('Status', style: TextStyle(fontWeight: FontWeight.bold))),
          Expanded(flex: 3, child: Text('Technician', style: TextStyle(fontWeight: FontWeight.bold))),
          Expanded(flex: 2, child: Text('Reported', style: TextStyle(fontWeight: FontWeight.bold))),
          Expanded(flex: 2, child: Text('Scheduled', style: TextStyle(fontWeight: FontWeight.bold))),
          Expanded(flex: 2, child: Text('Response / SLA', style: TextStyle(fontWeight: FontWeight.bold))),
          Expanded(flex: 2, child: Text('Action', style: TextStyle(fontWeight: FontWeight.bold))),
        ]),
      ),
      for (final rRaw in rows)
        Builder(builder: (_) {
          final r = Map<String, dynamic>.from(rRaw as Map);
          final unassigned = r['status'] == 'UNASSIGNED';
          return Container(
            padding: const EdgeInsets.symmetric(vertical: 9, horizontal: 12),
            decoration: BoxDecoration(
              color: unassigned ? Colors.red.shade50 : null,
              border: Border(bottom: BorderSide(color: Colors.grey.shade300)),
            ),
            child: Row(children: [
              Expanded(flex: 4, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${r['task_no']} · ${r['unit_name']}',
                    style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13), overflow: TextOverflow.ellipsis),
                Text('${r['unit_code']}', style: TextStyle(fontSize: 11, color: Colors.grey.shade600)),
                if (unassigned && (r['unassigned_reason'] ?? '').toString().isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 3),
                    child: Text('${r['unassigned_reason']}',
                        style: TextStyle(fontSize: 11, color: Colors.red.shade700), overflow: TextOverflow.ellipsis),
                  ),
              ])),
              Expanded(flex: 1, child: Align(alignment: Alignment.centerLeft, child: _priorityChip('${r['priority']}'))),
              Expanded(flex: 2, child: Align(alignment: Alignment.centerLeft, child: _statusChip('${r['status_label']}', '${r['status']}'))),
              Expanded(flex: 3, child: Text('${r['technician'] ?? '—'}', style: const TextStyle(fontSize: 13), overflow: TextOverflow.ellipsis)),
              Expanded(flex: 2, child: Text('${r['reported_date'] ?? r['date'] ?? ''}\n${r['reported'] ?? ''}', style: const TextStyle(fontSize: 12))),
              Expanded(flex: 2, child: Text((r['start'] ?? '').toString().isEmpty ? '—' : '${r['start']}–${r['end']}', style: const TextStyle(fontSize: 12))),
              Expanded(flex: 2, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(r['response_min'] == null ? '—' : 'Resp ${r['response_min']}m', style: const TextStyle(fontSize: 12)),
                const SizedBox(height: 2),
                _slaChip('${r['sla_label']}', r['sla_met'] == true),
              ])),
              Expanded(flex: 2, child: Text('${r['action_hint'] ?? ''}', style: TextStyle(fontSize: 12, color: unassigned ? Colors.red.shade700 : Colors.grey.shade700))),
            ]),
          );
        }),
    ]);
  }

  Widget _priorityChip(String p) {
    final isAA = p == 'AA';
    final c = isAA ? Colors.red : Colors.purple;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(color: c.shade500, borderRadius: BorderRadius.circular(5)),
      child: Text('CB $p', style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.bold)),
    );
  }

  Widget _statusChip(String label, String status) {
    MaterialColor c;
    if (status == 'UNASSIGNED') c = Colors.red;
    else if (status == 'ON_SITE') c = Colors.blue;
    else if (status == 'DONE') c = Colors.green;
    else if (status == 'ON_PLAN') c = Colors.grey;
    else c = Colors.orange;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: c.shade50, border: Border.all(color: c.shade200), borderRadius: BorderRadius.circular(20)),
      child: Text(label, style: TextStyle(color: c.shade800, fontSize: 11, fontWeight: FontWeight.w600)),
    );
  }

  Widget _slaChip(String label, bool ok) {
    final c = ok ? Colors.green : Colors.red;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(color: c.shade50, border: Border.all(color: c.shade200), borderRadius: BorderRadius.circular(12)),
      child: Text(label, style: TextStyle(color: c.shade700, fontSize: 10, fontWeight: FontWeight.w700)),
    );
  }
}

// ---------------------------------------------------- Monthly Log

class MonthlyLogTab extends StatefulWidget {
  final DateTime activeDate;   // operating-clock day
  final bool fullSchedule;
  const MonthlyLogTab({super.key, required this.activeDate, this.fullSchedule = false});
  @override
  State<MonthlyLogTab> createState() => _MonthlyLogTabState();
}

class _MonthlyLogTabState extends State<MonthlyLogTab> {
  final ApiClient _api = ApiClient();
  final TextEditingController _search = TextEditingController();
  Map<String, dynamic>? _data;
  bool _loading = true;
  String? _error;
  late int _year;
  late int _month;
  int _page = 1;
  String _status = '';
  String _priority = '';

  @override
  void initState() {
    super.initState();
    _year = widget.activeDate.year;
    _month = widget.activeDate.month;
    _load();
  }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      var requestPriority = _priority;
      var d = await _api.fetchMonthlyLog(
        _year,
        _month,
        page: _page,
        asOf: widget.fullSchedule ? kFullAsOf : '',
        search: _search.text.trim(),
        status: _status,
        priority: requestPriority,
      );

      // If an old filter from another supervisor/domain is no longer valid
      // (e.g. C selected while logged into callback), clear it and refetch.
      final gt = '${d['group_type'] ?? ''}'.toLowerCase();
      final validCallback = ['', 'AA', 'B'];
      final validMaintenance = ['', 'A', 'B', 'C'];
      final invalidForCallback = gt == 'callback' && !validCallback.contains(_priority);
      final invalidForMaintenance = gt == 'maintenance' && !validMaintenance.contains(_priority);
      if (invalidForCallback || invalidForMaintenance) {
        _priority = '';
        requestPriority = '';
        d = await _api.fetchMonthlyLog(
          _year,
          _month,
          page: 1,
          asOf: widget.fullSchedule ? kFullAsOf : '',
          search: _search.text.trim(),
          status: _status,
          priority: requestPriority,
        );
        _page = 1;
      }

      setState(() { _data = d; _loading = false; });
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  String get _groupType => '${_data?['group_type'] ?? ''}'.toLowerCase();
  bool get _isCallback => _groupType == 'callback';
  bool get _isMaintenance => _groupType == 'maintenance';

  @override
  Widget build(BuildContext context) {
    final rows = ((_data?['log'] as List?) ?? []);
    final total = _data?['total'] ?? 0;
    final summary = Map<String, dynamic>.from((_data?['summary'] as Map?) ?? {});
    final scope = '${_data?['scope'] ?? (widget.fullSchedule ? 'full' : 'roll-date')}';
    final scopeStart = '${_data?['scope_start'] ?? ''}';
    final scopeEnd = '${_data?['scope_end'] ?? ''}';
    final title = widget.fullSchedule ? 'Full Monthly Work Log' : 'Monthly Tracking & Logs';

    return _DashboardCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            Icon(Icons.calendar_month, color: Colors.teal.shade700),
            const SizedBox(width: 8),
            Text(title, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(width: 10),
            if (_data != null)
              _scopeChip(scope == 'full' ? 'FULL SCHEDULE' : 'TO ROLL DATE'),
            const Spacer(),
            SizedBox(
              width: 270,
              child: TextField(
                controller: _search,
                decoration: const InputDecoration(
                  prefixIcon: Icon(Icons.search),
                  hintText: 'Search unit / tech / task...',
                  isDense: true,
                  border: OutlineInputBorder(),
                ),
                onSubmitted: (_) { _page = 1; _load(); },
              ),
            ),
            const SizedBox(width: 8),
            IconButton(onPressed: () { _page = 1; _load(); }, icon: const Icon(Icons.refresh)),
            const SizedBox(width: 8),
            DropdownButton<int>(
              value: _month,
              items: [
                for (int m = 1;
                    m <= (widget.fullSchedule ? 12 : (_year == widget.activeDate.year ? widget.activeDate.month : 12));
                    m++)
                  DropdownMenuItem(value: m, child: Text('Month $m'))
              ],
              onChanged: (m) { setState(() { _month = m!; _page = 1; }); _load(); },
            ),
            const SizedBox(width: 8),
            DropdownButton<int>(
              value: _year,
              items: [
                for (int y = 2025; y <= widget.activeDate.year + (widget.fullSchedule ? 1 : 0); y++)
                  DropdownMenuItem(value: y, child: Text('$y'))
              ],
              onChanged: (y) {
                setState(() {
                  _year = y!;
                  if (!widget.fullSchedule && _year == widget.activeDate.year && _month > widget.activeDate.month) {
                    _month = widget.activeDate.month;
                  }
                  _page = 1;
                });
                _load();
              },
            ),
          ]),
          const SizedBox(height: 8),
          if (_data != null)
            Text(
              widget.fullSchedule
                  ? 'Full generated schedule scope for $scopeStart → $scopeEnd.'
                  : 'Roll-date scope for $scopeStart → $scopeEnd. Live statuses are based on the selected roll date/time.',
              style: TextStyle(color: Colors.grey[600], fontSize: 12),
            ),
          const SizedBox(height: 10),
          if (_data != null) _summaryCards(summary),
          const SizedBox(height: 10),
          _filters(),
          const SizedBox(height: 10),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _error != null
                    ? Center(child: Text('Error: $_error', style: const TextStyle(color: Colors.red)))
                    : rows.isEmpty
                        ? const Center(child: Text('No tasks logged for this month.', style: TextStyle(color: Colors.grey)))
                        : ListView(children: [_enhancedLogTable(rows)]),
          ),
          if (!_loading && _error == null)
            _pagerBar(total, _page, _data?['page_size'] ?? 100,
                _page > 1 ? () { setState(() => _page--); _load(); } : null,
                _page * (_data?['page_size'] ?? 100) < total ? () { setState(() => _page++); _load(); } : null),
        ],
      ),
    );
  }

  Widget _summaryCards(Map<String, dynamic> s) {
    final isCb = _isCallback;
    final cards = <Widget>[
      _metricCard(isCb ? 'Callbacks logged' : 'Tasks logged', '${s['total'] ?? _data?['total'] ?? 0}', Icons.list_alt, Colors.blue),
      _metricCard('Assigned', '${s['assigned'] ?? 0}', Icons.assignment_turned_in_outlined, Colors.green),
      _metricCard('Unassigned', '${s['unassigned'] ?? 0}', Icons.warning_amber_outlined,
          (s['unassigned'] ?? 0) > 0 ? Colors.red : Colors.grey),
      _metricCard('Done / Active', '${s['done'] ?? 0} / ${(s['on_site'] ?? 0) + (s['on_route'] ?? 0)}',
          Icons.play_circle_outline, Colors.orange),
    ];
    if (isCb) {
      cards.addAll([
        _metricCard('AA / B', '${s['aa'] ?? 0} / ${s['b'] ?? 0}', Icons.priority_high, Colors.purple),
        _metricCard('SLA success', s['sla_pct'] == null ? 'N/A' : '${s['sla_pct']}%', Icons.verified_outlined,
            (s['sla_pct'] ?? 100) >= 80 ? Colors.green : Colors.red),
        _metricCard('SLA missed', '${s['sla_missed'] ?? 0}', Icons.cancel_outlined,
            (s['sla_missed'] ?? 0) > 0 ? Colors.red : Colors.grey),
        _metricCard('Avg response', s['avg_response_min'] == null ? 'N/A' : '${s['avg_response_min']}m', Icons.timer_outlined, Colors.indigo),
      ]);
    } else {
      cards.addAll([
        _metricCard('A/B/C work', '${s['maintenance'] ?? 0}', Icons.build_circle_outlined, Colors.indigo),
        _metricCard('Service hours', '${s['service_hours'] ?? 0} h', Icons.schedule, Colors.teal),
        _metricCard('Travel hours', '${s['travel_hours'] ?? 0} h', Icons.directions_car_outlined, Colors.blueGrey),
        _metricCard('Route KM', '${s['route_km'] ?? 0} km', Icons.route_outlined, Colors.deepPurple),
      ]);
    }
    return GridView.count(
      crossAxisCount: 4,
      mainAxisSpacing: 10,
      crossAxisSpacing: 10,
      childAspectRatio: 4.2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      children: cards,
    );
  }

  Widget _filters() {
    final statuses = <List<String>>[
      ['', 'All'],
      ['DONE', 'Done'],
      ['ON_ROUTE', 'On route'],
      ['ON_SITE', 'On site'],
      ['ON_PLAN', 'On plan'],
      ['UNASSIGNED', 'Unassigned'],
      if (_isCallback) ['SLA_NO', 'SLA missed'],
      if (_isCallback) ['SLA_YES', 'SLA met'],
    ];
    final priorities = _isCallback
        ? <List<String>>[['', 'All priority'], ['AA', 'AA'], ['B', 'B']]
        : <List<String>>[['', 'All type'], ['A', 'A'], ['B', 'B'], ['C', 'C']];

    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final item in statuses)
          ChoiceChip(
            label: Text(item[1]),
            selected: _status == item[0],
            onSelected: (_) { setState(() { _status = item[0]; _page = 1; }); _load(); },
          ),
        const SizedBox(width: 12),
        for (final item in priorities)
          ChoiceChip(
            label: Text(item[1]),
            selected: _priority == item[0],
            onSelected: (_) { setState(() { _priority = item[0]; _page = 1; }); _load(); },
          ),
      ],
    );
  }

  Widget _enhancedLogTable(List rows) {
    final isCb = _isCallback;
    return Column(children: [
      Container(
        padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
        color: Colors.grey.shade100,
        child: Row(children: [
          const Expanded(flex: 3, child: Text('Date', style: TextStyle(fontWeight: FontWeight.bold))),
          Expanded(flex: isCb ? 4 : 5, child: const Text('Unit', style: TextStyle(fontWeight: FontWeight.bold))),
          const Expanded(flex: 2, child: Text('Type', style: TextStyle(fontWeight: FontWeight.bold))),
          const Expanded(flex: 3, child: Text('Technician', style: TextStyle(fontWeight: FontWeight.bold))),
          const Expanded(flex: 3, child: Text('Time', style: TextStyle(fontWeight: FontWeight.bold))),
          if (isCb) const Expanded(flex: 2, child: Text('Resp.', style: TextStyle(fontWeight: FontWeight.bold))),
          if (isCb) const Expanded(flex: 2, child: Text('SLA', style: TextStyle(fontWeight: FontWeight.bold))),
          const Expanded(flex: 2, child: Text('Status', style: TextStyle(fontWeight: FontWeight.bold))),
          const Expanded(flex: 2, child: Text('Travel', style: TextStyle(fontWeight: FontWeight.bold))),
        ]),
      ),
      for (final raw in rows) _logRow(Map<String, dynamic>.from(raw as Map), isCb),
    ]);
  }

  Widget _logRow(Map<String, dynamic> r, bool isCb) {
    final status = '${r['status'] ?? ''}';
    final isUnassigned = status == 'UNASSIGNED';
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 12),
      decoration: BoxDecoration(
        color: isUnassigned ? Colors.red.shade50 : Colors.white,
        border: Border(bottom: BorderSide(color: Colors.grey.shade300)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Expanded(flex: 3, child: Text('${r['date'] ?? ''}', style: const TextStyle(fontSize: 12))),
          Expanded(
            flex: isCb ? 4 : 5,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${r['unit_name'] ?? ''}', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600), overflow: TextOverflow.ellipsis),
              Text('${r['unit_code'] ?? ''} · ${r['task_no'] ?? ''}', style: TextStyle(fontSize: 10, color: Colors.grey.shade600), overflow: TextOverflow.ellipsis),
            ]),
          ),
          Expanded(flex: 2, child: Align(alignment: Alignment.centerLeft, child: _typeChip('${r['operation'] ?? ''}', '${r['priority'] ?? r['type'] ?? ''}'))),
          Expanded(flex: 3, child: Text('${r['technician'] ?? '—'}', style: const TextStyle(fontSize: 12), overflow: TextOverflow.ellipsis)),
          Expanded(flex: 3, child: Text(_timeText(r), style: const TextStyle(fontSize: 12))),
          if (isCb) Expanded(flex: 2, child: Text(r['response_min'] == null ? '—' : '${r['response_min']}m', style: const TextStyle(fontSize: 12))),
          if (isCb) Expanded(flex: 2, child: _slaChip(r['sla_met'])),
          Expanded(flex: 2, child: _statusChip('${r['status_label'] ?? status}', status)),
          Expanded(flex: 2, child: Text('${r['travel_min'] ?? 0}m · ${r['route_km'] ?? 0}km', style: TextStyle(fontSize: 11, color: Colors.grey.shade700))),
        ]),
        if (isUnassigned && '${r['unassigned_reason'] ?? ''}'.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text('Reason: ${r['unassigned_reason']}', style: TextStyle(fontSize: 12, color: Colors.red.shade700)),
        ],
      ]),
    );
  }

  String _timeText(Map<String, dynamic> r) {
    if ('${r['status'] ?? ''}' == 'UNASSIGNED') {
      return '${r['reported'] ?? r['start'] ?? ''} reported';
    }
    final rep = '${r['reported'] ?? ''}';
    final start = '${r['start'] ?? ''}';
    final end = '${r['end'] ?? ''}';
    if (_isCallback && rep.isNotEmpty) return 'Rep $rep · $start–$end';
    return '$start–$end';
  }

  Widget _metricCard(String label, String value, IconData icon, MaterialColor color) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.shade50,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.shade100),
      ),
      child: Row(children: [
        CircleAvatar(backgroundColor: color.shade100, child: Icon(icon, color: color.shade700, size: 18)),
        const SizedBox(width: 10),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.center, children: [
          Text(label, style: TextStyle(fontSize: 11, color: Colors.grey.shade700), overflow: TextOverflow.ellipsis),
          Text(value, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold), overflow: TextOverflow.ellipsis),
        ])),
      ]),
    );
  }

  Widget _scopeChip(String text) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
    decoration: BoxDecoration(color: Colors.green.shade50, borderRadius: BorderRadius.circular(12)),
    child: Text(text, style: TextStyle(fontSize: 11, color: Colors.green.shade800, fontWeight: FontWeight.bold)),
  );

  Widget _typeChip(String operation, String type) {
    final isCb = operation == 'CALLBACK';
    final color = isCb ? (type == 'AA' ? Colors.red : Colors.purple) : (type == 'A' ? Colors.red : type == 'B' ? Colors.orange : Colors.green);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(color: color.shade500, borderRadius: BorderRadius.circular(5)),
      child: Text(isCb ? 'CB $type' : type, style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.bold)),
    );
  }

  Widget _statusChip(String label, String status) {
    final normalized = status.toUpperCase().replaceAll(' ', '_');
    MaterialColor color = Colors.grey;
    if (normalized == 'DONE' || normalized == 'COMPLETED') color = Colors.green;
    if (normalized == 'ON_SITE') color = Colors.blue;
    if (normalized == 'ON_ROUTE') color = Colors.orange;
    if (normalized == 'UNASSIGNED' || normalized == 'SLA_MISSED') color = Colors.red;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(color: color.shade50, borderRadius: BorderRadius.circular(12), border: Border.all(color: color.shade200)),
      child: Text(label, style: TextStyle(color: color.shade700, fontSize: 10, fontWeight: FontWeight.bold), overflow: TextOverflow.ellipsis),
    );
  }

  Widget _slaChip(dynamic met) {
    if (met == null) return const Text('—', style: TextStyle(fontSize: 12));
    final ok = met == true;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(color: ok ? Colors.green.shade50 : Colors.red.shade50, borderRadius: BorderRadius.circular(12), border: Border.all(color: ok ? Colors.green.shade200 : Colors.red.shade200)),
      child: Text(ok ? 'YES' : 'NO', style: TextStyle(color: ok ? Colors.green.shade700 : Colors.red.shade700, fontSize: 10, fontWeight: FontWeight.bold)),
    );
  }
}

// ---------------------------------------------------- Daily Report
class DailyReportTab extends StatefulWidget {
  final DateTime activeDate;
  final DateTime activeTime;
  final bool fullSchedule;
  const DailyReportTab({super.key, required this.activeDate, required this.activeTime, this.fullSchedule = false});
  @override
  State<DailyReportTab> createState() => _DailyReportTabState();
}

class _DailyReportTabState extends State<DailyReportTab> {
  final ApiClient _api = ApiClient();
  final TextEditingController _searchCtrl = TextEditingController();
  Map<String, dynamic>? _data;
  bool _loading = true;
  String? _error;
  late String _date;
  String _search = '';
  String _status = 'all';
  String _type = 'all';

  @override
  void initState() {
    super.initState();
    _date = _fmtDate(widget.activeDate);
    _load();
  }

  @override
  void didUpdateWidget(covariant DailyReportTab oldWidget) {
    super.didUpdateWidget(oldWidget);
    final newDate = _fmtDate(widget.activeDate);

    // Daily Report live statuses must follow the operating roll clock,
    // not only the date. Previously this tab used activeDate at midnight,
    // so the first task of the day stayed ON ROUTE while later tasks stayed
    // ON PLAN. Reload when the roll date or roll minute changes.
    final oldMinute = DateTime(
      oldWidget.activeTime.year, oldWidget.activeTime.month, oldWidget.activeTime.day,
      oldWidget.activeTime.hour, oldWidget.activeTime.minute,
    );
    final newMinute = DateTime(
      widget.activeTime.year, widget.activeTime.month, widget.activeTime.day,
      widget.activeTime.hour, widget.activeTime.minute,
    );

    if (!widget.fullSchedule && (newDate != _date || newMinute != oldMinute)) {
      _date = newDate;
      _load();
    }
  }

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  String _fmtDate(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  String get _asOf => widget.fullSchedule ? kFullAsOf : widget.activeTime.toIso8601String();

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final d = await _api.fetchDailyReport(
        date: _date,
        asOf: _asOf,
        search: _search,
        status: _status,
        type: _type,
      );
      final gtype = '${d['group_type'] ?? ''}';
      if (gtype == 'callback' && !['all', 'AA', 'B'].contains(_type)) {
        _type = 'all';
      }
      if (gtype == 'maintenance' && !['all', 'A', 'B', 'C'].contains(_type)) {
        _type = 'all';
      }
      setState(() { _data = d; _loading = false; });
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: DateTime.tryParse(_date) ?? widget.activeDate,
      firstDate: DateTime(2026, 1, 1),
      lastDate: widget.fullSchedule ? DateTime(2099, 12, 31) : widget.activeDate,
    );
    if (picked != null) {
      setState(() => _date = _fmtDate(picked));
      _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final gtype = '${_data?['group_type'] ?? ''}';
    final isCallback = gtype == 'callback';
    final summary = Map<String, dynamic>.from((_data?['summary'] as Map?) ?? {});
    final rows = ((_data?['rows'] as List?) ?? []);
    final techs = ((_data?['technicians'] as List?) ?? []);

    return _DashboardCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            Icon(Icons.today, color: isCallback ? Colors.red.shade700 : Colors.orange.shade800),
            const SizedBox(width: 8),
            Text(widget.fullSchedule ? 'Full · Daily Supervisor Report' : 'Daily Supervisor Report',
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            if (gtype.isNotEmpty) ...[
              const SizedBox(width: 10),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(color: Colors.blue.shade50, borderRadius: BorderRadius.circular(6)),
                child: Text('$gtype HQ', style: TextStyle(color: Colors.blue.shade800, fontSize: 11)),
              ),
            ],
            const Spacer(),
            SizedBox(
              width: 280,
              child: TextField(
                controller: _searchCtrl,
                decoration: const InputDecoration(
                  hintText: 'Search unit / tech / task...',
                  isDense: true,
                  prefixIcon: Icon(Icons.search, size: 18),
                  border: OutlineInputBorder(),
                ),
                onSubmitted: (v) { _search = v.trim(); _load(); },
              ),
            ),
            const SizedBox(width: 10),
            IconButton(onPressed: _load, icon: const Icon(Icons.refresh)),
            OutlinedButton.icon(
              onPressed: _pickDate,
              icon: const Icon(Icons.calendar_today, size: 16),
              label: Text(_date),
            ),
          ]),
          const SizedBox(height: 12),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _error != null
                    ? Center(child: Text('Error: $_error', style: const TextStyle(color: Colors.red)))
                    : ListView(
                        children: [
                          Text(
                            widget.fullSchedule
                                ? 'Full-day scope for $_date. Statuses use the generated daily plan.'
                                : 'Roll-date scope for $_date. Live statuses use the selected roll date/time.',
                            style: TextStyle(color: Colors.grey.shade600, fontSize: 12),
                          ),
                          const SizedBox(height: 12),
                          _summaryGrid(summary, isCallback),
                          const SizedBox(height: 10),
                          _filterRow(isCallback),
                          const SizedBox(height: 10),
                          if (isCallback)
                            _incidentTable(rows)
                          else
                            _technicianDailyBlocks(techs, rows),
                        ],
                      ),
          ),
        ],
      ),
    );
  }

  Widget _summaryGrid(Map<String, dynamic> s, bool isCallback) {
    final cards = isCallback
        ? [
            _DailyCard('Callbacks', _fmtNum(s['tasks']), Icons.warning_amber, Colors.red, subtitle: 'AA ${s['aa'] ?? 0} · B ${s['b'] ?? 0}'),
            _DailyCard('SLA success', _pctOrDash(s['sla_pct']), Icons.verified_outlined, Colors.green, subtitle: '${s['sla_met'] ?? 0}/${s['sla_total'] ?? 0} inside window'),
            _DailyCard('Avg response', _minOrDash(s['avg_response_min']), Icons.speed, Colors.orange, subtitle: 'reported → arrival'),
            _DailyCard('Unassigned', _fmtNum(s['unassigned']), Icons.report_problem_outlined, Colors.red, subtitle: 'callback backlog'),
            _DailyCard('Duty hours', '${_fmtDec(s['duty_hours'])} h', Icons.timer, Colors.teal, subtitle: 'service + travel'),
            _DailyCard('Travel / Route', '${_fmtDec(s['travel_hours'])} h', Icons.directions_car, Colors.blue, subtitle: '${_fmtDec(s['route_km'])} km'),
          ]
        : [
            _DailyCard('Maintenance tasks', _fmtNum(s['tasks']), Icons.fact_check_outlined, Colors.blue, subtitle: 'A ${s['a'] ?? 0} · B ${s['b'] ?? 0} · C ${s['c'] ?? 0}'),
            _DailyCard('Completed', _fmtNum(s['done']), Icons.check_circle_outline, Colors.green, subtitle: '${s['active'] ?? 0} active now'),
            _DailyCard('Remaining', _fmtNum(s['on_plan']), Icons.event_note, Colors.orange, subtitle: 'planned after roll time'),
            _DailyCard('Unassigned', _fmtNum(s['unassigned']), Icons.report_problem_outlined, Colors.red, subtitle: 'maintenance backlog'),
            _DailyCard('Service hours', '${_fmtDec(s['service_hours'])} h', Icons.timer, Colors.teal, subtitle: '${s['technicians'] ?? 0} technicians'),
            _DailyCard('Travel / Route', '${_fmtDec(s['travel_hours'])} h', Icons.directions_car, Colors.blue, subtitle: '${_fmtDec(s['route_km'])} km'),
          ];
    return GridView.count(
      crossAxisCount: 3,
      childAspectRatio: 4.4,
      crossAxisSpacing: 10,
      mainAxisSpacing: 10,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      children: cards,
    );
  }

  Widget _filterRow(bool isCallback) {
    final statuses = [
      ['all', 'All'],
      ['DONE', 'Done'],
      ['ON_ROUTE', 'On route'],
      ['ON_SITE', 'On site'],
      ['ON_PLAN', 'On plan'],
      ['UNASSIGNED', 'Unassigned'],
      if (isCallback) ['SLA_MISSED', 'SLA missed'],
      if (isCallback) ['SLA_MET', 'SLA met'],
    ];
    final types = isCallback
        ? [['all', 'All type'], ['AA', 'AA'], ['B', 'B']]
        : [['all', 'All type'], ['A', 'A'], ['B', 'B'], ['C', 'C']];
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final item in statuses)
          ChoiceChip(
            label: Text(item[1]),
            selected: _status == item[0],
            onSelected: (_) { setState(() => _status = item[0]); _load(); },
          ),
        const SizedBox(width: 12),
        for (final item in types)
          ChoiceChip(
            label: Text(item[1]),
            selected: _type == item[0],
            onSelected: (_) { setState(() => _type = item[0]); _load(); },
          ),
      ],
    );
  }

  Widget _incidentTable(List rows) {
    if (rows.isEmpty) return const _EmptyStateText('No callback incidents match the selected filters.');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _tableHeader(['Date', 'Unit', 'Priority', 'Technician', 'Reported', 'Scheduled', 'Response', 'SLA', 'Status', 'Travel']),
        for (final raw in rows)
          Builder(builder: (_) {
            final r = Map<String, dynamic>.from(raw as Map);
            final unassigned = r['is_unassigned'] == true;
            return Container(
              decoration: BoxDecoration(
                border: Border(bottom: BorderSide(color: Colors.grey.shade200)),
                color: unassigned ? Colors.red.shade50.withOpacity(.45) : null,
              ),
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              child: Row(children: [
                _cell('${r['date']}', flex: 1),
                _cellTitle('${r['unit']}', '${r['unit_code']} · ${r['task_no']}', flex: 3),
                Expanded(flex: 1, child: Align(alignment: Alignment.centerLeft, child: _typeBadge('${r['type']}', true))),
                _cell('${r['technician']}', flex: 2),
                _cell(_dash(r['reported']), flex: 1),
                _cell('${_dash(r['start'])}${r['end'] != null && '${r['end']}'.isNotEmpty ? '–${r['end']}' : ''}', flex: 2),
                _cell(_minOrDash(r['response_min']), flex: 1),
                Expanded(flex: 1, child: Align(alignment: Alignment.centerLeft, child: _slaChip(r['sla_met']))),
                Expanded(flex: 2, child: Align(alignment: Alignment.centerLeft, child: _statusChip('${r['status']}'))),
                _cell(_travelText(r), flex: 1),
              ]),
            );
          }),
      ],
    );
  }

  Widget _technicianDailyBlocks(List techs, List rows) {
    if (techs.isEmpty && rows.isEmpty) return const _EmptyStateText('No maintenance work matches the selected filters.');
    final unassigned = rows.where((r) => (r as Map)['is_unassigned'] == true).toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (unassigned.isNotEmpty) ...[
          Text('Unassigned maintenance backlog (${unassigned.length})',
              style: TextStyle(fontWeight: FontWeight.bold, color: Colors.red.shade800)),
          const SizedBox(height: 6),
          _maintenanceRows(unassigned.cast<Map>()),
          const SizedBox(height: 16),
        ],
        Text('Technician workload (${techs.length} techs)',
            style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
        const SizedBox(height: 8),
        for (final raw in techs)
          Builder(builder: (_) {
            final t = Map<String, dynamic>.from(raw as Map);
            final items = ((t['rows'] as List?) ?? []).cast<Map>();
            return ExpansionTile(
              tilePadding: EdgeInsets.zero,
              title: Text('${t['technician']}', style: const TextStyle(fontWeight: FontWeight.w600)),
              subtitle: Text('${t['stops']} stops · ${_fmtDec(t['duty_hours'])} duty h · ${_fmtDec(t['route_km'])} km'),
              trailing: _workloadSignal(t),
              children: [_maintenanceRows(items)],
            );
          }),
      ],
    );
  }

  Widget _maintenanceRows(List<Map> rows) {
    if (rows.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _tableHeader(['Date', 'Unit', 'Type', 'Time', 'Status', 'Travel']),
        for (final raw in rows)
          Builder(builder: (_) {
            final r = Map<String, dynamic>.from(raw);
            return Container(
              decoration: BoxDecoration(border: Border(bottom: BorderSide(color: Colors.grey.shade200))),
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
              child: Row(children: [
                _cell('${r['date']}', flex: 1),
                _cellTitle('${r['unit']}', '${r['unit_code']} · ${r['task_no']}', flex: 4),
                Expanded(flex: 1, child: Align(alignment: Alignment.centerLeft, child: _typeBadge('${r['type']}', false))),
                _cell('${_dash(r['start'])}${r['end'] != null && '${r['end']}'.isNotEmpty ? '–${r['end']}' : ''}', flex: 2),
                Expanded(flex: 2, child: Align(alignment: Alignment.centerLeft, child: _statusChip('${r['status']}'))),
                _cell(_travelText(r), flex: 1),
              ]),
            );
          }),
      ],
    );
  }

  Widget _tableHeader(List<String> labels) {
    final flexes = labels.length == 10
        ? [1, 3, 1, 2, 1, 2, 1, 1, 2, 1]
        : [1, 4, 1, 2, 2, 1];
    return Container(
      color: Colors.grey.shade100,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      child: Row(children: [
        for (int i = 0; i < labels.length; i++)
          Expanded(flex: flexes[i], child: Text(labels[i], style: const TextStyle(fontWeight: FontWeight.bold))),
      ]),
    );
  }

  Widget _cell(String text, {int flex = 1}) => Expanded(
        flex: flex,
        child: Text(text, style: const TextStyle(fontSize: 12), overflow: TextOverflow.ellipsis),
      );

  Widget _cellTitle(String title, String sub, {int flex = 2}) => Expanded(
        flex: flex,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13), overflow: TextOverflow.ellipsis),
          Text(sub, style: TextStyle(color: Colors.grey.shade600, fontSize: 11), overflow: TextOverflow.ellipsis),
        ]),
      );

  Widget _typeBadge(String text, bool callback) {
    final isAA = text == 'AA';
    final color = callback ? (isAA ? Colors.red : Colors.purple) : Colors.green;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(color: color.shade500, borderRadius: BorderRadius.circular(5)),
      child: Text(callback ? 'CB $text' : text, style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.bold)),
    );
  }

  Widget _slaChip(dynamic met) {
    if (met == true) return _smallChip('SLA YES', Colors.green);
    if (met == false) return _smallChip('SLA NO', Colors.red);
    return Text('N/A', style: TextStyle(color: Colors.grey.shade500, fontSize: 12));
  }

  Widget _statusChip(String status) {
    final s = status.toUpperCase();
    if (s == 'DONE') return _smallChip('Done', Colors.green);
    if (s == 'ON_ROUTE') return _smallChip('On route', Colors.orange);
    if (s == 'ON_SITE') return _smallChip('On site', Colors.blue);
    if (s == 'ON_PLAN') return _smallChip('On plan', Colors.grey);
    if (s == 'UNASSIGNED') return _smallChip('Unassigned', Colors.red);
    return _smallChip(status, Colors.grey);
  }

  Widget _smallChip(String text, MaterialColor color) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(
          color: color.shade50,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: color.shade200),
        ),
        child: Text(text, style: TextStyle(color: color.shade800, fontSize: 11, fontWeight: FontWeight.w600)),
      );

  Widget _workloadSignal(Map<String, dynamic> t) {
    final duty = _toDouble(t['duty_hours']);
    MaterialColor c = Colors.green;
    String label = 'Balanced';
    if (duty < 5) { c = Colors.orange; label = 'Low'; }
    if (duty > 8.5) { c = Colors.red; label = 'High'; }
    return _smallChip('$label · ${_fmtDec(duty)} h', c);
  }

  String _travelText(Map<String, dynamic> r) {
    final min = r['travel_min'];
    final km = r['route_km'];
    final minText = min == null ? '—' : '${min}m';
    final kmVal = _toDouble(km);
    final kmText = km == null || kmVal <= 0 ? '— km' : '${_fmtDec(kmVal)} km';
    return '$minText · $kmText';
  }

  String _dash(dynamic v) {
    final text = '${v ?? ''}'.trim();
    return text.isEmpty ? '—' : text;
  }

  String _fmtNum(dynamic v) => '${v ?? 0}';
  double _toDouble(dynamic v) { try { return v == null ? 0 : (v as num).toDouble(); } catch (_) { return double.tryParse('$v') ?? 0; } }
  String _fmtDec(dynamic v) {
    final d = _toDouble(v);
    if (d == 0) return '0';
    if ((d - d.round()).abs() < .05) return '${d.round()}';
    return d.toStringAsFixed(1);
  }
  String _pctOrDash(dynamic v) => v == null ? 'N/A' : '${_fmtDec(v)}%';
  String _minOrDash(dynamic v) => v == null ? '—' : '${v}m';
}

class _DailyCard extends StatelessWidget {
  final String title;
  final String value;
  final IconData icon;
  final MaterialColor color;
  final String subtitle;
  const _DailyCard(this.title, this.value, this.icon, this.color, {required this.subtitle});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: color.shade50,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.shade200),
      ),
      child: Row(children: [
        CircleAvatar(backgroundColor: color.shade100, child: Icon(icon, color: color.shade700, size: 19)),
        const SizedBox(width: 12),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.center, children: [
          Text(title, style: TextStyle(color: Colors.grey.shade700, fontSize: 12)),
          Text(value, style: TextStyle(color: color.shade900, fontSize: 20, fontWeight: FontWeight.bold)),
          Text(subtitle, style: TextStyle(color: Colors.grey.shade600, fontSize: 11), overflow: TextOverflow.ellipsis),
        ])),
      ]),
    );
  }
}

class _EmptyStateText extends StatelessWidget {
  final String text;
  const _EmptyStateText(this.text);
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(22),
        child: Center(child: Text(text, style: TextStyle(color: Colors.grey.shade600))),
      );
}

// ---------------------------------------------------- Dispatch (real-time callback)
class DispatchTab extends StatefulWidget {
  final DashboardController controller;
  const DispatchTab({super.key, required this.controller});
  @override
  State<DispatchTab> createState() => _DispatchTabState();
}

class _DispatchTabState extends State<DispatchTab> {
  final TextEditingController _unitSearchCtrl = TextEditingController();
  final TextEditingController _descCtrl = TextEditingController();
  String _priority = 'NORMAL';
  bool _dispatching = false;
  bool _loadingUnits = true;
  DispatchResult? _result;
  String? _error;
  List<DispatchUnitOption> _units = [];
  DispatchUnitOption? _selectedUnit;

  @override
  void initState() {
    super.initState();
    _loadUnits();
    _unitSearchCtrl.addListener(() => setState(() {}));
  }

  Future<void> _loadUnits() async {
    setState(() { _loadingUnits = true; _error = null; });
    try {
      final units = await widget.controller.fetchDispatchUnits();
      setState(() {
        _units = units;
        _loadingUnits = false;
        if (_selectedUnit != null && !_units.any((u) => u.id == _selectedUnit!.id)) {
          _selectedUnit = null;
        }
      });
    } catch (e) {
      setState(() { _error = e.toString(); _loadingUnits = false; });
    }
  }

  @override
  void dispose() {
    _unitSearchCtrl.dispose();
    _descCtrl.dispose();
    super.dispose();
  }

  List<DispatchUnitOption> get _filteredUnits {
    final q = _unitSearchCtrl.text.trim().toLowerCase();
    var list = _units;
    if (q.isNotEmpty) {
      list = list.where((u) {
        return u.name.toLowerCase().contains(q)
            || u.code.toLowerCase().contains(q)
            || u.address.toLowerCase().contains(q)
            || u.city.toLowerCase().contains(q);
      }).toList();
    }
    list.sort((a, b) {
      final backlogCmp = b.unassignedCallbackCount.compareTo(a.unassignedCallbackCount);
      if (backlogCmp != 0) return backlogCmp;
      return a.name.compareTo(b.name);
    });
    return list.take(12).toList();
  }

  Future<void> _dispatch() async {
    if (_selectedUnit == null) {
      setState(() { _error = 'Select an existing unit before dispatching.'; });
      return;
    }
    setState(() { _dispatching = true; _error = null; _result = null; });
    try {
      final res = await widget.controller.dispatch(
        unitId: _selectedUnit!.id,
        priority: _priority,
        faultType: _priority == 'AA' ? 'Elevator Entrapment' : 'Elevator Fault',
        description: _descCtrl.text.trim(),
      );
      setState(() { _result = res; _dispatching = false; });
    } catch (e) {
      setState(() { _error = e.toString(); _dispatching = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    final filtered = _filteredUnits;
    return _DashboardCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            Icon(Icons.send, color: Colors.deepOrange.shade700),
            const SizedBox(width: 8),
            const Text('Dispatch Callback',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
          ]),
          const SizedBox(height: 6),
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: Colors.blue.shade50,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.blue.shade200),
            ),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Icon(Icons.info_outline, size: 16, color: Colors.blue.shade800),
              const SizedBox(width: 8),
              Expanded(child: Text(
                'Select an existing portfolio unit. Dispatch uses the unit\'s saved coordinates, then assigns the nearest / lowest-added-route callback technician.',
                style: TextStyle(fontSize: 12, color: Colors.blue.shade900))),
            ]),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _unitSearchCtrl,
            decoration: InputDecoration(
              labelText: 'Search existing unit by name, code, address...',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: IconButton(
                tooltip: 'Reload units',
                onPressed: _loadUnits,
                icon: const Icon(Icons.refresh),
              ),
              isDense: true,
              border: const OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 8),
          if (_loadingUnits)
            const LinearProgressIndicator(minHeight: 3)
          else
            Container(
              constraints: const BoxConstraints(maxHeight: 260),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: Colors.grey.shade300),
              ),
              child: filtered.isEmpty
                  ? const Padding(
                      padding: EdgeInsets.all(16),
                      child: Text('No existing units match this search.'),
                    )
                  : ListView.separated(
                      shrinkWrap: true,
                      itemCount: filtered.length,
                      separatorBuilder: (_, __) => Divider(height: 1, color: Colors.grey.shade200),
                      itemBuilder: (context, i) {
                        final u = filtered[i];
                        final selected = _selectedUnit?.id == u.id;
                        return ListTile(
                          dense: true,
                          selected: selected,
                          selectedTileColor: Colors.blue.shade50,
                          leading: CircleAvatar(
                            radius: 16,
                            backgroundColor: selected ? Colors.blue.shade700 : Colors.grey.shade200,
                            child: Icon(Icons.business, size: 17, color: selected ? Colors.white : Colors.grey.shade700),
                          ),
                          title: Text(u.name, style: const TextStyle(fontWeight: FontWeight.w700)),
                          subtitle: Text([
                            u.code,
                            u.unitType,
                            if (u.city.isNotEmpty) u.city,
                            '${u.latitude.toStringAsFixed(5)}, ${u.longitude.toStringAsFixed(5)}',
                          ].where((x) => x.isNotEmpty).join(' · ')),
                          trailing: Wrap(spacing: 6, children: [
                            if (u.unassignedCallbackCount > 0)
                              Chip(
                                label: Text('${u.unassignedCallbackCount} backlog'),
                                visualDensity: VisualDensity.compact,
                                backgroundColor: Colors.red.shade50,
                                labelStyle: TextStyle(fontSize: 11, color: Colors.red.shade800, fontWeight: FontWeight.w700),
                              ),
                            if (u.callbackCount > 0)
                              Chip(
                                label: Text('${u.callbackCount} cb'),
                                visualDensity: VisualDensity.compact,
                                backgroundColor: Colors.purple.shade50,
                                labelStyle: TextStyle(fontSize: 11, color: Colors.purple.shade800),
                              ),
                          ]),
                          onTap: () => setState(() => _selectedUnit = u),
                        );
                      },
                    ),
            ),
          if (_selectedUnit != null) ...[
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.green.shade50,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: Colors.green.shade200),
              ),
              child: Row(children: [
                Icon(Icons.location_on, color: Colors.green.shade700),
                const SizedBox(width: 8),
                Expanded(child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(_selectedUnit!.name, style: const TextStyle(fontWeight: FontWeight.w800)),
                    Text('Using saved unit location: ${_selectedUnit!.latitude.toStringAsFixed(5)}, ${_selectedUnit!.longitude.toStringAsFixed(5)}',
                        style: TextStyle(fontSize: 12, color: Colors.grey.shade700)),
                  ],
                )),
              ]),
            ),
          ],
          const SizedBox(height: 12),
          Row(children: [
            const Text('Priority:', style: TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(width: 12),
            ChoiceChip(
              label: const Text('AA — Entrapment (1hr)'),
              selected: _priority == 'AA',
              selectedColor: Colors.red.shade100,
              onSelected: (_) => setState(() => _priority = 'AA'),
            ),
            const SizedBox(width: 8),
            ChoiceChip(
              label: const Text('Normal B (4hr)'),
              selected: _priority == 'NORMAL',
              onSelected: (_) => setState(() => _priority = 'NORMAL'),
            ),
          ]),
          const SizedBox(height: 12),
          TextField(
            controller: _descCtrl,
            decoration: const InputDecoration(
              labelText: 'Fault description (optional)',
              isDense: true, border: OutlineInputBorder()),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: (_dispatching || _selectedUnit == null) ? null : _dispatch,
            icon: _dispatching
                ? const SizedBox(height: 16, width: 16,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : const Icon(Icons.send, size: 18),
            label: Text(_selectedUnit == null ? 'Select a unit first' : 'Dispatch to nearest technician'),
            style: FilledButton.styleFrom(
              backgroundColor: Colors.deepOrange.shade700,
              minimumSize: const Size(0, 48),
            ),
          ),
          const SizedBox(height: 16),
          if (_error != null)
            Text('Dispatch failed: $_error', style: const TextStyle(color: Colors.red)),
          if (_result != null) _resultCard(_result!),
        ],
      ),
    );
  }

  Widget _resultCard(DispatchResult r) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.green.shade50,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.green.shade200),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(Icons.check_circle, color: Colors.green.shade700),
            const SizedBox(width: 8),
            Text('Dispatched — ${r.taskNo}',
                style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
          ]),
          const SizedBox(height: 8),
          if (r.unitName.isNotEmpty)
            Text('Unit: ${r.unitName}', style: const TextStyle(fontWeight: FontWeight.w600)),
          Text('Assigned to: ${r.assignedToName}',
              style: const TextStyle(fontWeight: FontWeight.w600)),
          Text('Priority: ${r.priority}', style: TextStyle(color: Colors.grey.shade700)),
          if (r.reason.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(r.reason, style: TextStyle(color: Colors.grey.shade700, fontSize: 13)),
            ),
          if (r.scoreboard.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text('Candidate ranking', style: TextStyle(fontWeight: FontWeight.w700, color: Colors.grey.shade800)),
            const SizedBox(height: 4),
            ...r.scoreboard.take(5).map((row) => Text(
              '${row['name']}  +${row['km_from_dispatch'] ?? row['added_km']} km',
              style: TextStyle(fontSize: 12, color: Colors.grey.shade700),
            )),
          ],
        ],
      ),
    );
  }
}

class _DashboardCard extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  const _DashboardCard({
    required this.child,
    this.padding = const EdgeInsets.all(20),
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.05),
            blurRadius: 10,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      padding: padding,
      child: child,
    );
  }
}
// =============================================================================
//  Leave Requests view — supervisor approves / rejects technician leave
// =============================================================================

class LeaveRequestItem {
  final int id;
  final String technician;
  final String leaveType;
  final String startDate;
  final String endDate;
  final String reason;
  final String status; // PENDING / APPROVED / REJECTED / RETURNED

  LeaveRequestItem({
    required this.id,
    required this.technician,
    required this.leaveType,
    required this.startDate,
    required this.endDate,
    required this.reason,
    required this.status,
  });

  factory LeaveRequestItem.fromJson(Map<String, dynamic> j) => LeaveRequestItem(
        id: j['id'] as int,
        technician: j['technician'] ?? '?',
        leaveType: j['leave_type'] ?? 'Leave',
        startDate: j['start_date'] ?? '',
        endDate: j['end_date'] ?? '',
        reason: j['reason'] ?? '',
        status: j['status'] ?? 'PENDING',
      );
}

class LeaveRequestsView extends StatefulWidget {
  final DateTime activeDate;    // operating-clock "today"
  final VoidCallback onChanged; // refresh the dashboard after a decision
  const LeaveRequestsView({super.key, required this.activeDate, required this.onChanged});

  @override
  State<LeaveRequestsView> createState() => _LeaveRequestsViewState();
}

class _LeaveRequestsViewState extends State<LeaveRequestsView> {
  final ApiClient _api = ApiClient();
  List<LeaveRequestItem> _items = [];
  bool _loading = true;
  String? _error;
  int? _busyId;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final items = await _api.fetchLeaveRequests();
      if (!mounted) return;
      setState(() {
        _items = items;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _decide(LeaveRequestItem item, String decision) async {
    setState(() => _busyId = item.id);
    try {
      await _api.decideLeave(item.id, decision);
      widget.onChanged(); // dashboard re-pulls -> On Leave badge updates
      await _load();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed: $e'), backgroundColor: Colors.red.shade700),
        );
      }
    } finally {
      if (mounted) setState(() => _busyId = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final pending = _items.where((i) => i.status == 'PENDING').toList();
    final decided = _items.where((i) => i.status != 'PENDING').toList();

    return SingleChildScrollView(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 820),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  const Text('Leave Requests',
                      style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
                  const SizedBox(width: 12),
                  if (pending.isNotEmpty)
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(
                        color: Colors.orange.shade100,
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Text('${pending.length} pending',
                          style: TextStyle(
                              color: Colors.orange.shade900,
                              fontWeight: FontWeight.bold,
                              fontSize: 12)),
                    ),
                  const Spacer(),
                  IconButton(
                    onPressed: _loading ? null : _load,
                    icon: const Icon(Icons.refresh),
                    tooltip: 'Refresh',
                  ),
                ],
              ),
              const SizedBox(height: 8),

              if (!_loading && _error == null && _items.isNotEmpty)
                _absenceOverview(),

              if (_loading)
                const Padding(
                  padding: EdgeInsets.all(40),
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (_error != null)
                _DashboardCard(
                  child: Text('Could not load: $_error',
                      style: TextStyle(color: Colors.red.shade700)),
                )
              else if (_items.isEmpty)
                _DashboardCard(
                  child: Column(
                    children: [
                      Icon(Icons.event_available, size: 40, color: Colors.grey.shade400),
                      const SizedBox(height: 8),
                      Text('No leave requests yet.',
                          style: TextStyle(color: Colors.grey.shade600)),
                    ],
                  ),
                )
              else ...[
                if (pending.isNotEmpty) ...[
                  const Padding(
                    padding: EdgeInsets.only(top: 8, bottom: 6),
                    child: Text('Pending your approval',
                        style: TextStyle(fontWeight: FontWeight.bold, color: Colors.black54)),
                  ),
                  for (final item in pending) _card(item, actionable: true),
                ],
                if (decided.isNotEmpty) ...[
                  const Padding(
                    padding: EdgeInsets.only(top: 16, bottom: 6),
                    child: Text('History',
                        style: TextStyle(fontWeight: FontWeight.bold, color: Colors.black54)),
                  ),
                  for (final item in decided) _card(item, actionable: false),
                ],
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _absenceOverview() {
    // "Today" is the operating clock, not the device clock — otherwise a leave
    // that starts on the operating day (e.g. 6 July) is wrongly shown as upcoming.
    final ad = widget.activeDate;
    final today = DateTime(ad.year, ad.month, ad.day, 12);
    DateTime? parse(String s) => DateTime.tryParse(s);

    final approved = _items.where((i) => i.status == 'APPROVED').toList();
    final away = <LeaveRequestItem>[];
    final upcoming = <LeaveRequestItem>[];
    for (final i in approved) {
      final s = parse(i.startDate);
      final e = parse(i.endDate);
      if (s == null || e == null) continue;
      final endInclusive = DateTime(e.year, e.month, e.day, 23, 59);
      if (!today.isBefore(s) && !today.isAfter(endInclusive)) {
        away.add(i);
      } else if (today.isBefore(s)) {
        upcoming.add(i);
      }
    }
    away.sort((a, b) => a.endDate.compareTo(b.endDate));
    upcoming.sort((a, b) => a.startDate.compareTo(b.startDate));

    if (away.isEmpty && upcoming.isEmpty) return const SizedBox.shrink();

    Widget chip(LeaveRequestItem i, Color c) => Container(
          margin: const EdgeInsets.only(right: 8, bottom: 8),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: c.withOpacity(0.10),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: c.withOpacity(0.35)),
          ),
          child: Text('${i.technician}  ·  ${i.startDate} → ${i.endDate}',
              style: TextStyle(fontSize: 12, color: c, fontWeight: FontWeight.w600)),
        );

    return _DashboardCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(Icons.beach_access, size: 18, color: Colors.indigo.shade400),
            const SizedBox(width: 8),
            const Text('Team Absences',
                style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
          ]),
          const SizedBox(height: 12),
          Text('Currently away (${away.length})',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold,
                  color: Colors.red.shade700)),
          const SizedBox(height: 6),
          if (away.isEmpty)
            Text('Nobody is on leave today.',
                style: TextStyle(fontSize: 12, color: Colors.grey.shade500))
          else
            Wrap(children: [for (final i in away) chip(i, Colors.red.shade700)]),
          const SizedBox(height: 14),
          Text('Upcoming leaves (${upcoming.length})',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold,
                  color: Colors.orange.shade800)),
          const SizedBox(height: 6),
          if (upcoming.isEmpty)
            Text('No upcoming approved leaves.',
                style: TextStyle(fontSize: 12, color: Colors.grey.shade500))
          else
            Wrap(children: [for (final i in upcoming) chip(i, Colors.orange.shade800)]),
        ],
      ),
    );
  }

  Widget _statusBadge(String status) {
    Color bg, fg;
    switch (status) {
      case 'APPROVED':
        bg = Colors.green.shade50;
        fg = Colors.green.shade800;
        break;
      case 'REJECTED':
        bg = Colors.red.shade50;
        fg = Colors.red.shade700;
        break;
      case 'RETURNED':
        bg = Colors.blue.shade50;
        fg = Colors.blue.shade800;
        break;
      default:
        bg = Colors.orange.shade50;
        fg = Colors.orange.shade900;
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(8)),
      child: Text(status,
          style: TextStyle(color: fg, fontSize: 11, fontWeight: FontWeight.bold)),
    );
  }

  Widget _card(LeaveRequestItem item, {required bool actionable}) {
    final busy = _busyId == item.id;
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      child: _DashboardCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                CircleAvatar(
                  radius: 18,
                  backgroundColor: Colors.indigo.shade50,
                  child: Text(
                    item.technician.isNotEmpty ? item.technician[0] : '?',
                    style: TextStyle(color: Colors.indigo.shade700, fontWeight: FontWeight.bold),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(item.technician,
                          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
                      Text('${item.leaveType} · ${item.startDate} → ${item.endDate}',
                          style: TextStyle(color: Colors.grey.shade600, fontSize: 13)),
                    ],
                  ),
                ),
                _statusBadge(item.status),
              ],
            ),
            if (item.reason.isNotEmpty) ...[
              const SizedBox(height: 10),
              Text(item.reason, style: TextStyle(color: Colors.grey.shade700, fontSize: 13)),
            ],
            if (actionable) ...[
              const SizedBox(height: 14),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: busy ? null : () => _decide(item, 'REJECT'),
                    style: TextButton.styleFrom(foregroundColor: Colors.red.shade700),
                    child: const Text('Reject'),
                  ),
                  const SizedBox(width: 8),
                  ElevatedButton.icon(
                    onPressed: busy ? null : () => _decide(item, 'APPROVE'),
                    icon: busy
                        ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                        : const Icon(Icons.check, size: 18),
                    label: const Text('Approve'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.green.shade700,
                      foregroundColor: Colors.white,
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}