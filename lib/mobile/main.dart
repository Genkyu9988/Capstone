import 'dart:convert';
import 'dart:async';
import 'login.dart';
import 'package:geolocator/geolocator.dart';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:http/http.dart' as http;
import 'route_stop.dart'; // Ensure you created this file from Step 2!
void main() {
  runApp(const ElevatorTechApp());
}

class ElevatorTechApp extends StatelessWidget {
  const ElevatorTechApp({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Elevator Maintenance',
      theme: ThemeData(
        primarySwatch: Colors.blue,
        scaffoldBackgroundColor: Colors.white,
        fontFamily: 'Roboto',
      ),
      home: const LoginScreen(),
      debugShowCheckedModeBanner: false,
    );
  }
}

// ==========================================
// SCREEN 2: MAIN DASHBOARD & TABS
// ==========================================
class TechnicianMainScreen extends StatefulWidget {
  final String username;
  final String password;
  final List<Map<String, dynamic>>? rawRouteData;
  
  // Update constructor to require the login credentials
  const TechnicianMainScreen({
    super.key, 
    required this.username, 
    required this.password,
    this.rawRouteData
  });
  @override
  State<TechnicianMainScreen> createState() => _TechnicianMainScreenState();
}

class _TechnicianMainScreenState extends State<TechnicianMainScreen> {
  List<RouteStop> _dailyRoute = [];
  bool _isLoadingMap = true; 
  int _selectedIndex = 0;    
  String _technicianTitle = "Technician Route"; // To show "Can (Acil Arızacı)" on top
  Timer? _pollTimer;
  Map<String, dynamic>? _profile; // logged-in technician's real attributes
  LatLng? _myPosition; // live GPS position of this technician
  List<LatLng> _roadPolyline = []; // real Google road path from /api/my-route/
  String? _geometrySource;         // GOOGLE_ROADS | CACHE | STRAIGHT_* | null
  String? _activeDate;             // operating-clock day (e.g. "2026-07-06")
  StreamSubscription<Position>? _posSub;

  @override
  void initState() {
    super.initState();
    _fetchLocationsFromDatabase();
    _fetchProfile();
    // GPS disabled for the demo: an emulator reports Googleplex (California),
    // not Istanbul, and POSTing it poisons the position on BOTH apps. The
    // technician's position now comes from the backend, estimated along the
    // route by the operating clock. Re-enable for real devices in the field.
    // _startLocationTracking();
    // Poll every 10s so BOTH the map and the tasks list stay in sync with
    // whatever the supervisor dispatches on the web dashboard.
    _pollTimer = Timer.periodic(const Duration(seconds: 10), (_) {
      _fetchLocationsFromDatabase();
      _fetchProfile();
    });
  }

  @override
  void dispose() {
    _posSub?.cancel();
    _pollTimer?.cancel();
    super.dispose();
  }

  Future<void> _startLocationTracking() async {
    // Location services on?
    final serviceOn = await Geolocator.isLocationServiceEnabled();
    if (!serviceOn) {
      print("Location services are disabled.");
      return;
    }
    // Permission?
    LocationPermission perm = await Geolocator.checkPermission();
    if (perm == LocationPermission.denied) {
      perm = await Geolocator.requestPermission();
    }
    if (perm == LocationPermission.denied ||
        perm == LocationPermission.deniedForever) {
      print("Location permission not granted.");
      return;
    }
    // Stream position; emit every ~10 metres moved.
    _posSub = Geolocator.getPositionStream(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.high,
        distanceFilter: 10,
      ),
    ).listen((Position pos) {
      final here = LatLng(pos.latitude, pos.longitude);
      if (mounted) setState(() => _myPosition = here);
      _reportLocation(pos.latitude, pos.longitude);
    });
  }

  Future<void> _reportLocation(double lat, double lng) async {
    try {
      final url = Uri.parse('http://10.0.2.2:8000/api/my-location/');
      final basicAuth =
          'Basic ${base64Encode(utf8.encode("${widget.username}:${widget.password}"))}';
      await http.post(
        url,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': basicAuth,
        },
        body: json.encode({'latitude': lat, 'longitude': lng}),
      );
    } catch (e) {
      print("Location report error: $e");
    }
  }

  Future<void> _fetchProfile() async {
    try {
      final url = Uri.parse('http://10.0.2.2:8000/api/me/');
      final basicAuth =
          'Basic ${base64Encode(utf8.encode("${widget.username}:${widget.password}"))}';
      final response = await http.get(url, headers: {
        'Content-Type': 'application/json',
        'Authorization': basicAuth,
      });
      if (response.statusCode == 200) {
        final data = json.decode(response.body) as Map<String, dynamic>;
        if (mounted) setState(() => _profile = data);
      }
    } catch (e) {
      print("Profile fetch error: $e");
    }
  }

  Future<void> _fetchLocationsFromDatabase() async {
    try {
      // 1. Point to the NEW route endpoint
      final url = Uri.parse('http://10.0.2.2:8000/api/my-route/');
      
      // 2. Encode the credentials for Basic Authentication
     String basicAuth = 'Basic ${base64Encode(utf8.encode("${widget.username}:${widget.password}"))}';

      // 3. Send the request
      final response = await http.get(
        url,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': basicAuth, // This tells Django exactly who is asking
        },
      );

      if (response.statusCode == 200) {
        Map<String, dynamic> data = json.decode(response.body);
        
        // Extract the name (e.g. "Can (Acil Arızacı)") and the route array
        String techName = data['technician'] ?? 'Unknown Technician';
        List<dynamic> routeArray = data['route'] ?? [];

        // Real road geometry: decoded [[lat,lng],...] following the streets.
        final List<dynamic> polyArray = data['route_polyline'] ?? [];
        final List<LatLng> road = polyArray
            .map<LatLng?>((p) {
              if (p is List && p.length >= 2) {
                final lat = double.tryParse(p[0].toString());
                final lng = double.tryParse(p[1].toString());
                if (lat != null && lng != null) return LatLng(lat, lng);
              }
              return null;
            })
            .whereType<LatLng>()
            .toList();

        // Clock-driven position from the backend (on the route, not GPS).
        // Updated on every 10s poll, so the dot advances along the route.
        LatLng? me;
        final cp = data['current_position'];
        if (cp is Map && cp['lat'] != null && cp['lng'] != null) {
          final lat = double.tryParse(cp['lat'].toString());
          final lng = double.tryParse(cp['lng'].toString());
          if (lat != null && lng != null) me = LatLng(lat, lng);
        }

        setState(() {
          _technicianTitle = "$techName's Route";
          _dailyRoute = routeArray.map((item) => RouteStop.fromJson(item)).toList();
          _roadPolyline = road;
          _geometrySource = data['geometry_source']?.toString();
          _activeDate = data['active_date']?.toString();
          _myPosition = me;
          _isLoadingMap = false;
        });
      } else {
        print("Login failed or unauthorized: ${response.statusCode}");
        setState(() => _isLoadingMap = false);
      }
    } catch (e) {
      print("Network Error: $e");
      setState(() => _isLoadingMap = false);
    }
  }



  void _onItemTapped(int index) {
    setState(() {
      _selectedIndex = index;
    });
  }

  @override
  Widget build(BuildContext context) {
    final List<Widget> pages = [
      _buildTasksTab(context),
      _buildMapTab(),
      _buildProfileTab(context),
    ];

    return Scaffold(
      backgroundColor: Colors.grey[100],
      body: SafeArea(
        child: pages[_selectedIndex],
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _selectedIndex,
        onTap: _onItemTapped,
        selectedItemColor: Colors.blue[800],
        unselectedItemColor: Colors.grey[500],
        backgroundColor: Colors.white,
        elevation: 10,
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.list_alt), label: 'Tasks'),
          BottomNavigationBarItem(icon: Icon(Icons.map_outlined), label: 'Map'),
          BottomNavigationBarItem(icon: Icon(Icons.person_outline), label: 'Profile'),
        ],
      ),
    );
  }

  // ----------------------------------------------------
  // TAB 1: TASKS
  // ----------------------------------------------------
  Widget _buildTasksTab(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async {
        await Future.delayed(const Duration(seconds: 1));
        if (context.mounted) {
           ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Checking for new schedule assignments...')),
          );
        }
      },
      child: Padding(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(_technicianTitle, style: const TextStyle(fontSize: 28, fontWeight: FontWeight.bold, letterSpacing: -0.5)),
                    const Text('Field Technician', style: TextStyle(fontSize: 16, color: Colors.blue, fontWeight: FontWeight.w600)),
                  ],
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(color: Colors.green[50], borderRadius: BorderRadius.circular(20), border: Border.all(color: Colors.green[200]!)),
                  child: Row(
                    children: [
                      Icon(Icons.wifi, size: 14, color: Colors.green[700]),
                      const SizedBox(width: 4),
                      Text("Online", style: TextStyle(color: Colors.green[700], fontSize: 12, fontWeight: FontWeight.bold)),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text('${_dailyRoute.where((s) => s.type.toUpperCase() != "DEPOT").length} stop(s) planned today', style: TextStyle(fontSize: 14, color: Colors.grey[600])),
            const SizedBox(height: 32),
            const Text("Daily Planned Schedule", style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
            const SizedBox(height: 16),

            Expanded(
              child: _isLoadingMap
                  ? const Center(child: CircularProgressIndicator())
                  : Builder(
                      builder: (context) {
                        // Real tasks from /api/my-route/, skipping the depot (stop 0).
                        final tasks = _dailyRoute
                            .where((s) => s.type.toUpperCase() != "DEPOT")
                            .toList();
                        if (tasks.isEmpty) {
                          return Center(
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Icon(Icons.check_circle_outline,
                                    size: 48, color: Colors.grey[400]),
                                const SizedBox(height: 12),
                                Text("No tasks assigned yet",
                                    style: TextStyle(
                                        color: Colors.grey[600], fontSize: 16)),
                                const SizedBox(height: 4),
                                Text("New dispatches appear here automatically.",
                                    style: TextStyle(
                                        color: Colors.grey[400], fontSize: 13)),
                              ],
                            ),
                          );
                        }
                        // Compute a clock time per stop, in displayed order,
                        // starting at 09:00 and adding each task's duration + a
                        // 15-minute travel buffer. Keeps times consistent with
                        // the order shown (AA first, etc.).
                        var clock = const TimeOfDay(hour: 9, minute: 0);
                        int minutes(TimeOfDay t) => t.hour * 60 + t.minute;
                        TimeOfDay addMin(TimeOfDay t, int m) {
                          final total = (minutes(t) + m) % (24 * 60);
                          return TimeOfDay(hour: total ~/ 60, minute: total % 60);
                        }
                        String fmt(TimeOfDay t) {
                          final h = t.hourOfPeriod == 0 ? 12 : t.hourOfPeriod;
                          final m = t.minute.toString().padLeft(2, '0');
                          final ap = t.period == DayPeriod.am ? 'AM' : 'PM';
                          return '$h:$m $ap';
                        }
                        final cards = <Widget>[];
                        for (final stop in tasks) {
                          final timeLabel = fmt(clock);
                          cards.add(_buildRouteTaskCard(context, stop, timeLabel));
                          clock = addMin(clock, stop.durationMin + 15);
                        }
                        return ListView(children: cards);
                      },
                    ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildRouteTaskCard(BuildContext context, RouteStop stop, String timeLabel) {
    final isAA = stop.priority.toUpperCase() == "AA";
    final accent = isAA ? Colors.red : Colors.blue;
    final place = stop.unitName.isNotEmpty ? stop.unitName : "Task ${stop.taskId}";
    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      decoration: BoxDecoration(
        color: isAA ? Colors.red[50] : Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isAA ? Colors.red : Colors.grey[300]!,
          width: isAA ? 2 : 1,
        ),
        boxShadow: [
          BoxShadow(
              color: Colors.black.withOpacity(0.05),
              blurRadius: 8,
              offset: const Offset(0, 2)),
        ],
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(timeLabel,
                    style: TextStyle(
                        fontWeight: FontWeight.bold,
                        fontSize: 16,
                        color: isAA ? Colors.red : Colors.black)),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: accent.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: accent.withOpacity(0.5)),
                  ),
                  child: Text(isAA ? "AA Emergency" : "Scheduled",
                      style: TextStyle(
                          color: accent,
                          fontSize: 12,
                          fontWeight: FontWeight.bold)),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                if (isAA)
                  const Padding(
                    padding: EdgeInsets.only(right: 8.0),
                    child:
                        Icon(Icons.report_problem, color: Colors.red, size: 20),
                  ),
                Expanded(
                  child: Text(stop.location,
                      style: const TextStyle(
                          fontWeight: FontWeight.bold, fontSize: 16)),
                ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: Colors.grey[100],
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text("Stop ${stop.sequenceOrder}",
                      style: TextStyle(
                          color: Colors.grey[700],
                          fontSize: 11,
                          fontWeight: FontWeight.bold)),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Row(
              children: [
                Icon(Icons.location_on, size: 14, color: Colors.grey[500]),
                const SizedBox(width: 4),
                Expanded(
                  child: Text(place,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(color: Colors.grey[700], fontSize: 14)),
                ),
                Text("~${stop.durationMin} min",
                    style: TextStyle(color: Colors.grey[500], fontSize: 12)),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildTaskCard({
    required BuildContext context,
    required String id,
    required String time,
    required String type,
    required String location,
    required String status,
    required bool isEmergency,
    required bool isHighPriority,
    required String faultDetails,
  }) {
    Color statusColor;
    if (status == "Completed") statusColor = Colors.green;
    else if (status == "En Route") statusColor = Colors.orange;
    else statusColor = Colors.grey;

    return Dismissible(
      key: Key(id),
      direction: status == "Completed" ? DismissDirection.none : DismissDirection.startToEnd,
      background: Container(
        margin: const EdgeInsets.only(bottom: 16),
        decoration: BoxDecoration(color: Colors.green, borderRadius: BorderRadius.circular(12)),
        alignment: Alignment.centerLeft,
        padding: const EdgeInsets.symmetric(horizontal: 20),
        child: const Icon(Icons.check_circle, color: Colors.white, size: 30),
      ),
      onDismissed: (direction) {
        ScaffoldMessenger.of(context).clearSnackBars();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('$id marked as completed'),
            action: SnackBarAction(
              label: 'UNDO',
              textColor: Colors.yellow,
              onPressed: () {},
            ),
            duration: const Duration(seconds: 4),
          ),
        );
      },
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 300),
        margin: const EdgeInsets.only(bottom: 16),
        decoration: BoxDecoration(
          color: isEmergency && status != "Completed" ? Colors.red[50] : Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: isHighPriority && status != "Completed" ? Colors.red : Colors.grey[300]!,
            width: isHighPriority && status != "Completed" ? 2 : 1,
          ),
          boxShadow: [
            BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 8, offset: const Offset(0, 2)),
          ],
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () {
            _showTaskDetailsSheet(context, id, time, type, location, isEmergency, faultDetails);
          },
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(time, style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: isEmergency && status != "Completed" ? Colors.red : Colors.black)),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(color: statusColor.withOpacity(0.1), borderRadius: BorderRadius.circular(8), border: Border.all(color: statusColor.withOpacity(0.5))),
                      child: Text(status, style: TextStyle(color: statusColor, fontSize: 12, fontWeight: FontWeight.bold)),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    if (isEmergency && status != "Completed") 
                      const Padding(padding: EdgeInsets.only(right: 8.0), child: Icon(Icons.report_problem, color: Colors.red, size: 20)),
                    Expanded(child: Text(type, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16))),
                  ],
                ),
                const SizedBox(height: 4),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Expanded(
                      child: Row(
                        children: [
                          Icon(Icons.location_on, size: 14, color: Colors.grey[500]),
                          const SizedBox(width: 4),
                          Expanded(child: Text(location, style: TextStyle(color: Colors.grey[700], fontSize: 14))),
                        ],
                      ),
                    ),
                    if (isHighPriority && status != "Completed")
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(color: Colors.red[100], borderRadius: BorderRadius.circular(4)),
                        child: const Text("14m remaining", style: TextStyle(color: Colors.red, fontSize: 12, fontWeight: FontWeight.bold)),
                      )
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  void _showTaskDetailsSheet(BuildContext context, String taskId, String time, String type, String location, bool isEmergency, String faultDetails) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true, 
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (BuildContext context) {
        return Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisSize: MainAxisSize.min, 
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Center(
                child: Container(
                  width: 40,
                  height: 5,
                  decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(10)),
                ),
              ),
              const SizedBox(height: 24),

              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    time, 
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: isEmergency ? Colors.red : Colors.black),
                  ),
                  if (isEmergency)
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(color: Colors.red, borderRadius: BorderRadius.circular(8)),
                      child: const Text('EMERGENCY', style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.bold)),
                    ),
                ],
              ),
              const SizedBox(height: 8),
              Text(type, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
              const SizedBox(height: 4),
              Row(
                children: [
                  Icon(Icons.location_on, size: 16, color: Colors.grey[600]),
                  const SizedBox(width: 4),
                  Text(location, style: TextStyle(color: Colors.grey[600], fontSize: 15)),
                ],
              ),
              const Divider(height: 32, thickness: 1),

              const Text('Fault / Task Details', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(color: Colors.grey[50], borderRadius: BorderRadius.circular(8), border: Border.all(color: Colors.grey[200]!)),
                child: Text(faultDetails, style: const TextStyle(fontSize: 15, height: 1.4)),
              ),
              const SizedBox(height: 32),

              SizedBox(
                width: double.infinity,
                child: ElevatedButton.icon(
                  onPressed: () {
                    Navigator.pop(context); 
                    
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (context) => ActiveNavigationScreen(
                          taskId: taskId, 
                          type: type,
                          location: location,
                          isEmergency: isEmergency,
                        ),
                      ),
                    );
                  }, 
                  icon: const Icon(Icons.directions),
                  label: const Text('Start Navigation'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: isEmergency ? Colors.red : Colors.blue[800],
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    elevation: 0,
                  ),
                ),
              ),
              const SizedBox(height: 16), 
            ],
          ),
        );
      },
    );
  }

  // ----------------------------------------------------
  // TAB 2: MAP (Dashboard Global Route Placeholder)
  // ----------------------------------------------------
  Widget _buildMapTab() {
    if (_isLoadingMap) {
      return const Center(
        child: CircularProgressIndicator(color: Color(0xFF1E3A8A)),
      );
    }

    // Task stops only — skip the depot (index 0), which can be a GPS artifact.
    final List<RouteStop> taskStops =
        _dailyRoute.where((s) => s.type != "DEPOT").toList();

    if (taskStops.isEmpty) {
      return const Center(
        child: Text("No tasks scheduled for today.", style: TextStyle(fontSize: 16)),
      );
    }

    final List<LatLng> straightPoints =
        taskStops.map((stop) => LatLng(stop.latitude, stop.longitude)).toList();
    // Prefer the real Google road path; fall back to straight legs if missing.
    final List<LatLng> routeLine =
        _roadPolyline.length >= 2 ? _roadPolyline : straightPoints;

    // Center on the technician (clock-driven position); else the first stop.
    final LatLng center = _myPosition ?? straightPoints.first;

    return FlutterMap(
      options: MapOptions(
        initialCenter: center,
        initialZoom: 14.0,
      ),
      children: [
        TileLayer(
          urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
          userAgentPackageName: 'com.example.elevatortechapp',
        ),
        PolylineLayer(
          polylines: [
            Polyline(
              points: routeLine,
              color: const Color(0xFF2563EB), 
              strokeWidth: 4.0,
            ),
          ],
        ),
        MarkerLayer(
          markers: taskStops.map((stop) {
            return Marker(
              point: LatLng(stop.latitude, stop.longitude),
              width: 150,  // Massive box to absorb Android's DPI scaling
              height: 150, 
              alignment: Alignment.center,
              child: Center( // Forces the Column to stay perfectly in the middle
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      width: 30,
                      height: 30,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        color: Colors.white,
                        shape: BoxShape.circle,
                        border: Border.all(color: const Color(0xFF2563EB), width: 2),
                        boxShadow: [
                          BoxShadow(color: Colors.black.withOpacity(0.15), blurRadius: 4, offset: const Offset(0, 2)),
                        ],
                      ),
                      child: Text(
                        "${stop.sequenceOrder}", 
                        // This stops the Android emulator from blowing up the font size
                        textScaler: const TextScaler.linear(1.0), 
                        style: const TextStyle(
                          fontWeight: FontWeight.w900, 
                          color: Color(0xFF1E3A8A), 
                          fontSize: 14,
                        ),
                      ),
                    ),
                    const Icon(Icons.location_on, color: Color(0xFF2563EB), size: 40),
                  ],
                ),
              ),
            );
          }).toList(),
        ),
        if (_myPosition != null)
          MarkerLayer(
            markers: [
              Marker(
                point: _myPosition!,
                width: 60,
                height: 60,
                alignment: Alignment.center,
                child: const _MePin(),
              ),
            ],
          ),
      ],
    );
  }

  // ----------------------------------------------------
  // TAB 3: PROFILE
  // ----------------------------------------------------
  Widget _buildProfileTab(BuildContext context) {
    final p = _profile;
    // Derive display values from the real /api/me/ data (with safe fallbacks).
    final name = p?['full_name'] ?? _technicianTitle.replaceAll("'s Route", "");
    final code = p?['employee_code'] ?? '—';
    final role = (p?['tech_role'] ?? '').toString();      // MAINTENANCE / REPAIR / BOTH
    final specialty = (p?['specialty'] ?? '').toString();  // ELEVATOR / ESCALATOR / BOTH
    final region = (p?['region'] ?? '').toString();        // ASIA / EUROPE
    final initials = name.trim().isEmpty
        ? '?'
        : name.trim().split(RegExp(r'\s+')).map((w) => w[0]).take(2).join().toUpperCase();

    String roleLabel(String r) {
      switch (r) {
        case 'MAINTENANCE':
          return 'Maintenance';
        case 'CALLBACK':
          return 'Callback';
        case 'REPAIR':
          return 'Repair / Fault';
        case 'BOTH':
          return 'Maintenance & Repair';
        default:
          return r.isEmpty ? '—' : r;
      }
    }

    final chips = <String>[];
    if (specialty == 'ELEVATOR' || specialty == 'BOTH') chips.add('Elevators');
    if (specialty == 'ESCALATOR' || specialty == 'BOTH') chips.add('Escalators');

    final isAsia = region.toUpperCase() == 'ASIA';
    final regionLabel = region.isEmpty
        ? '—'
        : (isAsia ? 'Asian Side' : 'European Side');

    return ListView(
      padding: const EdgeInsets.all(20.0),
      children: [
        const Text("Technician Profile", style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
        const SizedBox(height: 20),

        // Identity card
        Card(
          elevation: 0,
          color: Colors.white,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12), side: BorderSide(color: Colors.grey[200]!)),
          child: Padding(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    CircleAvatar(
                      radius: 30,
                      backgroundColor: Colors.blue[100],
                      child: Text(initials, style: TextStyle(color: Colors.blue[800], fontSize: 20, fontWeight: FontWeight.bold)),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(name, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
                          Text("ID: $code", style: TextStyle(color: Colors.grey[600])),
                        ],
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                      decoration: BoxDecoration(color: Colors.indigo[50], borderRadius: BorderRadius.circular(20)),
                      child: Text(roleLabel(role), style: TextStyle(color: Colors.indigo[700], fontSize: 12, fontWeight: FontWeight.bold)),
                    ),
                  ],
                ),
                const Divider(height: 32),
                const Text("Qualifications", style: TextStyle(fontWeight: FontWeight.w600)),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  children: [
                    for (final c in chips)
                      Chip(label: Text(c), backgroundColor: Colors.blue[50], side: BorderSide.none, labelStyle: TextStyle(color: Colors.blue[800])),
                    if (chips.isEmpty)
                      Text('—', style: TextStyle(color: Colors.grey[500])),
                  ],
                ),
                const SizedBox(height: 16),
                const Text("Region", style: TextStyle(fontWeight: FontWeight.w600)),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Icon(Icons.place, size: 18, color: isAsia ? Colors.deepOrange : Colors.blue),
                    const SizedBox(width: 6),
                    Text(regionLabel, style: const TextStyle(fontWeight: FontWeight.w600)),
                  ],
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),

        // Availability & Leave
        Card(
          elevation: 0,
          color: Colors.white,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12), side: BorderSide(color: Colors.grey[200]!)),
          child: Padding(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text("Availability & Leave", style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                Text(
                  "Submit planned leave or emergency instant leave for supervisor approval. Works for both maintenance and callback technicians.",
                  style: TextStyle(color: Colors.grey[600], fontSize: 13),
                ),
                const SizedBox(height: 10),
                if (_activeDate != null)
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: Colors.blue[50],
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: Colors.blue[100]!),
                    ),
                    child: Text(
                      "Operating date: $_activeDate",
                      style: TextStyle(color: Colors.blue[900], fontSize: 12, fontWeight: FontWeight.w600),
                    ),
                  ),
                const SizedBox(height: 12),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: () => _showPlannedLeaveRequestSheet(context),
                    icon: const Icon(Icons.date_range),
                    label: const Text("Planned Leave Request"),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Colors.blue[800],
                      side: BorderSide(color: Colors.blue[800]!),
                      padding: const EdgeInsets.symmetric(vertical: 14),
                    ),
                  ),
                ),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton.icon(
                    onPressed: () => _showInstantLeaveRequestSheet(context),
                    icon: const Icon(Icons.emergency_share),
                    label: const Text("Instant Emergency Leave"),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.red[700],
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                      elevation: 0,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),

        // Settings / Logout
        Card(
          elevation: 0,
          color: Colors.white,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12), side: BorderSide(color: Colors.grey[200]!)),
          child: Column(
            children: [
              ListTile(leading: const Icon(Icons.settings), title: const Text("App Settings"), trailing: const Icon(Icons.chevron_right), onTap: () {}),
              const Divider(height: 1),
              ListTile(
                leading: const Icon(Icons.logout, color: Colors.red),
                title: const Text("Logout", style: TextStyle(color: Colors.red)),
                onTap: () {
                  Navigator.pushReplacement(context, MaterialPageRoute(builder: (context) => const LoginScreen()));
                },
              ),
            ],
          ),
        ),
        const SizedBox(height: 24),
      ],
    );
  }

  // ----------------------------------------------------
  // LEAVE REQUEST BOTTOM SHEETS
  // ----------------------------------------------------
  DateTime _operatingDateTime() {
    final raw = _activeDate;
    if (raw != null && raw.trim().isNotEmpty) {
      final parsed = DateTime.tryParse(raw.trim());
      if (parsed != null) return DateTime(parsed.year, parsed.month, parsed.day);
    }
    final now = DateTime.now();
    return DateTime(now.year, now.month, now.day);
  }

  String _isoDate(DateTime dt) =>
      "${dt.year.toString().padLeft(4, '0')}-${dt.month.toString().padLeft(2, '0')}-${dt.day.toString().padLeft(2, '0')}";

  String _prettyDate(DateTime dt) =>
      "${dt.day.toString().padLeft(2, '0')}/${dt.month.toString().padLeft(2, '0')}/${dt.year}";

  String _extractApiError(http.Response response) {
    try {
      final decoded = json.decode(response.body);
      if (decoded is Map && decoded['error'] != null) {
        return decoded['error'].toString();
      }
    } catch (_) {}
    return 'Server returned ${response.statusCode}: ${response.body}';
  }

  Future<void> _submitLeaveRequest({
    required String leaveType,
    DateTime? start,
    DateTime? end,
    int? days,
    required String reason,
    bool instant = false,
  }) async {
    final url = Uri.parse('http://10.0.2.2:8000/api/leave-request/');
    final basicAuth =
        'Basic ${base64Encode(utf8.encode("${widget.username}:${widget.password}"))}';

    final Map<String, dynamic> payload = {
      'leave_type': instant ? 'Instant Leave' : leaveType,
      'reason': reason.trim(),
    };

    if (instant) {
      payload['instant'] = true;
      payload['days'] = days ?? 1;
    } else {
      if (start == null || end == null) {
        throw Exception('Start and end date are required.');
      }
      payload['start_date'] = _isoDate(start);
      payload['end_date'] = _isoDate(end);
    }

    final response = await http.post(
      url,
      headers: {'Content-Type': 'application/json', 'Authorization': basicAuth},
      body: json.encode(payload),
    );
    if (response.statusCode != 201) {
      throw Exception(_extractApiError(response));
    }
  }

  void _showPlannedLeaveRequestSheet(BuildContext context) {
    String leaveType = 'Annual Leave';
    DateTime? startDate;
    DateTime? endDate;
    final reasonController = TextEditingController();
    bool submitting = false;

    final operating = _operatingDateTime();
    final earliest = operating.add(const Duration(days: 14));
    final latest = operating.add(const Duration(days: 365));

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (BuildContext sheetContext) {
        return StatefulBuilder(
          builder: (context, setSheet) {
            Future<void> pick(bool isStart) async {
              final initial = isStart
                  ? (startDate ?? earliest)
                  : (endDate ?? startDate ?? earliest);
              final first = isStart ? earliest : (startDate ?? earliest);
              final last = isStart
                  ? latest
                  : (startDate == null ? latest : startDate!.add(const Duration(days: 6)));
              final picked = await showDatePicker(
                context: context,
                initialDate: initial.isBefore(first) ? first : initial,
                firstDate: first,
                lastDate: last.isAfter(latest) ? latest : last,
              );
              if (picked != null) {
                setSheet(() {
                  if (isStart) {
                    startDate = DateTime(picked.year, picked.month, picked.day);
                    final maxEnd = startDate!.add(const Duration(days: 6));
                    if (endDate == null || endDate!.isBefore(startDate!) || endDate!.isAfter(maxEnd)) {
                      endDate = startDate;
                    }
                  } else {
                    endDate = DateTime(picked.year, picked.month, picked.day);
                  }
                });
              }
            }

            Future<void> submit() async {
              if (startDate == null || endDate == null) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Please pick a start and end date.')),
                );
                return;
              }
              final leaveDays = endDate!.difference(startDate!).inDays + 1;
              if (leaveDays > 7) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Leave interval can be maximum 7 days.')),
                );
                return;
              }
              setSheet(() => submitting = true);
              try {
                await _submitLeaveRequest(
                  leaveType: leaveType,
                  start: startDate!,
                  end: endDate!,
                  reason: reasonController.text,
                );
                if (!mounted) return;
                Navigator.pop(sheetContext);
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: const Row(
                      children: [
                        Icon(Icons.check_circle, color: Colors.white),
                        SizedBox(width: 12),
                        Expanded(child: Text('Planned leave request submitted — pending supervisor approval.')),
                      ],
                    ),
                    backgroundColor: Colors.green[800],
                    behavior: SnackBarBehavior.floating,
                  ),
                );
              } catch (e) {
                setSheet(() => submitting = false);
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('Could not submit: $e'), backgroundColor: Colors.red[700]),
                );
              }
            }

            Widget dateButton(String label, DateTime? value, bool isStart) {
              return Expanded(
                child: OutlinedButton.icon(
                  onPressed: () => pick(isStart),
                  icon: const Icon(Icons.calendar_today, size: 18),
                  label: Text(value == null ? label : _prettyDate(value)),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: value == null ? Colors.black87 : Colors.blue[800],
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    side: BorderSide(color: value == null ? Colors.grey[300]! : Colors.blue[800]!),
                  ),
                ),
              );
            }

            return Padding(
              padding: EdgeInsets.only(
                bottom: MediaQuery.of(context).viewInsets.bottom,
                left: 24.0,
                right: 24.0,
                top: 24.0,
              ),
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Center(
                      child: Container(
                        width: 40,
                        height: 5,
                        decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(10)),
                      ),
                    ),
                    const SizedBox(height: 24),
                    const Text("Planned Leave Request", style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 8),
                    Text(
                      "Minimum notice: 14 days from operating date (${_isoDate(operating)}). Maximum interval: 7 days.",
                      style: TextStyle(color: Colors.grey[600], fontSize: 14),
                    ),
                    const SizedBox(height: 16),
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(color: Colors.blue[50], borderRadius: BorderRadius.circular(8)),
                      child: Text(
                        "Earliest allowed start: ${_isoDate(earliest)}",
                        style: TextStyle(color: Colors.blue[900], fontWeight: FontWeight.w600),
                      ),
                    ),
                    const SizedBox(height: 20),

                    const Text("Request Type", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
                    const SizedBox(height: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      decoration: BoxDecoration(
                        border: Border.all(color: Colors.grey[300]!),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: DropdownButtonHideUnderline(
                        child: DropdownButton<String>(
                          isExpanded: true,
                          value: leaveType,
                          items: const <String>['Annual Leave', 'Medical Leave', 'Training', 'Personal Leave']
                              .map((v) => DropdownMenuItem<String>(value: v, child: Text(v)))
                              .toList(),
                          onChanged: (v) => setSheet(() => leaveType = v ?? 'Annual Leave'),
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    const Text("Select Dates", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        dateButton("Start Date", startDate, true),
                        const SizedBox(width: 12),
                        dateButton("End Date", endDate, false),
                      ],
                    ),
                    const SizedBox(height: 16),

                    const Text("Reason / Notes", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
                    const SizedBox(height: 8),
                    TextField(
                      controller: reasonController,
                      maxLines: 3,
                      decoration: InputDecoration(
                        hintText: "Briefly explain the reason for your request...",
                        hintStyle: TextStyle(color: Colors.grey[400]),
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide(color: Colors.grey[300]!)),
                        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide(color: Colors.grey[300]!)),
                      ),
                    ),
                    const SizedBox(height: 24),

                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton(
                        onPressed: submitting ? null : submit,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.blue[800],
                          foregroundColor: Colors.white,
                          padding: const EdgeInsets.symmetric(vertical: 16),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                          elevation: 0,
                        ),
                        child: submitting
                            ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                            : const Text('SUBMIT PLANNED LEAVE', style: TextStyle(fontWeight: FontWeight.bold, letterSpacing: 1)),
                      ),
                    ),
                    const SizedBox(height: 24),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }

  void _showInstantLeaveRequestSheet(BuildContext context) {
    int days = 1;
    final reasonController = TextEditingController(text: 'Emergency / sudden leave request');
    bool submitting = false;
    final operating = _operatingDateTime();

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (BuildContext sheetContext) {
        return StatefulBuilder(
          builder: (context, setSheet) {
            Future<void> submit() async {
              if (reasonController.text.trim().isEmpty) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Please enter a short emergency reason.')),
                );
                return;
              }
              setSheet(() => submitting = true);
              try {
                await _submitLeaveRequest(
                  leaveType: 'Instant Leave',
                  days: days,
                  reason: reasonController.text,
                  instant: true,
                );
                if (!mounted) return;
                Navigator.pop(sheetContext);
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: const Row(
                      children: [
                        Icon(Icons.warning_amber_rounded, color: Colors.white),
                        SizedBox(width: 12),
                        Expanded(child: Text('Instant leave request submitted — pending supervisor approval.')),
                      ],
                    ),
                    backgroundColor: Colors.red[800],
                    behavior: SnackBarBehavior.floating,
                  ),
                );
              } catch (e) {
                setSheet(() => submitting = false);
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('Could not submit: $e'), backgroundColor: Colors.red[700]),
                );
              }
            }

            return Padding(
              padding: EdgeInsets.only(
                bottom: MediaQuery.of(context).viewInsets.bottom,
                left: 24.0,
                right: 24.0,
                top: 24.0,
              ),
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Center(
                      child: Container(
                        width: 40,
                        height: 5,
                        decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(10)),
                      ),
                    ),
                    const SizedBox(height: 24),
                    Row(
                      children: [
                        Icon(Icons.warning_amber_rounded, color: Colors.red[700]),
                        const SizedBox(width: 8),
                        const Expanded(
                          child: Text("Instant Emergency Leave", style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(
                      "Use this for sudden emergencies during work, such as an accident. It starts from the current operating date (${_isoDate(operating)}).",
                      style: TextStyle(color: Colors.grey[600], fontSize: 14),
                    ),
                    const SizedBox(height: 18),
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.red[50],
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: Colors.red[100]!),
                      ),
                      child: Text(
                        "Supervisor approval will rebuild remaining same-day work and future schedules in your own domain: maintenance stays maintenance, callback stays callback.",
                        style: TextStyle(color: Colors.red[900], fontSize: 13, fontWeight: FontWeight.w600),
                      ),
                    ),
                    const SizedBox(height: 16),

                    const Text("Requested Duration", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
                    const SizedBox(height: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      decoration: BoxDecoration(
                        border: Border.all(color: Colors.grey[300]!),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: DropdownButtonHideUnderline(
                        child: DropdownButton<int>(
                          isExpanded: true,
                          value: days,
                          items: List.generate(7, (i) => i + 1)
                              .map((v) => DropdownMenuItem<int>(value: v, child: Text('$v day${v == 1 ? '' : 's'}')))
                              .toList(),
                          onChanged: (v) => setSheet(() => days = v ?? 1),
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    const Text("Emergency Reason", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
                    const SizedBox(height: 8),
                    TextField(
                      controller: reasonController,
                      maxLines: 3,
                      decoration: InputDecoration(
                        hintText: "Example: Car crash during route, sudden illness...",
                        hintStyle: TextStyle(color: Colors.grey[400]),
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide(color: Colors.grey[300]!)),
                        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide(color: Colors.grey[300]!)),
                      ),
                    ),
                    const SizedBox(height: 24),

                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton(
                        onPressed: submitting ? null : submit,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.red[700],
                          foregroundColor: Colors.white,
                          padding: const EdgeInsets.symmetric(vertical: 16),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                          elevation: 0,
                        ),
                        child: submitting
                            ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                            : const Text('SUBMIT INSTANT LEAVE', style: TextStyle(fontWeight: FontWeight.bold, letterSpacing: 1)),
                      ),
                    ),
                    const SizedBox(height: 24),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }

}

// ==========================================
// SCREEN 3: ACTIVE NAVIGATION (Placeholder)
// ==========================================
class ActiveNavigationScreen extends StatelessWidget {
  final String taskId;
  final String type;
  final String location;
  final bool isEmergency;

  const ActiveNavigationScreen({
    Key? key,
    required this.taskId,
    required this.type,
    required this.location,
    required this.isEmergency,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Stack(
        children: [
          Container(
            width: double.infinity,
            height: double.infinity,
            color: const Color(0xFFE5E5EA),
            child: Stack(
              children: [
                CustomPaint(
                  size: Size.infinite,
                  painter: GridPainter(),
                ),
                Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.directions_car, size: 64, color: Colors.blue[800]),
                      const SizedBox(height: 16),
                      Text(
                        "Live Navigation View\n(Backend Map Integration Area)",
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                          color: Colors.grey[600],
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),

          Positioned(
            top: 50,
            left: 16,
            child: CircleAvatar(
              backgroundColor: Colors.white,
              radius: 20,
              child: IconButton(
                icon: const Icon(Icons.close, color: Colors.black, size: 20),
                onPressed: () => Navigator.pop(context),
              ),
            ),
          ),

          Positioned(
            top: 50,
            left: 70,
            right: 16,
            child: Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
                boxShadow: const [BoxShadow(color: Colors.black12, blurRadius: 10)],
                border: Border.all(
                  color: isEmergency ? Colors.red : Colors.transparent,
                  width: 2,
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      if (isEmergency)
                        const Padding(
                          padding: EdgeInsets.only(right: 8.0),
                          child: Icon(Icons.warning_amber_rounded, color: Colors.red),
                        ),
                      Expanded(
                        child: Text(
                          type,
                          style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.bold,
                            color: isEmergency ? Colors.red : Colors.black,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    "Dest: $location",
                    style: TextStyle(color: Colors.grey[700], fontSize: 14),
                  ),
                ],
              ),
            ),
          ),

          Positioned(
            bottom: 0,
            left: 0,
            right: 0,
            child: Container(
              padding: const EdgeInsets.all(24),
              decoration: const BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
                boxShadow: [
                  BoxShadow(color: Colors.black12, blurRadius: 15, offset: Offset(0, -5))
                ],
              ),
              child: SafeArea(
                top: false,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                      children: [
                        Column(
                          children: [
                            Text(
                              "14 min",
                              style: TextStyle(
                                fontSize: 28,
                                fontWeight: FontWeight.bold,
                                color: isEmergency ? Colors.red : Colors.green[700],
                              ),
                            ),
                            Text("ETA", style: TextStyle(color: Colors.grey[600])),
                          ],
                        ),
                        Container(width: 1, height: 40, color: Colors.grey[300]),
                        Column(
                          children: [
                            const Text(
                              "5.2 km",
                              style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
                            ),
                            Text("Distance", style: TextStyle(color: Colors.grey[600])),
                          ],
                        ),
                      ],
                    ),
                    const SizedBox(height: 24),

                    SizedBox(
                      width: double.infinity,
                      height: 60,
                      child: ElevatedButton(
                        onPressed: () {
                          Navigator.pop(context); 
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(content: Text('Arrival logged. Task timer started.')),
                          );
                        },
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.blue[800],
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(16),
                          ),
                          elevation: 0,
                        ),
                        child: const Text(
                          'MARK AS ARRIVED',
                          style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.bold,
                            letterSpacing: 1.2,
                            color: Colors.white,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class GridPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = Colors.white
      ..strokeWidth = 2.0;

    const double spacing = 40.0;

    for (double i = 0; i < size.width; i += spacing) {
      canvas.drawLine(Offset(i, 0), Offset(i, size.height), paint);
    }
    for (double i = 0; i < size.height; i += spacing) {
      canvas.drawLine(Offset(0, i), Offset(size.width, i), paint);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
class _MePin extends StatelessWidget {
  const _MePin();
  @override
  Widget build(BuildContext context) {
    return Center(
      child: Container(
        width: 22,
        height: 22,
        decoration: BoxDecoration(
          color: const Color(0xFF2563EB),
          shape: BoxShape.circle,
          border: Border.all(color: Colors.white, width: 3),
          boxShadow: [
            BoxShadow(
              color: const Color(0xFF2563EB).withOpacity(0.5),
              blurRadius: 10,
              spreadRadius: 2,
            ),
          ],
        ),
      ),
    );
  }
}
