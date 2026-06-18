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
  final String state; // done / current / upcoming

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
      );
}

class DispatchResult {
  final String assignedToName;
  final String assignedToUsername;
  final String taskNo;
  final String priority;
  final double unitLat;
  final double unitLng;
  final String reason;
  final List<Map<String, dynamic>> scoreboard;

  DispatchResult({
    required this.assignedToName,
    required this.assignedToUsername,
    required this.taskNo,
    required this.priority,
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

  Future<DispatchResult> dispatchTask({
    required double latitude,
    required double longitude,
    required String priority,
    required String faultType,
    String description = '',
  }) async {
    final r = await http.post(
      Uri.parse('$kBaseUrl/api/repair/dispatch/'),
      headers: _headers,
      body: jsonEncode({
        'latitude': latitude,
        'longitude': longitude,
        'priority': priority,
        'fault_type': faultType,
        'description': description,
      }),
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
  }) async {
    final r = await http.post(
      Uri.parse('$kBaseUrl/api/technicians/add/'),
      headers: _headers,
      body: jsonEncode({
        'full_name': fullName,
        'tech_role': techRole,
        'specialty': specialty,
      }),
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
      {String asOf = ''}) async {
    final base = '$kBaseUrl/api/reports/monthly/?year=$year&month=$month';
    final r = await http.get(
      Uri.parse(asOf.isNotEmpty ? '$base&as_of=$asOf' : base),
      headers: _headers,
    );
    if (r.statusCode != 200) {
      throw Exception('GET /api/reports/monthly/ -> ${r.statusCode}: ${r.body}');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  String exportUrl(int year, int month) =>
      '$kBaseUrl/api/reports/monthly/export/?year=$year&month=$month';

  Future<Map<String, dynamic>> fetchUnitHistorySummary(
      {String search = '', int page = 1, int pageSize = 50, String asOf = ''}) async {
    final uri = Uri.parse('$kBaseUrl/api/units/history/').replace(
        queryParameters: {
          if (search.isNotEmpty) 'search': search,
          'page': '$page',
          'page_size': '$pageSize',
          if (asOf.isNotEmpty) 'as_of': asOf,
        });
    final r = await http.get(uri, headers: _headers);
    if (r.statusCode != 200) {
      throw Exception('GET /api/units/history/ -> ${r.statusCode}: ${r.body}');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> fetchUnitHistoryDetail(int unitId,
      {String asOf = ''}) async {
    final base = '$kBaseUrl/api/units/$unitId/history/';
    final r = await http.get(
      Uri.parse(asOf.isNotEmpty ? '$base?as_of=$asOf' : base),
      headers: _headers,
    );
    if (r.statusCode != 200) {
      throw Exception('GET /api/units/$unitId/history/ -> ${r.statusCode}: ${r.body}');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  String unitHistoryExportUrl() => '$kBaseUrl/api/units/history/export/';

  Future<Map<String, dynamic>> fetchMaintenanceOverview(
      {String type = '', String search = '', int page = 1, String asOf = ''}) async {
    final uri = Uri.parse('$kBaseUrl/api/overview/maintenance/').replace(
        queryParameters: {
          if (type.isNotEmpty) 'type': type,
          if (search.isNotEmpty) 'search': search,
          'page': '$page',
          if (asOf.isNotEmpty) 'as_of': asOf,
        });
    final r = await http.get(uri, headers: _headers);
    if (r.statusCode != 200) {
      throw Exception('GET maintenance overview -> ${r.statusCode}: ${r.body}');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> fetchCallbackOverview(
      {String priority = '', String search = '', int page = 1, String asOf = ''}) async {
    final uri = Uri.parse('$kBaseUrl/api/overview/callbacks/').replace(
        queryParameters: {
          if (priority.isNotEmpty) 'priority': priority,
          if (search.isNotEmpty) 'search': search,
          'page': '$page',
          if (asOf.isNotEmpty) 'as_of': asOf,
        });
    final r = await http.get(uri, headers: _headers);
    if (r.statusCode != 200) {
      throw Exception('GET callback overview -> ${r.statusCode}: ${r.body}');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> fetchMonthlyLog(
      int year, int month, {int page = 1, String asOf = ''}) async {
    final uri = Uri.parse('$kBaseUrl/api/overview/monthly-log/').replace(
        queryParameters: {
          'year': '$year', 'month': '$month', 'page': '$page',
          if (asOf.isNotEmpty) 'as_of': asOf,
        });
    final r = await http.get(uri, headers: _headers);
    if (r.statusCode != 200) {
      throw Exception('GET monthly log -> ${r.statusCode}: ${r.body}');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> fetchDailyReport(
      {String date = '', String technicianId = '', String asOf = ''}) async {
    final uri = Uri.parse('$kBaseUrl/api/overview/daily-report/').replace(
        queryParameters: {
          if (date.isNotEmpty) 'date': date,
          if (technicianId.isNotEmpty) 'technician_id': technicianId,
          if (asOf.isNotEmpty) 'as_of': asOf,
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

  Future<DispatchResult> dispatch({
    required double latitude,
    required double longitude,
    required String priority,
    required String faultType,
    String description = '',
  }) async {
    final result = await _api.dispatchTask(
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
          (st) => LiveMapView(state: st)),

      _TabDef(const _NavItem(Icons.auto_awesome_outlined, Icons.auto_awesome, 'Generate Schedule'),
          (st) => GenerateScheduleTab(baseUrl: kBaseUrl, token: kSupervisorToken)),    
      _TabDef(const _NavItem(Icons.engineering_outlined, Icons.engineering, 'Technicians'),
          (st) => TechniciansView(state: st, onChanged: () => _controller.refresh())),
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
          (st) => DailyReportTab(activeDate: st.activeDate)),
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
          (st) => DailyReportTab(activeDate: st.activeDate, fullSchedule: true)),
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
  const LiveMapView({super.key, required this.state});

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
                          : 'No Google-routed technicians to show yet.\n'
                              'All $totalFleet are still scheduled '
                              '(visible in the console).',
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

class _TechniciansSidePanel extends StatefulWidget {
  final List<TechnicianState> technicians;
  final Color Function(TechnicianState) colorFor;
  final int? selectedTechId;
  final void Function(int id) onSelect;
  const _TechniciansSidePanel({
    required this.technicians,
    required this.colorFor,
    required this.selectedTechId,
    required this.onSelect,
  });

  @override
  State<_TechniciansSidePanel> createState() => _TechniciansSidePanelState();
}

class _TechniciansSidePanelState extends State<_TechniciansSidePanel> {
  String _query = '';
  String _roleFilter = 'ALL';      // ALL / MAINTENANCE / CALLBACK
  String _specFilter = 'ALL';      // ALL / ELEVATOR / ESCALATOR / BOTH (only under Maintenance)

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
    bool saving = false;
    String? err;

    await showDialog<void>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('Add Technician'),
          content: SizedBox(
            width: 360,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
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
                if (err != null) ...[
                  const SizedBox(height: 10),
                  Text(err!, style: const TextStyle(color: Colors.red, fontSize: 12)),
                ],
              ],
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
                        );
                        if (ctx.mounted) Navigator.pop(ctx);
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
                  : const Text('Add'),
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
              IconButton(
                tooltip: 'Add technician',
                icon: Icon(Icons.person_add_alt_1, color: Colors.blue.shade800, size: 20),
                onPressed: () => _showAddTechnicianDialog(context),
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
                          child: Text(
                            s.unitName,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(fontSize: 12),
                          ),
                        ),
                        if (s.priority == 'AA')
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

class MonthlyReportView extends StatefulWidget {
  final DateTime activeDate;   // operating-clock day; nothing past it is shown
  final bool fullSchedule;     // true = ignore the clamp, show the whole plan
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

  @override
  void initState() {
    super.initState();
    _loadMonths();
  }

  Future<void> _loadMonths() async {
    setState(() { _loading = true; _error = null; });
    try {
      final months = await _api.fetchReportMonths(
          asOf: widget.fullSchedule ? kFullAsOf : '');
      if (widget.fullSchedule) {
        // full plan: show every month the schedule covers, no future-hide
        _months = months;
      } else {
        // Hide any month after the operating-clock month — the frontend must not
        // reveal the future. (The console can still query later months directly.)
        final ad = widget.activeDate;
        _months = months.where((m) {
          final y = (m['year'] as num).toInt();
          final mo = (m['month'] as num).toInt();
          return y < ad.year || (y == ad.year && mo <= ad.month);
        }).toList();
      }
      if (_months.isNotEmpty) {
        _selectedMonth = _months.last; // operating month (latest visible)
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
          asOf: widget.fullSchedule ? kFullAsOf : '');
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
            _selectedMonth!['year'], _selectedMonth!['month'])),
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
      html.AnchorElement(href: url)
        ..setAttribute('download', 'report_$label.xlsx')
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
              const Text('Monthly Report',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const Spacer(),
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
          const SizedBox(height: 16),
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
        child: Text('No schedule data yet. Run a month of solves first.',
            style: TextStyle(color: Colors.grey)),
      );
    }
    final techs = ((_report?['technicians'] as List?) ?? []);
    if (techs.isEmpty) {
      return const Center(
        child: Text('No maintenance activity for this month.',
            style: TextStyle(color: Colors.grey)),
      );
    }
    return ListView(
      children: [
        // summary header row
        Container(
          padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
          color: Colors.grey.shade100,
          child: Row(
            children: const [
              Expanded(flex: 3, child: Text('Technician',
                  style: TextStyle(fontWeight: FontWeight.bold))),
              Expanded(child: Text('Days',
                  style: TextStyle(fontWeight: FontWeight.bold))),
              Expanded(child: Text('Buildings',
                  style: TextStyle(fontWeight: FontWeight.bold))),
              Expanded(child: Text('Hours',
                  style: TextStyle(fontWeight: FontWeight.bold))),
              SizedBox(width: 24),
            ],
          ),
        ),
        for (final t in techs) _techRow(Map<String, dynamic>.from(t as Map)),
      ],
    );
  }

  Widget _techRow(Map<String, dynamic> t) {
    final expanded = _expandedTechId == t['id'];
    return Column(
      children: [
        InkWell(
          onTap: () => setState(
              () => _expandedTechId = expanded ? null : t['id'] as int),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 12),
            child: Row(
              children: [
                Expanded(flex: 3, child: Text(t['name'].toString(),
                    style: const TextStyle(fontWeight: FontWeight.w600))),
                Expanded(child: Text('${t['days_worked']}')),
                Expanded(child: Text('${t['buildings_visited']}')),
                Expanded(child: Text('${t['total_hours']} h')),
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
          for (final dRaw in days)
            _dayBlock(Map<String, dynamic>.from(dRaw as Map)),
        ],
      ),
    );
  }

  Widget _dayBlock(Map<String, dynamic> day) {
    final visits = ((day['visits'] as List?) ?? []);
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
              Text('${day['buildings']} buildings · '
                  '${(day['work_minutes'] / 60).toStringAsFixed(1)} h · '
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
    return Padding(
      padding: const EdgeInsets.only(left: 12, top: 2),
      child: Row(
        children: [
          SizedBox(
            width: 110,
            child: Text('${v['start']}–${v['end'] ?? '—'}',
                style: const TextStyle(
                    fontFeatures: [], fontSize: 12, color: Colors.black87)),
          ),
          Container(
            margin: const EdgeInsets.only(right: 8),
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
            decoration: BoxDecoration(
              color: _typeColor(v['maintenance_type']),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text('${v['maintenance_type'] ?? '?'}',
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
        ],
      ),
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
}

// =============================================================================
//  Unit History view — per-unit maintenance + callback history (group-scoped)
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

  // detail panel
  int? _openUnitId;
  Map<String, dynamic>? _detail;
  bool _detailLoading = false;

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
          search: _search, page: _page, pageSize: 50,
          asOf: widget.fullSchedule ? kFullAsOf : '');
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
      final d = await _api.fetchUnitHistoryDetail(unitId,
          asOf: widget.fullSchedule ? kFullAsOf : '');
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
        Uri.parse(_api.unitHistoryExportUrl()),
        headers: {'Authorization': 'Token $kSupervisorToken'},
      );
      if (r.statusCode != 200) throw Exception('Export failed: ${r.statusCode}');
      final blob = html.Blob([r.bodyBytes],
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
      final url = html.Url.createObjectUrlFromBlob(blob);
      html.AnchorElement(href: url)
        ..setAttribute('download', 'unit_history.xlsx')
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

  @override
  Widget build(BuildContext context) {
    final units = ((_summary?['units'] as List?) ?? []);
    final total = _summary?['total_units'] ?? 0;
    final gtype = _summary?['group_type'] ?? '';
    return _DashboardCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Icon(Icons.apartment, color: Colors.blue.shade800),
              const SizedBox(width: 8),
              const Text('Unit History',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(width: 10),
              if (gtype.toString().isNotEmpty)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: Colors.blue.shade50,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text('$gtype HQ',
                      style: TextStyle(color: Colors.blue.shade800, fontSize: 11)),
                ),
              const Spacer(),
              SizedBox(
                width: 220,
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
              FilledButton.icon(
                onPressed: _exporting ? null : _export,
                icon: _exporting
                    ? const SizedBox(height: 16, width: 16,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white))
                    : const Icon(Icons.download, size: 18),
                label: const Text('Export Excel'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text('$total units in your scope',
              style: TextStyle(color: Colors.grey[600], fontSize: 12)),
          const SizedBox(height: 12),
          Expanded(child: _buildBody(units)),
          if (!_loading && _error == null) _pager(total),
        ],
      ),
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
        child: Text('No unit history found. Run solve_month / solve_callbacks_year.',
            style: TextStyle(color: Colors.grey)));
    }
    return ListView(
      children: [
        Container(
          padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
          color: Colors.grey.shade100,
          child: Row(children: const [
            Expanded(flex: 4, child: Text('Unit',
                style: TextStyle(fontWeight: FontWeight.bold))),
            Expanded(flex: 2, child: Text('Maintenance',
                style: TextStyle(fontWeight: FontWeight.bold))),
            Expanded(flex: 2, child: Text('Callbacks',
                style: TextStyle(fontWeight: FontWeight.bold))),
            Expanded(flex: 2, child: Text('Last service',
                style: TextStyle(fontWeight: FontWeight.bold))),
            SizedBox(width: 24),
          ]),
        ),
        for (final uRaw in units)
          _unitRow(Map<String, dynamic>.from(uRaw as Map)),
      ],
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
                    Text('${u['name']}',
                        style: const TextStyle(fontWeight: FontWeight.w600),
                        overflow: TextOverflow.ellipsis),
                    Text('${u['code']}',
                        style: TextStyle(
                            fontSize: 11, color: Colors.grey.shade600)),
                  ],
                ),
              ),
              Expanded(flex: 2, child: Text('${u['maint']}')),
              Expanded(flex: 2, child: Text('${u['callback']}')),
              Expanded(flex: 2, child: Text('${u['last'] ?? '—'}',
                  style: const TextStyle(fontSize: 12))),
              Icon(open ? Icons.expand_less : Icons.expand_more,
                  size: 20, color: Colors.grey),
            ]),
          ),
        ),
        if (open) _detailPanel(),
        const Divider(height: 1),
      ],
    );
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
    if (visits.isEmpty) {
      return const Padding(
        padding: EdgeInsets.all(16),
        child: Text('No visits recorded.', style: TextStyle(color: Colors.grey)),
      );
    }
    return Container(
      color: Colors.blue.shade50.withOpacity(0.3),
      padding: const EdgeInsets.fromLTRB(24, 8, 12, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final vRaw in visits)
            _visitRow(Map<String, dynamic>.from(vRaw as Map)),
        ],
      ),
    );
  }

  Widget _visitRow(Map<String, dynamic> v) {
    final isCallback = v['kind'] == 'Callback';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(children: [
        SizedBox(width: 90, child: Text('${v['date']}',
            style: const TextStyle(fontSize: 12))),
        Container(
          margin: const EdgeInsets.only(right: 8),
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
          decoration: BoxDecoration(
            color: isCallback ? Colors.purple.shade400 : _typeColor(v['type']),
            borderRadius: BorderRadius.circular(4),
          ),
          child: Text(isCallback ? 'CB ${v['type']}' : '${v['type']}',
              style: const TextStyle(color: Colors.white, fontSize: 10,
                  fontWeight: FontWeight.bold)),
        ),
        SizedBox(width: 110, child: Text('${v['start']}–${v['end'] ?? '—'}',
            style: const TextStyle(fontSize: 12))),
        Expanded(child: Text('${v['technician'] ?? ''}',
            style: const TextStyle(fontSize: 12), overflow: TextOverflow.ellipsis)),
        Text('${v['duration_min']}m',
            style: TextStyle(color: Colors.grey.shade600, fontSize: 11)),
      ]),
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
    return _DashboardCard(
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
  String? _error;
  String _priority = '';
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
          priority: _priority, search: _search, page: _page,
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
    final breakdown = (_data?['breakdown'] as Map?) ?? {};
    return _DashboardCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            Icon(Icons.report_problem, color: Colors.purple.shade700),
            const SizedBox(width: 8),
            const Text('Repair / Callback Module',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const Spacer(),
            for (final p in ['', 'AA', 'A', 'B', 'C', 'D'])
              Padding(
                padding: const EdgeInsets.only(left: 6),
                child: ChoiceChip(
                  label: Text(p.isEmpty ? 'All' : p),
                  selected: _priority == p,
                  onSelected: (_) { setState(() { _priority = p; _page = 1; }); _load(); },
                ),
              ),
          ]),
          const SizedBox(height: 8),
          if (breakdown.isNotEmpty)
            Wrap(spacing: 8, children: [
              for (final e in breakdown.entries)
                Chip(label: Text('${e.key}: ${e.value}'),
                    backgroundColor: Colors.purple.shade50,
                    labelStyle: TextStyle(color: Colors.purple.shade800, fontSize: 12)),
            ]),
          const SizedBox(height: 8),
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
          Text('$total callbacks', style: TextStyle(color: Colors.grey[600], fontSize: 12)),
          const SizedBox(height: 8),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _error != null
                    ? Center(child: Text('Error: $_error', style: const TextStyle(color: Colors.red)))
                    : rows.isEmpty
                        ? const Center(child: Text('No callbacks found.', style: TextStyle(color: Colors.grey)))
                        : ListView(children: [_taskTable(rows)]),
          ),
          if (!_loading && _error == null)
            _pagerBar(total, _page, _data?['page_size'] ?? 50,
                _page > 1 ? () { setState(() => _page--); _load(); } : null,
                _page * (_data?['page_size'] ?? 50) < total ? () { setState(() => _page++); _load(); } : null),
        ],
      ),
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
  Map<String, dynamic>? _data;
  bool _loading = true;
  String? _error;
  late int _year;
  late int _month;
  int _page = 1;

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
      final d = await _api.fetchMonthlyLog(_year, _month, page: _page,
          asOf: widget.fullSchedule ? kFullAsOf : '');
      setState(() { _data = d; _loading = false; });
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    final rows = ((_data?['log'] as List?) ?? []);
    final total = _data?['total'] ?? 0;
    return _DashboardCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            Icon(Icons.calendar_month, color: Colors.teal.shade700),
            const SizedBox(width: 8),
            const Text('Monthly Tracking & Logs',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const Spacer(),
            DropdownButton<int>(
              value: _month,
              items: [
                for (int m = 1;
                    m <= (widget.fullSchedule
                        ? 12
                        : (_year == widget.activeDate.year
                            ? widget.activeDate.month
                            : 12));
                    m++)
                  DropdownMenuItem(value: m, child: Text('Month $m'))
              ],
              onChanged: (m) { setState(() { _month = m!; _page = 1; }); _load(); },
            ),
            const SizedBox(width: 8),
            DropdownButton<int>(
              value: _year,
              items: [
                for (int y = 2025;
                    y <= widget.activeDate.year + (widget.fullSchedule ? 1 : 0);
                    y++)
                  DropdownMenuItem(value: y, child: Text('$y'))
              ],
              onChanged: (y) {
                setState(() {
                  _year = y!;
                  // jumping to the operating year: don't allow a future month
                  if (!widget.fullSchedule &&
                      _year == widget.activeDate.year &&
                      _month > widget.activeDate.month) {
                    _month = widget.activeDate.month;
                  }
                  _page = 1;
                });
                _load();
              },
            ),
          ]),
          const SizedBox(height: 8),
          Text('$total tasks logged this month',
              style: TextStyle(color: Colors.grey[600], fontSize: 12)),
          const SizedBox(height: 8),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _error != null
                    ? Center(child: Text('Error: $_error', style: const TextStyle(color: Colors.red)))
                    : rows.isEmpty
                        ? const Center(child: Text('No tasks logged for this month.', style: TextStyle(color: Colors.grey)))
                        : ListView(children: [_taskTable(rows)]),
          ),
          if (!_loading && _error == null)
            _pagerBar(total, _page, _data?['page_size'] ?? 100,
                _page > 1 ? () { setState(() => _page--); _load(); } : null,
                _page * (_data?['page_size'] ?? 100) < total ? () { setState(() => _page++); _load(); } : null),
        ],
      ),
    );
  }
}

// ---------------------------------------------------- Daily Report
class DailyReportTab extends StatefulWidget {
  final DateTime activeDate;   // operating-clock day
  final bool fullSchedule;
  const DailyReportTab({super.key, required this.activeDate, this.fullSchedule = false});
  @override
  State<DailyReportTab> createState() => _DailyReportTabState();
}

class _DailyReportTabState extends State<DailyReportTab> {
  final ApiClient _api = ApiClient();
  Map<String, dynamic>? _data;
  bool _loading = true;
  String? _error;
  late String _date;

  @override
  void initState() {
    super.initState();
    _date = _fmtDate(widget.activeDate); // default to the operating-clock day
    _load();
  }

  String _fmtDate(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final d = await _api.fetchDailyReport(
          date: _date, asOf: widget.fullSchedule ? kFullAsOf : '');
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
      lastDate: widget.fullSchedule
          ? DateTime(2099, 12, 31) // full plan: any day in the generated schedule
          : widget.activeDate,     // can't look past the operating-clock day
    );
    if (picked != null) {
      _date = _fmtDate(picked);
      _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final faults = ((_data?['faults'] as List?) ?? []);
    final techs = ((_data?['technicians'] as List?) ?? []);
    final gtype = '${_data?['group_type'] ?? ''}';
    // faults/breakdowns are a callback concept -> only show for callback or
    // mixed HQs, never for a maintenance-only HQ.
    final showFaults = gtype == 'callback' || gtype == 'mixed';
    return _DashboardCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            Icon(Icons.today, color: Colors.orange.shade800),
            const SizedBox(width: 8),
            const Text('Daily Supervisor Report',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            if (gtype.isNotEmpty) ...[
              const SizedBox(width: 10),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: Colors.blue.shade50,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text('$gtype HQ',
                    style: TextStyle(color: Colors.blue.shade800, fontSize: 11)),
              ),
            ],
            const Spacer(),
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
                    : ListView(children: [
                        Row(children: [
                          _statCard('Total Visits', '${_data?['total_visits'] ?? 0}', Colors.blue),
                          if (showFaults) ...[
                            const SizedBox(width: 12),
                            _statCard('Faults / Breakdowns', '${_data?['fault_count'] ?? 0}', Colors.red),
                          ],
                        ]),
                        const SizedBox(height: 18),
                        if (showFaults) ...[
                          Text("Faults & Breakdowns (${faults.length})",
                              style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
                          const SizedBox(height: 8),
                          if (faults.isEmpty)
                            Text('No faults/breakdowns recorded on this date.',
                                style: TextStyle(color: Colors.grey.shade500, fontSize: 13))
                          else
                            _taskTable(faults),
                          const SizedBox(height: 22),
                        ],
                        Text("Technician Locations Visited (${techs.length} techs)",
                            style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
                        const SizedBox(height: 8),
                        if (techs.isEmpty)
                          Text('No activity on this date.',
                              style: TextStyle(color: Colors.grey.shade500, fontSize: 13))
                        else
                          for (final tRaw in techs) _techBlock(Map<String, dynamic>.from(tRaw as Map)),
                      ]),
          ),
        ],
      ),
    );
  }

  Widget _statCard(String label, String value, MaterialColor c) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: c.shade50,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: c.shade200),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(value, style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold, color: c.shade800)),
            Text(label, style: TextStyle(fontSize: 12, color: c.shade700)),
          ],
        ),
      ),
    );
  }

  Widget _techBlock(Map<String, dynamic> t) {
    final locs = ((t['locations'] as List?) ?? []);
    return ExpansionTile(
      title: Text('${t['technician']}', style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14)),
      subtitle: Text('${t['stops']} stops'),
      children: [
        for (final lRaw in locs)
          Builder(builder: (_) {
            final l = Map<String, dynamic>.from(lRaw as Map);
            final isCb = l['kind'] == 'Callback';
            return ListTile(
              dense: true,
              leading: Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: isCb ? Colors.purple.shade400 : Colors.green.shade600,
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Text(isCb ? 'CB ${l['type']}' : '${l['type']}',
                    style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.bold)),
              ),
              title: Text('${l['unit_name']}', style: const TextStyle(fontSize: 13)),
              subtitle: Text('${l['unit_code']}', style: const TextStyle(fontSize: 11)),
              trailing: Text('${l['start']}–${l['end'] ?? ''}', style: const TextStyle(fontSize: 12)),
            );
          }),
      ],
    );
  }
}

// ---------------------------------------------------- Dispatch (real-time callback)
class DispatchTab extends StatefulWidget {
  final DashboardController controller;
  const DispatchTab({super.key, required this.controller});
  @override
  State<DispatchTab> createState() => _DispatchTabState();
}

class _DispatchTabState extends State<DispatchTab> {
  final TextEditingController _latCtrl = TextEditingController(text: '41.01');
  final TextEditingController _lngCtrl = TextEditingController(text: '29.05');
  final TextEditingController _descCtrl = TextEditingController();
  String _priority = 'NORMAL';
  bool _dispatching = false;
  DispatchResult? _result;
  String? _error;

  @override
  void dispose() {
    _latCtrl.dispose(); _lngCtrl.dispose(); _descCtrl.dispose();
    super.dispose();
  }

  Future<void> _dispatch() async {
    setState(() { _dispatching = true; _error = null; _result = null; });
    try {
      final lat = double.parse(_latCtrl.text.trim());
      final lng = double.parse(_lngCtrl.text.trim());
      final res = await widget.controller.dispatch(
        latitude: lat, longitude: lng,
        priority: _priority,
        faultType: _priority == 'AA' ? 'Entrapment' : 'Fault',
        description: _descCtrl.text.trim(),
      );
      setState(() { _result = res; _dispatching = false; });
    } catch (e) {
      setState(() { _error = e.toString(); _dispatching = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
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
              color: Colors.amber.shade50,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.amber.shade200),
            ),
            child: Row(children: [
              Icon(Icons.info_outline, size: 16, color: Colors.amber.shade800),
              const SizedBox(width: 8),
              Expanded(child: Text(
                'Dispatches to the nearest available callback technician. '
                'Travel times currently use a straight-line estimate; they '
                'will become real road times when Google Maps is integrated.',
                style: TextStyle(fontSize: 12, color: Colors.amber.shade900))),
            ]),
          ),
          const SizedBox(height: 16),
          Row(children: [
            Expanded(child: TextField(
              controller: _latCtrl,
              decoration: const InputDecoration(
                labelText: 'Latitude', isDense: true, border: OutlineInputBorder()),
            )),
            const SizedBox(width: 12),
            Expanded(child: TextField(
              controller: _lngCtrl,
              decoration: const InputDecoration(
                labelText: 'Longitude', isDense: true, border: OutlineInputBorder()),
            )),
          ]),
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
              label: const Text('Normal (4hr)'),
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
            onPressed: _dispatching ? null : _dispatch,
            icon: _dispatching
                ? const SizedBox(height: 16, width: 16,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : const Icon(Icons.send, size: 18),
            label: const Text('Dispatch to nearest technician'),
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
          Text('Assigned to: ${r.assignedToName}',
              style: const TextStyle(fontWeight: FontWeight.w600)),
          Text('Priority: ${r.priority}', style: TextStyle(color: Colors.grey.shade700)),
          if (r.reason.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(r.reason, style: TextStyle(color: Colors.grey.shade700, fontSize: 13)),
            ),
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