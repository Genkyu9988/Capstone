// =============================================================================
// Anıl Galeri — WEB ADMIN DASHBOARD  (separate app from anil_galeri.dart)
//
// Run on Chrome:
//   flutter run -d chrome -t lib/AdminWeb/anil_admin.dart
//
// Needs the Java backend running:  cd anil-backend && mvn spring-boot:run
// Uses only packages already in your pubspec: dio.
// =============================================================================

import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:dio/dio.dart';

// Flutter web reaches the backend on localhost directly (CORS is open for dev).
const String kApiBase = 'http://localhost:8080';

// Admin login the backend's SecurityConfig expects (HTTP Basic).
// Everything except public GET /vehicles, GET /locations, POST /orders, POST /bookings
// requires this. Change these if you change the backend user.
const String kAdminUser = 'admin@anilgaleri.com';
const String kAdminPass = '123456';

void main() => runApp(const AdminApp());

// =============================================================================
// THEME
// =============================================================================

class C {
  static const bg = Color(0xFFF4F5F7);
  static const sidebar = Color(0xFF0F1318);
  static const sidebarSel = Color(0xFF1C2530);
  static const card = Colors.white;
  static const gold = Color(0xFFE8C423);
  static const text = Color(0xFF1A1D21);
  static const muted = Color(0xFF8A9099);
  static const border = Color(0xFFE6E8EC);
  static const green = Color(0xFF2BB673);
  static const red = Color(0xFFE5484D);
  static const blue = Color(0xFF3B82F6);
}

const List<String> kFuelOptions = ['petrol', 'diesel', 'electric', 'hybrid'];
const List<String> kTransOptions = ['automatic', 'manual', 'semiAutomatic'];
const List<String> kBodyOptions = [
  'suv', 'sedan', 'coupe', 'hatchback', 'pickup', 'cabrio', 'wagon'
];
const List<String> kPartOptions = ['original', 'painted', 'replaced'];

// Display capacity per gallery, used by the Distribution view's utilization bars.
const int kLocationCapacity = 35;

String thousands(num n) => n
    .toStringAsFixed(0)
    .replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (m) => ',');
String money(num n) => '\$${thousands(n)}';

double _d(dynamic v) =>
    v == null ? 0 : (v is num ? v.toDouble() : double.tryParse('$v') ?? 0);
int _i(dynamic v) =>
    v == null ? 0 : (v is num ? v.toInt() : int.tryParse('$v') ?? 0);

// =============================================================================
// MODELS  (mirror the API / cars.json shape exactly)
// =============================================================================

class Specs {
  int powerHp, topSpeed, engineCc, torque, rangeKm;
  double zeroToHundred, batteryKwh;
  String color, drivetrain;

  Specs({
    this.powerHp = 0,
    this.topSpeed = 0,
    this.engineCc = 0,
    this.torque = 0,
    this.rangeKm = 0,
    this.zeroToHundred = 0,
    this.batteryKwh = 0,
    this.color = '',
    this.drivetrain = 'AWD',
  });

  factory Specs.fromJson(Map<String, dynamic> j) => Specs(
        powerHp: _i(j['powerHp']),
        topSpeed: _i(j['topSpeed']),
        engineCc: _i(j['engineCc']),
        torque: _i(j['torque']),
        rangeKm: _i(j['rangeKm']),
        zeroToHundred: _d(j['zeroToHundred']),
        batteryKwh: _d(j['batteryKwh']),
        color: (j['color'] ?? '').toString(),
        drivetrain: (j['drivetrain'] ?? 'AWD').toString(),
      );

  Map<String, dynamic> toJson() => {
        'powerHp': powerHp,
        'topSpeed': topSpeed,
        'engineCc': engineCc,
        'torque': torque,
        'rangeKm': rangeKm,
        'zeroToHundred': zeroToHundred,
        'batteryKwh': batteryKwh,
        'color': color,
        'drivetrain': drivetrain,
      };
}

class Inspection {
  String hood, roof, frontBumper, rearBumper;
  String leftFrontDoor, rightFrontDoor, leftRearDoor, rightRearDoor;
  double tramerAmount;

  Inspection({
    this.hood = 'original',
    this.roof = 'original',
    this.frontBumper = 'original',
    this.rearBumper = 'original',
    this.leftFrontDoor = 'original',
    this.rightFrontDoor = 'original',
    this.leftRearDoor = 'original',
    this.rightRearDoor = 'original',
    this.tramerAmount = 0,
  });

  bool get hasDamage =>
      tramerAmount > 0 ||
      [
        hood,
        roof,
        frontBumper,
        rearBumper,
        leftFrontDoor,
        rightFrontDoor,
        leftRearDoor,
        rightRearDoor
      ].any((p) => p != 'original');

  List<String> get _allParts => [
        hood,
        roof,
        frontBumper,
        rearBumper,
        leftFrontDoor,
        rightFrontDoor,
        leftRearDoor,
        rightRearDoor
      ];
  bool get hasPainted => _allParts.any((p) => p == 'painted');
  bool get hasReplaced => _allParts.any((p) => p == 'replaced');

  factory Inspection.fromJson(Map<String, dynamic> j) => Inspection(
        hood: (j['hood'] ?? 'original').toString(),
        roof: (j['roof'] ?? 'original').toString(),
        frontBumper: (j['frontBumper'] ?? 'original').toString(),
        rearBumper: (j['rearBumper'] ?? 'original').toString(),
        leftFrontDoor: (j['leftFrontDoor'] ?? 'original').toString(),
        rightFrontDoor: (j['rightFrontDoor'] ?? 'original').toString(),
        leftRearDoor: (j['leftRearDoor'] ?? 'original').toString(),
        rightRearDoor: (j['rightRearDoor'] ?? 'original').toString(),
        tramerAmount: _d(j['tramerAmount']),
      );

  Map<String, dynamic> toJson() => {
        'hood': hood,
        'roof': roof,
        'frontBumper': frontBumper,
        'rearBumper': rearBumper,
        'leftFrontDoor': leftFrontDoor,
        'rightFrontDoor': rightFrontDoor,
        'leftRearDoor': leftRearDoor,
        'rightRearDoor': rightRearDoor,
        'tramerAmount': tramerAmount,
      };
}

class Vehicle {
  String id, brand, model, trimPackage, currency, plate;
  String fuelType, transmission, bodyType, locationId, description;
  double price;
  int year, mileage;
  bool isHotDeal, isLoanEligible, acceptsTradeIn, inStock;
  Specs specs;
  Inspection inspection;
  List<String> images;

  Vehicle({
    this.id = '',
    this.brand = '',
    this.model = '',
    this.trimPackage = '',
    this.plate = '',
    this.currency = '\$',
    this.fuelType = 'petrol',
    this.transmission = 'automatic',
    this.bodyType = 'suv',
    this.locationId = '',
    this.description = '',
    this.price = 0,
    this.year = 2024,
    this.mileage = 0,
    this.isHotDeal = false,
    this.isLoanEligible = false,
    this.acceptsTradeIn = false,
    this.inStock = true,
    Specs? specs,
    Inspection? inspection,
    List<String>? images,
  })  : specs = specs ?? Specs(),
        inspection = inspection ?? Inspection(),
        images = images ?? [];

  String get fullName => '$brand $model';

  factory Vehicle.fromJson(Map<String, dynamic> j) => Vehicle(
        id: (j['id'] ?? '').toString(),
        brand: (j['brand'] ?? '').toString(),
        model: (j['model'] ?? '').toString(),
        trimPackage: (j['trimPackage'] ?? '').toString(),
        plate: (j['plate'] ?? '').toString(),
        currency: (j['currency'] ?? '\$').toString(),
        fuelType: (j['fuelType'] ?? 'petrol').toString(),
        transmission: (j['transmission'] ?? 'automatic').toString(),
        bodyType: (j['bodyType'] ?? 'suv').toString(),
        locationId: (j['locationId'] ?? '').toString(),
        description: (j['description'] ?? '').toString(),
        price: _d(j['price']),
        year: _i(j['year']),
        mileage: _i(j['mileage']),
        isHotDeal: j['isHotDeal'] == true,
        isLoanEligible: j['isLoanEligible'] == true,
        acceptsTradeIn: j['acceptsTradeIn'] == true,
        inStock: j['inStock'] == true,
        specs: Specs.fromJson((j['specs'] ?? {}) as Map<String, dynamic>),
        inspection:
            Inspection.fromJson((j['inspection'] ?? {}) as Map<String, dynamic>),
        images: ((j['images'] ?? []) as List).map((e) => '$e').toList(),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'brand': brand,
        'model': model,
        'trimPackage': trimPackage,
        'plate': plate,
        'currency': currency,
        'fuelType': fuelType,
        'transmission': transmission,
        'bodyType': bodyType,
        'locationId': locationId,
        'description': description,
        'price': price,
        'year': year,
        'mileage': mileage,
        'isHotDeal': isHotDeal,
        'isLoanEligible': isLoanEligible,
        'acceptsTradeIn': acceptsTradeIn,
        'inStock': inStock,
        'specs': specs.toJson(),
        'inspection': inspection.toJson(),
        'images': images,
      };
}

class GLocation {
  String id, name, city, address;
  double latitude, longitude;

  GLocation({
    this.id = '',
    this.name = '',
    this.city = '',
    this.address = '',
    this.latitude = 0,
    this.longitude = 0,
  });

  factory GLocation.fromJson(Map<String, dynamic> j) => GLocation(
        id: (j['id'] ?? '').toString(),
        name: (j['name'] ?? '').toString(),
        city: (j['city'] ?? '').toString(),
        address: (j['address'] ?? '').toString(),
        latitude: _d(j['latitude']),
        longitude: _d(j['longitude']),
      );
}

// Demand-side records (mirror the backend).
const List<String> kOrderStatuses = [
  'PENDING', 'CONFIRMED', 'READY', 'COMPLETED', 'CANCELLED'
];

class AdminOrder {
  String id, vehicleId, customerName, phone, email, type, status, note;
  String targetLocationId;
  int createdAt;
  AdminOrder({
    this.id = '',
    this.vehicleId = '',
    this.customerName = '',
    this.phone = '',
    this.email = '',
    this.type = 'RESERVE',
    this.status = 'PENDING',
    this.note = '',
    this.targetLocationId = '',
    this.createdAt = 0,
  });
  factory AdminOrder.fromJson(Map<String, dynamic> j) => AdminOrder(
        id: (j['id'] ?? '').toString(),
        vehicleId: (j['vehicleId'] ?? '').toString(),
        customerName: (j['customerName'] ?? '').toString(),
        phone: (j['phone'] ?? '').toString(),
        email: (j['email'] ?? '').toString(),
        type: (j['type'] ?? 'RESERVE').toString(),
        status: (j['status'] ?? 'PENDING').toString(),
        note: (j['note'] ?? '').toString(),
        targetLocationId: (j['targetLocationId'] ?? '').toString(),
        createdAt: _i(j['createdAt']),
      );
  Map<String, dynamic> toJson() => {
        'id': id,
        'vehicleId': vehicleId,
        'customerName': customerName,
        'phone': phone,
        'email': email,
        'type': type,
        'status': status,
        'note': note,
        'targetLocationId': targetLocationId,
        'createdAt': createdAt,
      };
}

// =============================================================================
// API + STORE
// =============================================================================

class Api {
  final Dio _dio = Dio(BaseOptions(
    baseUrl: kApiBase,
    connectTimeout: const Duration(seconds: 8),
    receiveTimeout: const Duration(seconds: 8),
    headers: {
      // HTTP Basic auth for the admin-only endpoints (SecurityConfig).
      'authorization':
          'Basic ${base64Encode(utf8.encode('$kAdminUser:$kAdminPass'))}',
    },
  ));

  Future<List<Vehicle>> getVehicles() async {
    final r = await _dio.get('/api/vehicles');
    return (r.data as List)
        .map((e) => Vehicle.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<GLocation>> getLocations() async {
    final r = await _dio.get('/api/locations');
    return (r.data as List)
        .map((e) => GLocation.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Vehicle> createVehicle(Vehicle v) async {
    final r = await _dio.post('/api/vehicles', data: v.toJson());
    return Vehicle.fromJson(r.data as Map<String, dynamic>);
  }

  Future<Vehicle> updateVehicle(Vehicle v) async {
    final r = await _dio.put('/api/vehicles/${v.id}', data: v.toJson());
    return Vehicle.fromJson(r.data as Map<String, dynamic>);
  }

  Future<void> deleteVehicle(String id) async {
    await _dio.delete('/api/vehicles/$id');
  }

  // ---- Demand side ----
  Future<List<AdminOrder>> getOrders() async {
    final r = await _dio.get('/api/orders');
    return (r.data as List)
        .map((e) => AdminOrder.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<AdminOrder> updateOrder(AdminOrder o) async {
    final r = await _dio.put('/api/orders/${o.id}', data: o.toJson());
    return AdminOrder.fromJson(r.data as Map<String, dynamic>);
  }

  Future<void> deleteOrder(String id) async {
    await _dio.delete('/api/orders/$id');
  }
}

class AdminStore extends ChangeNotifier {
  final Api api = Api();
  List<Vehicle> vehicles = [];
  List<GLocation> locations = [];
  List<AdminOrder> orders = [];
  bool loading = false;
  String? error;

  Future<void> load() async {
    loading = true;
    error = null;
    notifyListeners();
    try {
      vehicles = await api.getVehicles();
      locations = await api.getLocations();
      orders = await api.getOrders();
    } catch (e) {
      error =
          'Could not reach the backend at $kApiBase.\nIs it running?  (cd anil-backend && mvn spring-boot:run)';
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  GLocation? locationById(String id) {
    for (final l in locations) {
      if (l.id == id) return l;
    }
    return null;
  }

  String locationName(String id) => locationById(id)?.name ?? '—';

  int countAt(String locationId) =>
      vehicles.where((v) => v.locationId == locationId).length;

  Map<String, int> countBy(String Function(Vehicle) key) {
    final m = <String, int>{};
    for (final v in vehicles) {
      final k = key(v);
      m[k] = (m[k] ?? 0) + 1;
    }
    return m;
  }

  Future<void> saveVehicle(Vehicle v, {required bool isNew}) async {
    final saved = isNew ? await api.createVehicle(v) : await api.updateVehicle(v);
    final idx = vehicles.indexWhere((x) => x.id == saved.id);
    if (idx >= 0) {
      vehicles[idx] = saved;
    } else {
      vehicles.add(saved);
    }
    notifyListeners();
  }

  Future<void> deleteVehicle(String id) async {
    await api.deleteVehicle(id);
    vehicles.removeWhere((v) => v.id == id);
    notifyListeners();
  }

  // Reassign a car to another gallery (or '' for the warehouse) — used by the
  // Distribution view. Uses the existing update endpoint.
  Future<void> moveVehicle(Vehicle v, String locationId) async {
    v.locationId = locationId;
    await api.updateVehicle(v);
    notifyListeners();
  }

  // Apply a change to many cars at once (bulk actions in Inventory).
  Future<void> bulkUpdate(Iterable<Vehicle> cars, void Function(Vehicle) apply) async {
    for (final v in cars) {
      apply(v);
      await api.updateVehicle(v);
    }
    notifyListeners();
  }

  Future<void> bulkDelete(Iterable<String> ids) async {
    for (final id in ids.toList()) {
      await api.deleteVehicle(id);
      vehicles.removeWhere((v) => v.id == id);
    }
    notifyListeners();
  }

  // ---- Demand side ----
  Future<void> updateOrder(AdminOrder o) async {
    final saved = await api.updateOrder(o);
    final i = orders.indexWhere((x) => x.id == saved.id);
    if (i >= 0) orders[i] = saved;
    notifyListeners();
  }

  Future<void> deleteOrder(String id) async {
    await api.deleteOrder(id);
    orders.removeWhere((o) => o.id == id);
    notifyListeners();
  }

  int get pendingOrders =>
      orders.where((o) => o.status == 'PENDING').length;

  String vehicleName(String id) {
    for (final v in vehicles) {
      if (v.id == id) return v.fullName;
    }
    return id.isEmpty ? '—' : id;
  }
}

final AdminStore store = AdminStore();

// =============================================================================
// APP + SHELL
// =============================================================================

class AdminApp extends StatelessWidget {
  const AdminApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Anıl Galeri Admin',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        scaffoldBackgroundColor: C.bg,
        colorScheme: ColorScheme.fromSeed(
            seedColor: C.gold, primary: C.text, brightness: Brightness.light),
        fontFamily: 'Roboto',
      ),
      home: const AdminShell(),
    );
  }
}

class AdminShell extends StatefulWidget {
  const AdminShell({super.key});

  @override
  State<AdminShell> createState() => _AdminShellState();
}

class _AdminShellState extends State<AdminShell> {
  int _index = 0;

  // Drill-down filters set by tapping a dashboard chart bar; consumed by the
  // Inventory page when we switch to it.
  String? _invBody;
  String? _invFuel;
  String? _invLoc;

  static const _titles = [
    'Dashboard', 'Inventory', 'Distribution', 'Orders', 'Pre-orders'
  ];

  @override
  void initState() {
    super.initState();
    store.load();
  }

  Widget _page() {
    switch (_index) {
      case 1:
        return InventoryPage(
            initialBody: _invBody,
            initialFuel: _invFuel,
            initialLoc: _invLoc);
      case 2:
        return DistributionPage(onOpen: (loc) => _drill(loc: loc));
      case 3:
        return const OrdersPage();
      case 4:
        return const PreOrdersPage();
      default:
        return DashboardPage(onDrill: _drill);
    }
  }

  // From a dashboard chart bar -> jump to Inventory pre-filtered.
  void _drill({String? body, String? fuel, String? loc}) {
    setState(() {
      _invBody = body;
      _invFuel = fuel;
      _invLoc = loc;
      _index = 1;
    });
  }

  Widget _sidebar({required bool drawer}) {
    return Container(
      width: 240,
      color: C.sidebar,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 28),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 22),
            child: Row(
              children: [
                Container(
                  width: 34,
                  height: 34,
                  decoration: BoxDecoration(
                      color: C.gold, borderRadius: BorderRadius.circular(9)),
                  child: const Icon(Icons.directions_car,
                      color: Colors.black, size: 20),
                ),
                const SizedBox(width: 10),
                const Text('Anıl Galeri',
                    style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w900,
                        fontSize: 16)),
              ],
            ),
          ),
          const SizedBox(height: 8),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 22),
            child: Text('ADMIN PANEL',
                style: TextStyle(
                    color: C.muted, fontSize: 10, letterSpacing: 1.4)),
          ),
          const SizedBox(height: 24),
          _NavItem(
              icon: Icons.dashboard_outlined,
              label: 'Dashboard',
              selected: _index == 0,
              onTap: () => _go(0, drawer)),
          _NavItem(
              icon: Icons.inventory_2_outlined,
              label: 'Inventory',
              selected: _index == 1,
              onTap: () => _go(1, drawer)),
          _NavItem(
              icon: Icons.hub_outlined,
              label: 'Distribution',
              selected: _index == 2,
              onTap: () => _go(2, drawer)),
          _NavItem(
              icon: Icons.receipt_long_outlined,
              label: 'Orders',
              selected: _index == 3,
              onTap: () => _go(3, drawer)),
          _NavItem(
              icon: Icons.schedule_send_outlined,
              label: 'Pre-orders',
              selected: _index == 4,
              onTap: () => _go(4, drawer)),
          const Spacer(),
          Padding(
            padding: const EdgeInsets.all(18),
            child: Text('Connected to\n$kApiBase',
                style: const TextStyle(color: C.muted, fontSize: 11)),
          ),
        ],
      ),
    );
  }

  void _go(int i, bool drawer) {
    setState(() {
      _index = i;
      // Sidebar navigation shows the full, unfiltered view.
      _invBody = null;
      _invFuel = null;
      _invLoc = null;
    });
    if (drawer) Navigator.pop(context);
  }

  Widget _topBar(bool wide) {
    return Container(
      height: 64,
      padding: const EdgeInsets.symmetric(horizontal: 24),
      decoration: const BoxDecoration(
        color: C.card,
        border: Border(bottom: BorderSide(color: C.border)),
      ),
      child: Row(
        children: [
          if (!wide)
            Builder(
              builder: (ctx) => IconButton(
                icon: const Icon(Icons.menu),
                onPressed: () => Scaffold.of(ctx).openDrawer(),
              ),
            ),
          Text(_titles[_index],
              style: const TextStyle(
                  fontSize: 20, fontWeight: FontWeight.w900, color: C.text)),
          const Spacer(),
          OutlinedButton.icon(
            onPressed: () => store.load(),
            icon: const Icon(Icons.refresh, size: 18),
            label: const Text('Refresh'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 900;
        final content = Column(
          children: [
            _topBar(wide),
            Expanded(
              child: ListenableBuilder(
                listenable: store,
                builder: (context, _) {
                  if (store.loading && store.vehicles.isEmpty) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  if (store.error != null && store.vehicles.isEmpty) {
                    return _ErrorView(
                        message: store.error!, onRetry: () => store.load());
                  }
                  return _page();
                },
              ),
            ),
          ],
        );

        if (wide) {
          return Scaffold(
            body: Row(
              children: [
                _sidebar(drawer: false),
                Expanded(child: content),
              ],
            ),
          );
        }
        return Scaffold(
          drawer: Drawer(child: _sidebar(drawer: true)),
          body: content,
        );
      },
    );
  }
}

class _NavItem extends StatelessWidget {
  final IconData icon;
  final String label;
  final bool selected;
  final VoidCallback onTap;
  const _NavItem(
      {required this.icon,
      required this.label,
      required this.selected,
      required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
      child: Material(
        color: selected ? C.sidebarSel : Colors.transparent,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            child: Row(
              children: [
                Icon(icon,
                    size: 20, color: selected ? C.gold : C.muted),
                const SizedBox(width: 12),
                Text(label,
                    style: TextStyle(
                        color: selected ? Colors.white : C.muted,
                        fontWeight:
                            selected ? FontWeight.w800 : FontWeight.w600)),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;
  const _ErrorView({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Container(
        constraints: const BoxConstraints(maxWidth: 440),
        padding: const EdgeInsets.all(28),
        margin: const EdgeInsets.all(24),
        decoration: BoxDecoration(
            color: C.card,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: C.border)),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off, size: 44, color: C.red),
            const SizedBox(height: 14),
            const Text('Backend not reachable',
                style: TextStyle(fontWeight: FontWeight.w900, fontSize: 16)),
            const SizedBox(height: 8),
            Text(message,
                textAlign: TextAlign.center,
                style: const TextStyle(color: C.muted)),
            const SizedBox(height: 18),
            FilledButton.icon(
              onPressed: onRetry,
              style: FilledButton.styleFrom(backgroundColor: C.text),
              icon: const Icon(Icons.refresh),
              label: const Text('Try again'),
            ),
          ],
        ),
      ),
    );
  }
}

// =============================================================================
// DASHBOARD
// =============================================================================

class DashboardPage extends StatelessWidget {
  final void Function({String? body, String? fuel, String? loc}) onDrill;
  const DashboardPage({super.key, required this.onDrill});

  @override
  Widget build(BuildContext context) {
    final v = store.vehicles;
    final inWarehouse = v.where((c) => c.locationId.trim().isEmpty).length;
    final inGalleries = v.length - inWarehouse;
    final totalValue = v.fold<double>(0, (s, c) => s + c.price);
    final hotDeals = v.where((c) => c.isHotDeal).length;
    final damaged = v.where((c) => c.inspection.hasDamage).length;
    final avgPrice = v.isEmpty ? 0.0 : totalValue / v.length;
    final avgMileage =
        v.isEmpty ? 0 : (v.fold<int>(0, (s, c) => s + c.mileage) / v.length).round();

    // Each bar carries a display label, a count, and the value to filter by.
    final locationData = store.locations
        .map((l) => _BarDatum(l.name, store.countAt(l.id), l.id))
        .toList();
    final byBody = store.countBy((c) => c.bodyType);
    final bodyData =
        byBody.entries.map((e) => _BarDatum(e.key, e.value, e.key)).toList();
    final byFuel = store.countBy((c) => c.fuelType);
    final fuelData =
        byFuel.entries.map((e) => _BarDatum(e.key, e.value, e.key)).toList();

    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 16,
            runSpacing: 16,
            children: [
              _Kpi(
                  label: 'Total inventory',
                  value: '${v.length}',
                  icon: Icons.inventory_2,
                  color: C.blue),
              _Kpi(
                  label: 'In galleries',
                  value: '$inGalleries',
                  icon: Icons.storefront,
                  color: C.green),
              _Kpi(
                  label: 'In warehouse',
                  value: '$inWarehouse',
                  icon: Icons.warehouse,
                  color: C.gold),
              _Kpi(
                  label: 'Total value',
                  value: money(totalValue),
                  icon: Icons.payments,
                  color: C.text),
              _Kpi(
                  label: 'Hot deals',
                  value: '$hotDeals',
                  icon: Icons.local_fire_department,
                  color: C.red),
              _Kpi(
                  label: 'Damaged / painted',
                  value: '$damaged',
                  icon: Icons.report_problem,
                  color: C.muted),
              _Kpi(
                  label: 'Avg price',
                  value: money(avgPrice),
                  icon: Icons.sell,
                  color: C.blue),
              _Kpi(
                  label: 'Avg mileage',
                  value: '${thousands(avgMileage)} km',
                  icon: Icons.speed,
                  color: C.gold),
            ],
          ),
          const SizedBox(height: 24),
          LayoutBuilder(builder: (context, cons) {
            final twoCol = cons.maxWidth >= 760;
            final locationCard = _ChartCard(
                title: 'Inventory by location',
                child: _BarList(
                    data: locationData,
                    color: C.blue,
                    onTap: (id) => onDrill(loc: id)));
            final bodyCard = _ChartCard(
                title: 'By body type',
                child: _BarList(
                    data: bodyData,
                    color: C.gold,
                    onTap: (b) => onDrill(body: b)));
            final fuelCard = _ChartCard(
                title: 'By fuel type',
                child: _BarList(
                    data: fuelData,
                    color: C.green,
                    onTap: (f) => onDrill(fuel: f)));
            if (twoCol) {
              return Column(
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(child: locationCard),
                      const SizedBox(width: 16),
                      Expanded(child: bodyCard),
                    ],
                  ),
                  const SizedBox(height: 16),
                  fuelCard,
                ],
              );
            }
            return Column(
              children: [
                locationCard,
                const SizedBox(height: 16),
                bodyCard,
                const SizedBox(height: 16),
                fuelCard,
              ],
            );
          }),
        ],
      ),
    );
  }
}

class _Kpi extends StatelessWidget {
  final String label, value;
  final IconData icon;
  final Color color;
  const _Kpi(
      {required this.label,
      required this.value,
      required this.icon,
      required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 210,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
          color: C.card,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: C.border)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                    color: color.withOpacity(0.12),
                    borderRadius: BorderRadius.circular(9)),
                child: Icon(icon, color: color, size: 18),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Text(value,
              style: const TextStyle(
                  fontSize: 26, fontWeight: FontWeight.w900, color: C.text)),
          const SizedBox(height: 2),
          Text(label, style: const TextStyle(color: C.muted, fontSize: 13)),
        ],
      ),
    );
  }
}

class _ChartCard extends StatelessWidget {
  final String title;
  final Widget child;
  const _ChartCard({required this.title, required this.child});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
          color: C.card,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: C.border)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title,
              style:
                  const TextStyle(fontWeight: FontWeight.w900, fontSize: 15)),
          const SizedBox(height: 16),
          child,
        ],
      ),
    );
  }
}

class _BarDatum {
  final String label; // shown to the user
  final int value; // count
  final String drill; // value to filter Inventory by
  const _BarDatum(this.label, this.value, this.drill);
}

class _BarList extends StatelessWidget {
  final List<_BarDatum> data;
  final Color color;
  final void Function(String drill)? onTap;
  const _BarList({required this.data, required this.color, this.onTap});

  @override
  Widget build(BuildContext context) {
    if (data.isEmpty) {
      return const Text('No data', style: TextStyle(color: C.muted));
    }
    final entries = [...data]..sort((a, b) => b.value.compareTo(a.value));
    final max = entries.first.value;
    return Column(
      children: entries.map((e) {
        final frac = max == 0 ? 0.0 : e.value / max;
        final row = Padding(
          padding: const EdgeInsets.symmetric(vertical: 5),
          child: Row(
            children: [
              SizedBox(
                width: 130,
                child: Text(e.label,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 13, color: C.text)),
              ),
              Expanded(
                child: SizedBox(
                  height: 18,
                  child: Stack(
                    children: [
                      Container(
                        decoration: BoxDecoration(
                            color: C.bg,
                            borderRadius: BorderRadius.circular(6)),
                      ),
                      FractionallySizedBox(
                        alignment: Alignment.centerLeft,
                        widthFactor: frac.clamp(0.0, 1.0),
                        child: Container(
                          decoration: BoxDecoration(
                              color: color,
                              borderRadius: BorderRadius.circular(6)),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              SizedBox(
                width: 34,
                child: Text('${e.value}',
                    textAlign: TextAlign.right,
                    style: const TextStyle(
                        fontWeight: FontWeight.w800, fontSize: 13)),
              ),
            ],
          ),
        );
        if (onTap == null) return row;
        return InkWell(
          borderRadius: BorderRadius.circular(8),
          onTap: () => onTap!(e.drill),
          child: row,
        );
      }).toList(),
    );
  }
}

// =============================================================================
// INVENTORY
// =============================================================================

class InventoryPage extends StatefulWidget {
  final String? initialBody;
  final String? initialFuel;
  final String? initialLoc;
  const InventoryPage(
      {super.key, this.initialBody, this.initialFuel, this.initialLoc});

  @override
  State<InventoryPage> createState() => _InventoryPageState();
}

class _InventoryPageState extends State<InventoryPage> {
  String _q = '';
  String? _body;
  String? _fuel;
  String? _loc;
  bool _hotOnly = false;
  String? _cond; // null=all, 'clean', 'painted', 'replaced'

  // Range filters.
  RangeValues _price = const RangeValues(0, 300000);
  RangeValues _year = const RangeValues(2010, 2026);

  // Sorting.
  int? _sortCol;
  bool _sortAsc = true;

  @override
  void initState() {
    super.initState();
    // Pre-apply any drill-down filter passed from the dashboard charts.
    _body = widget.initialBody;
    _fuel = widget.initialFuel;
    _loc = widget.initialLoc;
  }

  List<Vehicle> get _filtered {
    final list = store.vehicles.where((v) {
      if (_q.isNotEmpty &&
          !v.fullName.toLowerCase().contains(_q.toLowerCase()) &&
          !v.plate.toLowerCase().contains(_q.toLowerCase())) {
        return false;
      }
      if (_body != null && v.bodyType != _body) return false;
      if (_fuel != null && v.fuelType != _fuel) return false;
      if (_loc != null && v.locationId != _loc) return false;
      if (_hotOnly && !v.isHotDeal) return false;
      if (_cond == 'clean' && v.inspection.hasDamage) return false;
      if (_cond == 'painted' && !v.inspection.hasPainted) return false;
      if (_cond == 'replaced' && !v.inspection.hasReplaced) return false;
      if (v.price < _price.start || v.price > _price.end) return false;
      if (v.year < _year.start || v.year > _year.end) return false;
      return true;
    }).toList();

    if (_sortCol != null) {
      int cmp(Vehicle a, Vehicle b) {
        switch (_sortCol) {
          case 0:
            return a.fullName.toLowerCase().compareTo(b.fullName.toLowerCase());
          case 1:
            return a.year.compareTo(b.year);
          case 2:
            return a.price.compareTo(b.price);
          default:
            return 0;
        }
      }

      list.sort((a, b) => _sortAsc ? cmp(a, b) : cmp(b, a));
    }
    return list;
  }

  void _onSort(int col, bool asc) {
    setState(() {
      _sortCol = col;
      _sortAsc = asc;
    });
  }

  void _exportCsv(List<Vehicle> list) {
    final buf = StringBuffer(
        'id,brand,model,trim,plate,price,year,mileage,fuel,transmission,body,location,damaged\n');
    for (final v in list) {
      String esc(String s) => '"${s.replaceAll('"', '""')}"';
      buf.writeln([
        v.id,
        esc(v.brand),
        esc(v.model),
        esc(v.trimPackage),
        esc(v.plate),
        v.price.round(),
        v.year,
        v.mileage,
        v.fuelType,
        v.transmission,
        v.bodyType,
        esc(store.locationName(v.locationId)),
        v.inspection.hasDamage,
      ].join(','));
    }
    Clipboard.setData(ClipboardData(text: buf.toString()));
    _toast('CSV for ${list.length} cars copied to clipboard');
  }

  void _openDetail(Vehicle v) {
    showDialog(context: context, builder: (_) => VehicleDetailDialog(v: v));
  }

  void _toast(String msg, {bool error = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(msg),
        backgroundColor: error ? C.red : C.text));
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: store,
      builder: (context, _) {
        final list = _filtered;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 20, 24, 8),
              child: Wrap(
                spacing: 12,
                runSpacing: 12,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  SizedBox(
                    width: 240,
                    child: TextField(
                      decoration: const InputDecoration(
                        isDense: true,
                        prefixIcon: Icon(Icons.search, size: 20),
                        hintText: 'Search brand or model',
                        border: OutlineInputBorder(),
                      ),
                      onChanged: (s) => setState(() => _q = s),
                    ),
                  ),
                  _FilterDropdown(
                      hint: 'Body',
                      value: _body,
                      options: kBodyOptions,
                      onChanged: (v) => setState(() => _body = v)),
                  _FilterDropdown(
                      hint: 'Fuel',
                      value: _fuel,
                      options: kFuelOptions,
                      onChanged: (v) => setState(() => _fuel = v)),
                  _FilterDropdown(
                      hint: 'Location',
                      value: _loc,
                      options: ['', ...store.locations.map((l) => l.id)],
                      labels: {
                        '': 'Warehouse',
                        for (final l in store.locations) l.id: l.name
                      },
                      onChanged: (v) => setState(() => _loc = v)),
                  FilterChip(
                    label: const Text('Hot deals'),
                    selected: _hotOnly,
                    onSelected: (s) => setState(() => _hotOnly = s),
                  ),
                  _FilterDropdown(
                      hint: 'Condition',
                      value: _cond,
                      options: const ['clean', 'painted', 'replaced'],
                      labels: const {
                        'clean': 'Clean',
                        'painted': 'Painted',
                        'replaced': 'Replaced'
                      },
                      onChanged: (v) => setState(() => _cond = v)),
                  const Spacer(),
                  OutlinedButton.icon(
                    onPressed: () => _exportCsv(list),
                    icon: const Icon(Icons.download, size: 18),
                    label: const Text('Export CSV'),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24),
              child: Row(
                children: [
                  _RangeFilter(
                    label: 'Price',
                    values: _price,
                    min: 0,
                    max: 300000,
                    divisions: 30,
                    fmt: (d) => money(d),
                    onChanged: (r) => setState(() => _price = r),
                  ),
                  const SizedBox(width: 24),
                  _RangeFilter(
                    label: 'Year',
                    values: _year,
                    min: 2010,
                    max: 2026,
                    divisions: 16,
                    fmt: (d) => '${d.round()}',
                    onChanged: (r) => setState(() => _year = r),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24),
              child: Row(
                children: [
                  Text('${list.length} of ${store.vehicles.length} vehicles',
                      style: const TextStyle(color: C.muted, fontSize: 13)),
                ],
              ),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
                child: Container(
                  width: double.infinity,
                  decoration: BoxDecoration(
                      color: C.card,
                      borderRadius: BorderRadius.circular(14),
                      border: Border.all(color: C.border)),
                  child: list.isEmpty
                      ? const Center(
                          child: Text('No vehicles match your filters',
                              style: TextStyle(color: C.muted)))
                      : SingleChildScrollView(
                          child: SingleChildScrollView(
                            scrollDirection: Axis.horizontal,
                            child: DataTable(
                              headingRowColor: WidgetStatePropertyAll(C.bg),
                              showCheckboxColumn: false,
                              sortColumnIndex: _sortCol,
                              sortAscending: _sortAsc,
                              columns: [
                                DataColumn(
                                    label: const Text('Vehicle'),
                                    onSort: (i, asc) => _onSort(i, asc)),
                                DataColumn(
                                    label: const Text('Year'),
                                    numeric: true,
                                    onSort: (i, asc) => _onSort(i, asc)),
                                DataColumn(
                                    label: const Text('Price'),
                                    numeric: true,
                                    onSort: (i, asc) => _onSort(i, asc)),
                                const DataColumn(label: Text('Fuel')),
                                const DataColumn(label: Text('Body')),
                                const DataColumn(label: Text('Location')),
                                const DataColumn(label: Text('Condition')),
                                const DataColumn(label: Text('')),
                              ],
                              rows: list.map((v) {
                                return DataRow(
                                  cells: [
                                  DataCell(Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Text(v.fullName,
                                          style: const TextStyle(
                                              fontWeight: FontWeight.w700)),
                                      if (v.isHotDeal) ...[
                                        const SizedBox(width: 8),
                                        _Pill(text: 'HOT', color: C.gold),
                                      ],
                                      const SizedBox(width: 8),
                                      if (v.plate.isNotEmpty)
                                        Container(
                                          padding: const EdgeInsets.symmetric(
                                              horizontal: 6, vertical: 2),
                                          decoration: BoxDecoration(
                                            color: Colors.white,
                                            border:
                                                Border.all(color: C.border),
                                            borderRadius:
                                                BorderRadius.circular(4),
                                          ),
                                          child: Text(v.plate,
                                              style: const TextStyle(
                                                  fontSize: 11,
                                                  fontWeight: FontWeight.w700,
                                                  letterSpacing: 0.5)),
                                        )
                                      else
                                        Text('— no plate —',
                                            style: TextStyle(
                                                fontSize: 11,
                                                fontStyle: FontStyle.italic,
                                                color: C.muted)),
                                    ],
                                  )),
                                  DataCell(Text('${v.year}')),
                                  DataCell(Text(money(v.price))),
                                  DataCell(Text(v.fuelType)),
                                  DataCell(Text(v.bodyType)),
                                  DataCell(Text(store.locationName(v.locationId))),
                                  DataCell(_Pill(
                                      text: v.inspection.hasReplaced
                                          ? 'Replaced'
                                          : v.inspection.hasPainted
                                              ? 'Painted'
                                              : 'Clean',
                                      color: v.inspection.hasReplaced
                                          ? C.red
                                          : v.inspection.hasPainted
                                              ? C.gold
                                              : C.muted)),
                                  DataCell(Row(
                                    children: [
                                      IconButton(
                                          tooltip: 'View',
                                          icon: const Icon(
                                              Icons.visibility_outlined,
                                              size: 19),
                                          onPressed: () => _openDetail(v)),
                                    ],
                                  )),
                                ]);
                              }).toList(),
                            ),
                          ),
                        ),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

class _Pill extends StatelessWidget {
  final String text;
  final Color color;
  const _Pill({required this.text, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
          color: color.withOpacity(0.12),
          borderRadius: BorderRadius.circular(20)),
      child: Text(text,
          style: TextStyle(
              color: color, fontSize: 12, fontWeight: FontWeight.w700)),
    );
  }
}

class _RangeFilter extends StatelessWidget {
  final String label;
  final RangeValues values;
  final double min;
  final double max;
  final int divisions;
  final String Function(double) fmt;
  final ValueChanged<RangeValues> onChanged;
  const _RangeFilter(
      {required this.label,
      required this.values,
      required this.min,
      required this.max,
      required this.divisions,
      required this.fmt,
      required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(label,
                  style: const TextStyle(
                      fontSize: 12,
                      color: C.muted,
                      fontWeight: FontWeight.w700)),
              const Spacer(),
              Text('${fmt(values.start)} – ${fmt(values.end)}',
                  style: const TextStyle(
                      fontSize: 12, fontWeight: FontWeight.w700)),
            ],
          ),
          RangeSlider(
            values: values,
            min: min,
            max: max,
            divisions: divisions,
            activeColor: C.text,
            inactiveColor: C.border,
            onChanged: onChanged,
          ),
        ],
      ),
    );
  }
}

class _FilterDropdown extends StatelessWidget {
  final String hint;
  final String? value;
  final List<String> options;
  final Map<String, String>? labels;
  final ValueChanged<String?> onChanged;
  const _FilterDropdown(
      {required this.hint,
      required this.value,
      required this.options,
      required this.onChanged,
      this.labels});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: BoxDecoration(
          border: Border.all(color: C.border),
          borderRadius: BorderRadius.circular(6)),
      child: DropdownButton<String?>(
        value: value,
        hint: Text(hint),
        underline: const SizedBox.shrink(),
        items: [
          DropdownMenuItem<String?>(value: null, child: Text('All $hint')),
          ...options.map((o) => DropdownMenuItem<String?>(
              value: o, child: Text(labels?[o] ?? o))),
        ],
        onChanged: onChanged,
      ),
    );
  }
}

// =============================================================================
// VEHICLE FORM (add / edit)
// =============================================================================

class VehicleFormDialog extends StatefulWidget {
  final Vehicle? existing;
  const VehicleFormDialog({super.key, this.existing});

  @override
  State<VehicleFormDialog> createState() => _VehicleFormDialogState();
}

class _VehicleFormDialogState extends State<VehicleFormDialog> {
  late Vehicle v;
  final _c = <String, TextEditingController>{};
  final _formKey = GlobalKey<FormState>();

  // Option A: brand is chosen from the makes already in inventory, with an
  // "Add new brand" escape hatch so we're never blocked from a new make.
  late List<String> _brandOptions;
  bool _addingBrand = false;
  static const String _kAddNew = '__add_new_brand__';
  static const Set<String> _decimalKeys = {'price', 'zth', 'battery', 'tramer'};

  TextEditingController _ctrl(String key, String initial) {
    return _c.putIfAbsent(key, () => TextEditingController(text: initial));
  }

  @override
  void initState() {
    super.initState();
    final e = widget.existing;
    v = e == null
        ? Vehicle(
            locationId:
                store.locations.isNotEmpty ? store.locations.first.id : '')
        : Vehicle.fromJson(e.toJson()); // clone so cancel doesn't mutate

    final brands = store.vehicles
        .map((x) => x.brand.trim())
        .where((b) => b.isNotEmpty)
        .toSet();
    if (v.brand.trim().isNotEmpty) brands.add(v.brand.trim());
    _brandOptions = brands.toList()..sort();
  }

  @override
  void dispose() {
    for (final c in _c.values) {
      c.dispose();
    }
    super.dispose();
  }

  void _save() {
    // Block save unless every field passes validation.
    if (!(_formKey.currentState?.validate() ?? false)) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Please fix the highlighted fields')));
      return;
    }
    final s = v.specs;
    final ins = v.inspection;
    v
      ..brand = v.brand.trim()
      ..model = _ctrl('model', v.model).text.trim()
      ..trimPackage = _ctrl('trim', v.trimPackage).text.trim()
      ..plate = _ctrl('plate', v.plate).text.trim().toUpperCase()
      ..price = _d(_ctrl('price', '${v.price}').text)
      ..year = _i(_ctrl('year', '${v.year}').text)
      ..mileage = _i(_ctrl('mileage', '${v.mileage}').text)
      ..description = _ctrl('desc', v.description).text.trim()
      ..images = _ctrl('images', v.images.join('\n'))
          .text
          .split('\n')
          .map((s) => s.trim())
          .where((s) => s.isNotEmpty)
          .toList();
    s
      ..powerHp = _i(_ctrl('powerHp', '${s.powerHp}').text)
      ..topSpeed = _i(_ctrl('topSpeed', '${s.topSpeed}').text)
      ..zeroToHundred = _d(_ctrl('zth', '${s.zeroToHundred}').text)
      ..engineCc = _i(_ctrl('engineCc', '${s.engineCc}').text)
      ..torque = _i(_ctrl('torque', '${s.torque}').text)
      ..batteryKwh = _d(_ctrl('battery', '${s.batteryKwh}').text)
      ..rangeKm = _i(_ctrl('range', '${s.rangeKm}').text)
      ..color = _ctrl('color', s.color).text.trim()
      ..drivetrain = _ctrl('drivetrain', s.drivetrain).text.trim();
    ins.tramerAmount = _d(_ctrl('tramer', '${ins.tramerAmount}').text);

    Navigator.pop(context, v);
  }

  // Per-field validation rules.
  String? _validatorFor(String key, String? raw) {
    final s = (raw ?? '').trim();
    switch (key) {
      case 'model':
        return s.isEmpty ? 'Required' : null;
      case 'price':
        final d = double.tryParse(s);
        if (s.isEmpty || d == null) return 'Enter a price';
        if (d <= 0) return 'Must be > 0';
        return null;
      case 'year':
        final maxY = DateTime.now().year + 1;
        final y = int.tryParse(s);
        if (s.isEmpty || y == null) return 'Enter a year';
        if (y < 1990 || y > maxY) return '1990–$maxY';
        return null;
      case 'mileage':
        final i = int.tryParse(s);
        if (s.isEmpty || i == null) return 'Required';
        if (i < 0) return 'Must be ≥ 0';
        return null;
      case 'powerHp':
      case 'topSpeed':
      case 'engineCc':
      case 'torque':
      case 'range':
        if (s.isEmpty) return null;
        final i = int.tryParse(s);
        if (i == null) return 'Whole number';
        if (i < 0) return '≥ 0';
        return null;
      case 'zth':
      case 'battery':
      case 'tramer':
        if (s.isEmpty) return null;
        final d = double.tryParse(s);
        if (d == null) return 'Number only';
        if (d < 0) return '≥ 0';
        return null;
      default:
        return null;
    }
  }

  @override
  Widget build(BuildContext context) {
    final isNew = widget.existing == null;
    return Dialog(
      child: Container(
        width: 720,
        constraints: const BoxConstraints(maxHeight: 640),
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(isNew ? 'Add vehicle' : 'Edit ${v.fullName}',
                style: const TextStyle(
                    fontSize: 18, fontWeight: FontWeight.w900)),
            const SizedBox(height: 16),
            Expanded(
              child: SingleChildScrollView(
                child: Form(
                  key: _formKey,
                  autovalidateMode: AutovalidateMode.onUserInteraction,
                  child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _section('Basics'),
                    _row([
                      _brandField(),
                      _text('model', 'Model', v.model),
                    ]),
                    _row([
                      _text('trim', 'Trim / package', v.trimPackage),
                      _text('price', 'Price (USD)', '${v.price}', number: true),
                    ]),
                    _row([
                      _text('year', 'Year', '${v.year}', number: true),
                      _text('mileage', 'Mileage (km)', '${v.mileage}',
                          number: true),
                    ]),
                    _row([
                      _text('plate', 'License plate (plaka)', v.plate),
                    ]),
                    _row([
                      _dropdown('Fuel', v.fuelType, kFuelOptions,
                          (s) => setState(() => v.fuelType = s)),
                      _dropdown('Transmission', v.transmission, kTransOptions,
                          (s) => setState(() => v.transmission = s)),
                    ]),
                    _row([
                      _dropdown('Body', v.bodyType, kBodyOptions,
                          (s) => setState(() => v.bodyType = s)),
                      _dropdown(
                          'Location',
                          v.locationId,
                          store.locations.map((l) => l.id).toList(),
                          (s) => setState(() => v.locationId = s),
                          labels: {
                            for (final l in store.locations) l.id: l.name
                          }),
                    ]),
                    Wrap(
                      spacing: 18,
                      children: [
                        _switch('Hot deal', v.isHotDeal,
                            (b) => setState(() => v.isHotDeal = b)),
                        _switch('Accepts trade-in', v.acceptsTradeIn,
                            (b) => setState(() => v.acceptsTradeIn = b)),
                        _switch('Loan eligible', v.isLoanEligible,
                            (b) => setState(() => v.isLoanEligible = b)),
                      ],
                    ),
                    const SizedBox(height: 8),
                    _section('Specs'),
                    _row([
                      _text('powerHp', 'Power (HP)', '${v.specs.powerHp}',
                          number: true),
                      _text('topSpeed', 'Top speed (km/h)',
                          '${v.specs.topSpeed}',
                          number: true),
                    ]),
                    _row([
                      _text('zth', '0-100 (sec)', '${v.specs.zeroToHundred}',
                          number: true),
                      _text('engineCc', 'Engine (cc)', '${v.specs.engineCc}',
                          number: true),
                    ]),
                    _row([
                      _text('torque', 'Torque (Nm)', '${v.specs.torque}',
                          number: true),
                      _text('battery', 'Battery (kWh)', '${v.specs.batteryKwh}',
                          number: true),
                    ]),
                    _row([
                      _text('range', 'Range (km)', '${v.specs.rangeKm}',
                          number: true),
                      _text('color', 'Color', v.specs.color),
                    ]),
                    _row([
                      _text('drivetrain', 'Drivetrain', v.specs.drivetrain),
                      const Expanded(child: SizedBox.shrink()),
                    ]),
                    const SizedBox(height: 8),
                    _section('Condition / expertise'),
                    _row([
                      _partDrop('Hood', v.inspection.hood,
                          (s) => setState(() => v.inspection.hood = s)),
                      _partDrop('Roof', v.inspection.roof,
                          (s) => setState(() => v.inspection.roof = s)),
                    ]),
                    _row([
                      _partDrop('Front bumper', v.inspection.frontBumper,
                          (s) => setState(() => v.inspection.frontBumper = s)),
                      _partDrop('Rear bumper', v.inspection.rearBumper,
                          (s) => setState(() => v.inspection.rearBumper = s)),
                    ]),
                    _row([
                      _partDrop('L front door', v.inspection.leftFrontDoor,
                          (s) =>
                              setState(() => v.inspection.leftFrontDoor = s)),
                      _partDrop('R front door', v.inspection.rightFrontDoor,
                          (s) =>
                              setState(() => v.inspection.rightFrontDoor = s)),
                    ]),
                    _row([
                      _partDrop('L rear door', v.inspection.leftRearDoor,
                          (s) => setState(() => v.inspection.leftRearDoor = s)),
                      _partDrop('R rear door', v.inspection.rightRearDoor,
                          (s) =>
                              setState(() => v.inspection.rightRearDoor = s)),
                    ]),
                    _row([
                      _text('tramer', 'Tramer amount (\$)',
                          '${v.inspection.tramerAmount}',
                          number: true),
                      const Expanded(child: SizedBox.shrink()),
                    ]),
                    const SizedBox(height: 8),
                    _section('Images (one URL per line)'),
                    TextField(
                      controller: _ctrl('images', v.images.join('\n')),
                      maxLines: 3,
                      decoration: const InputDecoration(
                          border: OutlineInputBorder(),
                          hintText: 'https://...'),
                    ),
                    const SizedBox(height: 12),
                    _section('Description'),
                    TextField(
                      controller: _ctrl('desc', v.description),
                      maxLines: 2,
                      decoration:
                          const InputDecoration(border: OutlineInputBorder()),
                    ),
                  ],
                ),
                ),
              ),
            ),
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('Cancel')),
                const SizedBox(width: 8),
                FilledButton(
                  style: FilledButton.styleFrom(backgroundColor: C.text),
                  onPressed: _save,
                  child: Text(isNew ? 'Add vehicle' : 'Save changes'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _section(String t) => Padding(
        padding: const EdgeInsets.only(top: 6, bottom: 10),
        child: Text(t.toUpperCase(),
            style: const TextStyle(
                color: C.muted,
                fontSize: 11,
                fontWeight: FontWeight.w800,
                letterSpacing: 1)),
      );

  Widget _row(List<Widget> children) {
    final spaced = <Widget>[];
    for (var i = 0; i < children.length; i++) {
      spaced.add(children[i]);
      if (i != children.length - 1) spaced.add(const SizedBox(width: 14));
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: spaced),
    );
  }

  Widget _text(String key, String label, String initial,
      {bool number = false}) {
    final isDecimal = _decimalKeys.contains(key);
    final formatters = number
        ? [
            isDecimal
                ? FilteringTextInputFormatter.allow(RegExp(r'[0-9.]'))
                : FilteringTextInputFormatter.digitsOnly
          ]
        : <TextInputFormatter>[];
    return Expanded(
      child: TextFormField(
        controller: _ctrl(key, initial),
        keyboardType: number
            ? const TextInputType.numberWithOptions(decimal: true)
            : TextInputType.text,
        inputFormatters: formatters,
        validator: (s) => _validatorFor(key, s),
        decoration: InputDecoration(
            labelText: label,
            isDense: true,
            border: const OutlineInputBorder()),
      ),
    );
  }

  // Option A brand picker: dropdown of known makes + "Add new brand…".
  Widget _brandField() {
    if (_addingBrand) {
      return Expanded(
        child: TextFormField(
          controller: _ctrl('newBrand', v.brand),
          autofocus: true,
          textCapitalization: TextCapitalization.words,
          onChanged: (s) => v.brand = s.trim(),
          validator: (s) =>
              (s == null || s.trim().isEmpty) ? 'Enter a brand' : null,
          decoration: InputDecoration(
            labelText: 'New brand',
            isDense: true,
            border: const OutlineInputBorder(),
            suffixIcon: IconButton(
              tooltip: 'Pick from list',
              icon: const Icon(Icons.list, size: 20),
              onPressed: () => setState(() {
                _addingBrand = false;
                v.brand = '';
                _c['newBrand']?.clear();
              }),
            ),
          ),
        ),
      );
    }
    final value = _brandOptions.contains(v.brand) ? v.brand : null;
    return Expanded(
      child: DropdownButtonFormField<String>(
        value: value,
        isExpanded: true,
        decoration: InputDecoration(
            labelText: 'Brand',
            isDense: true,
            border: const OutlineInputBorder()),
        validator: (s) =>
            (s == null || s.isEmpty) ? 'Select a brand' : null,
        items: [
          ..._brandOptions.map(
              (b) => DropdownMenuItem(value: b, child: Text(b))),
          const DropdownMenuItem(
              value: _kAddNew,
              child: Text('+ Add new brand…',
                  style: TextStyle(fontStyle: FontStyle.italic))),
        ],
        onChanged: (s) {
          if (s == null) return;
          if (s == _kAddNew) {
            setState(() {
              _addingBrand = true;
              v.brand = '';
            });
          } else {
            setState(() => v.brand = s);
          }
        },
      ),
    );
  }

  Widget _dropdown(String label, String value, List<String> options,
      ValueChanged<String> onChanged,
      {Map<String, String>? labels}) {
    final safe = options.contains(value)
        ? value
        : (options.isNotEmpty ? options.first : null);
    return Expanded(
      child: InputDecorator(
        decoration: InputDecoration(
            labelText: label,
            isDense: true,
            border: const OutlineInputBorder()),
        child: DropdownButtonHideUnderline(
          child: DropdownButton<String>(
            value: safe,
            isExpanded: true,
            items: options
                .map((o) => DropdownMenuItem(
                    value: o, child: Text(labels?[o] ?? o)))
                .toList(),
            onChanged: (s) {
              if (s != null) onChanged(s);
            },
          ),
        ),
      ),
    );
  }

  Widget _partDrop(String label, String value, ValueChanged<String> onChanged) =>
      _dropdown(label, value, kPartOptions, onChanged);

  Widget _switch(String label, bool value, ValueChanged<bool> onChanged) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Switch(value: value, activeColor: C.text, onChanged: onChanged),
        Text(label),
      ],
    );
  }
}

// =============================================================================
// DISTRIBUTION  (per-gallery counts + reassign cars between galleries)
// =============================================================================

class DistributionPage extends StatefulWidget {
  final void Function(String locationId)? onOpen;
  const DistributionPage({super.key, this.onOpen});

  @override
  State<DistributionPage> createState() => _DistributionPageState();
}

class _DistributionPageState extends State<DistributionPage> {
  String _q = '';

  // All assignment targets: the galleries plus a "warehouse" (unassigned).
  List<MapEntry<String, String>> get _targets => [
        const MapEntry('', 'Warehouse (unassigned)'),
        ...store.locations.map((l) => MapEntry(l.id, l.name)),
      ];

  int _warehouseCount() {
    final ids = store.locations.map((l) => l.id).toSet();
    return store.vehicles.where((v) => !ids.contains(v.locationId)).length;
  }

  Future<void> _move(Vehicle v, String locationId) async {
    try {
      await store.moveVehicle(v, locationId);
      if (!mounted) return;
      final name = locationId.isEmpty
          ? 'Warehouse'
          : store.locationName(locationId);
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('${v.fullName} → $name')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Move failed: $e'), backgroundColor: C.red));
    }
  }

  void _toast(String msg, {bool error = false}) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(msg), backgroundColor: error ? C.red : null));
  }

  Future<void> _openForm({Vehicle? existing}) async {
    final result = await showDialog<Vehicle>(
      context: context,
      builder: (_) => VehicleFormDialog(existing: existing),
    );
    if (result == null) return;
    try {
      await store.saveVehicle(result, isNew: existing == null);
      _toast(existing == null ? 'Vehicle added' : 'Vehicle updated');
    } catch (e) {
      _toast('Save failed: $e', error: true);
    }
  }

  Future<void> _confirmDelete(Vehicle v) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Delete vehicle?'),
        content: Text('${v.fullName} will be permanently removed.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: C.red),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await store.deleteVehicle(v.id);
      _toast('Vehicle deleted');
    } catch (e) {
      _toast('Delete failed: $e', error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: store,
      builder: (context, _) {
        final cars = store.vehicles
            .where((v) =>
                _q.isEmpty ||
                v.fullName.toLowerCase().contains(_q.toLowerCase()))
            .toList()
          ..sort((a, b) => a.fullName.compareTo(b.fullName));

        return SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                spacing: 16,
                runSpacing: 16,
                children: [
                  ...store.locations.map((l) {
                    final count = store.countAt(l.id);
                    final frac = (count / kLocationCapacity).clamp(0.0, 1.0);
                    final color = frac >= 1.0
                        ? C.red
                        : (frac >= 0.8 ? C.gold : C.green);
                    return _CapacityCard(
                        title: l.name,
                        count: count,
                        capacity: kLocationCapacity,
                        frac: frac,
                        color: color,
                        onTap: () => widget.onOpen?.call(l.id));
                  }),
                  _CapacityCard(
                      title: 'Warehouse (unassigned)',
                      count: _warehouseCount(),
                      capacity: null,
                      frac: 0,
                      color: C.muted,
                      onTap: () => widget.onOpen?.call('')),
                ],
              ),
              const SizedBox(height: 24),
              const Text('Reassign vehicles',
                  style: TextStyle(fontSize: 15, fontWeight: FontWeight.w900)),
              const SizedBox(height: 4),
              const Text(
                  'Change a car\'s gallery from the dropdown — it saves immediately.',
                  style: TextStyle(color: C.muted, fontSize: 13)),
              const SizedBox(height: 12),
              Row(
                children: [
                  SizedBox(
                    width: 320,
                    child: TextField(
                      decoration: const InputDecoration(
                        isDense: true,
                        prefixIcon: Icon(Icons.search, size: 20),
                        hintText: 'Search a car to manage',
                        border: OutlineInputBorder(),
                      ),
                      onChanged: (s) => setState(() => _q = s),
                    ),
                  ),
                  const Spacer(),
                  FilledButton.icon(
                    style: FilledButton.styleFrom(backgroundColor: C.text),
                    onPressed: () => _openForm(),
                    icon: const Icon(Icons.add),
                    label: const Text('Add vehicle'),
                  ),
                ],
              ),
              const SizedBox(height: 14),
              Container(
                decoration: BoxDecoration(
                    color: C.card,
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(color: C.border)),
                child: Column(
                  children: cars.map((v) {
                    final ids = store.locations.map((l) => l.id).toSet();
                    final current = ids.contains(v.locationId) ? v.locationId : '';
                    return Padding(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 16, vertical: 8),
                      child: Row(
                        children: [
                          Expanded(
                            child: Row(
                              children: [
                                Flexible(
                                  child: Text(v.fullName,
                                      overflow: TextOverflow.ellipsis,
                                      style: const TextStyle(
                                          fontWeight: FontWeight.w600)),
                                ),
                                if (v.plate.isNotEmpty) ...[
                                  const SizedBox(width: 8),
                                  Container(
                                    padding: const EdgeInsets.symmetric(
                                        horizontal: 6, vertical: 2),
                                    decoration: BoxDecoration(
                                      color: Colors.white,
                                      border: Border.all(color: C.border),
                                      borderRadius: BorderRadius.circular(4),
                                    ),
                                    child: Text(v.plate,
                                        style: const TextStyle(
                                            fontSize: 11,
                                            fontWeight: FontWeight.w700)),
                                  ),
                                ],
                              ],
                            ),
                          ),
                          SizedBox(
                            width: 200,
                            child: DropdownButtonFormField<String>(
                              value: current,
                              isExpanded: true,
                              decoration: const InputDecoration(
                                  isDense: true,
                                  border: OutlineInputBorder()),
                              items: _targets
                                  .map((t) => DropdownMenuItem(
                                      value: t.key, child: Text(t.value)))
                                  .toList(),
                              onChanged: (loc) {
                                if (loc != null && loc != current) {
                                  _move(v, loc);
                                }
                              },
                            ),
                          ),
                          IconButton(
                              tooltip: 'Edit',
                              icon: const Icon(Icons.edit_outlined, size: 19),
                              onPressed: () => _openForm(existing: v)),
                          IconButton(
                              tooltip: 'Delete',
                              icon: const Icon(Icons.delete_outline,
                                  size: 19, color: C.red),
                              onPressed: () => _confirmDelete(v)),
                        ],
                      ),
                    );
                  }).toList(),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _CapacityCard extends StatelessWidget {
  final String title;
  final int count;
  final int? capacity;
  final double frac;
  final Color color;
  final VoidCallback? onTap;
  const _CapacityCard(
      {required this.title,
      required this.count,
      required this.capacity,
      required this.frac,
      required this.color,
      this.onTap});

  @override
  Widget build(BuildContext context) {
    final card = Container(
      width: 240,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
          color: C.card,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: C.border)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w900)),
              ),
              if (onTap != null)
                const Icon(Icons.chevron_right, color: C.muted, size: 18),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Text('$count',
                  style: const TextStyle(
                      fontSize: 26, fontWeight: FontWeight.w900)),
              if (capacity != null)
                Text(' / $capacity',
                    style: const TextStyle(color: C.muted, fontSize: 14)),
            ],
          ),
          const SizedBox(height: 10),
          if (capacity != null)
            ClipRRect(
              borderRadius: BorderRadius.circular(6),
              child: LinearProgressIndicator(
                value: frac,
                minHeight: 8,
                backgroundColor: C.bg,
                color: color,
              ),
            )
          else
            const Text('cars not at a gallery',
                style: TextStyle(color: C.muted, fontSize: 12)),
        ],
      ),
    );
    if (onTap == null) return card;
    return Material(
      color: Colors.transparent,
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
          onTap: onTap, borderRadius: BorderRadius.circular(14), child: card),
    );
  }
}

// =============================================================================
// CAR DETAIL  (read-only preview with photos)
// =============================================================================

class VehicleDetailDialog extends StatelessWidget {
  final Vehicle v;
  const VehicleDetailDialog({super.key, required this.v});

  @override
  Widget build(BuildContext context) {
    return Dialog(
      child: Container(
        width: 640,
        constraints: const BoxConstraints(maxHeight: 680),
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(v.fullName,
                      style: const TextStyle(
                          fontSize: 20, fontWeight: FontWeight.w900)),
                ),
                IconButton(
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.close)),
              ],
            ),
            Text(money(v.price),
                style: const TextStyle(
                    fontSize: 18, fontWeight: FontWeight.w900, color: C.blue)),
            const SizedBox(height: 14),
            Expanded(
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (v.images.isNotEmpty)
                      SizedBox(
                        height: 220,
                        child: ListView.separated(
                          scrollDirection: Axis.horizontal,
                          itemCount: v.images.length,
                          separatorBuilder: (_, __) =>
                              const SizedBox(width: 10),
                          itemBuilder: (context, i) => ClipRRect(
                            borderRadius: BorderRadius.circular(12),
                            child: Image.network(
                              v.images[i],
                              width: 320,
                              fit: BoxFit.cover,
                              errorBuilder: (_, __, ___) => Container(
                                width: 320,
                                color: C.bg,
                                child: const Icon(Icons.directions_car,
                                    size: 48, color: C.muted),
                              ),
                            ),
                          ),
                        ),
                      )
                    else
                      Container(
                        height: 160,
                        width: double.infinity,
                        decoration: BoxDecoration(
                            color: C.bg,
                            borderRadius: BorderRadius.circular(12)),
                        child: const Icon(Icons.image_not_supported,
                            size: 48, color: C.muted),
                      ),
                    const SizedBox(height: 18),
                    Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      children: [
                        _spec('Year', '${v.year}'),
                        _spec('Mileage', '${thousands(v.mileage)} km'),
                        _spec('Fuel', v.fuelType),
                        _spec('Transmission', v.transmission),
                        _spec('Body', v.bodyType),
                        _spec('Power', '${v.specs.powerHp} HP'),
                        _spec('Top speed', '${v.specs.topSpeed} km/h'),
                        _spec('0-100', '${v.specs.zeroToHundred} s'),
                        _spec('Drivetrain', v.specs.drivetrain),
                        _spec('Color', v.specs.color),
                        _spec('Location', store.locationName(v.locationId)),
                        _spec('Condition',
                            v.inspection.hasDamage ? 'Damaged / painted' : 'Clean'),
                      ],
                    ),
                    if (v.description.isNotEmpty) ...[
                      const SizedBox(height: 16),
                      const Text('Description',
                          style: TextStyle(
                              color: C.muted,
                              fontSize: 12,
                              fontWeight: FontWeight.w800,
                              letterSpacing: 1)),
                      const SizedBox(height: 4),
                      Text(v.description,
                          style: const TextStyle(height: 1.5)),
                    ],
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _spec(String label, String value) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
          color: C.bg, borderRadius: BorderRadius.circular(10)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label,
              style: const TextStyle(color: C.muted, fontSize: 11)),
          const SizedBox(height: 2),
          Text(value,
              style: const TextStyle(fontWeight: FontWeight.w800)),
        ],
      ),
    );
  }
}

// =============================================================================
// DEMAND SIDE — ORDERS & BOOKINGS (admin approval)
// =============================================================================

Color statusColor(String s) {
  switch (s) {
    case 'PENDING':
    case 'REQUESTED':
      return C.gold;
    case 'CONFIRMED':
    case 'READY':
      return C.blue;
    case 'COMPLETED':
    case 'DONE':
      return C.green;
    case 'CANCELLED':
      return C.red;
    default:
      return C.muted;
  }
}

String fmtDateTime(int ms) {
  if (ms <= 0) return '—';
  final d = DateTime.fromMillisecondsSinceEpoch(ms);
  String two(int n) => n.toString().padLeft(2, '0');
  return '${d.year}-${two(d.month)}-${two(d.day)} ${two(d.hour)}:${two(d.minute)}';
}

class OrdersPage extends StatefulWidget {
  const OrdersPage({super.key});
  @override
  State<OrdersPage> createState() => _OrdersPageState();
}

class _OrdersPageState extends State<OrdersPage> {
  bool _pendingOnly = false;

  void _toast(String m, [bool err = false]) {
    ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(m), backgroundColor: err ? C.red : C.text));
  }

  Future<void> _setStatus(AdminOrder o, String s) async {
    final prev = o.status;
    setState(() => o.status = s);
    try {
      await store.updateOrder(o);
    } catch (e) {
      setState(() => o.status = prev);
      _toast('Update failed: $e', true);
    }
  }

  // Approve a reservation: confirm it and, if the customer chose a pickup
  // gallery different from where the car sits, move it there.
  Future<void> _approve(AdminOrder o) async {
    final prev = o.status;
    setState(() => o.status = 'CONFIRMED');
    try {
      await store.updateOrder(o);
      if (o.targetLocationId.isNotEmpty) {
        for (final v in store.vehicles) {
          if (v.id == o.vehicleId) {
            if (v.locationId != o.targetLocationId) {
              await store.moveVehicle(v, o.targetLocationId);
            }
            break;
          }
        }
      }
    } catch (e) {
      setState(() => o.status = prev);
      _toast('Approve failed: $e', true);
    }
  }

  Future<void> _delete(AdminOrder o) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Delete order?'),
        content: const Text('This permanently removes the order.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel')),
          FilledButton(
              style: FilledButton.styleFrom(backgroundColor: C.red),
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Delete')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await store.deleteOrder(o.id);
    } catch (e) {
      _toast('Delete failed: $e', true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: store,
      builder: (context, _) {
        var list = store.orders.where((o) => o.type != 'PREORDER').toList();
        if (_pendingOnly) {
          list = list.where((o) => o.status == 'PENDING').toList();
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 20, 24, 8),
              child: Row(
                children: [
                  Text('${store.orders.where((o) => o.type != "PREORDER").length} orders · ${store.orders.where((o) => o.type != "PREORDER" && o.status == "PENDING").length} pending',
                      style: const TextStyle(color: C.muted, fontSize: 13)),
                  const Spacer(),
                  FilterChip(
                    label: const Text('Pending only'),
                    selected: _pendingOnly,
                    onSelected: (s) => setState(() => _pendingOnly = s),
                  ),
                ],
              ),
            ),
            Expanded(
              child: list.isEmpty
                  ? const Center(
                      child: Text('No orders yet',
                          style: TextStyle(color: C.muted)))
                  : ListView(
                      padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
                      children: list.map(_orderCard).toList(),
                    ),
            ),
          ],
        );
      },
    );
  }

  Widget _orderCard(AdminOrder o) {
    final isPending = o.status == 'PENDING';
    final isReserve = o.type == 'RESERVE';
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: C.card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
            color: isPending ? C.gold : C.border, width: isPending ? 1.5 : 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(store.vehicleName(o.vehicleId),
                    style: const TextStyle(
                        fontWeight: FontWeight.w900, fontSize: 15)),
              ),
              _Pill(
                  text: isReserve ? 'Reserve' : 'Pre-order',
                  color: isReserve ? C.blue : C.gold),
              const SizedBox(width: 8),
              _Pill(text: o.status, color: statusColor(o.status)),
            ],
          ),
          if (o.targetLocationId.isNotEmpty) ...[
            const SizedBox(height: 6),
            Row(
              children: [
                const Icon(Icons.place_outlined, size: 15, color: C.muted),
                const SizedBox(width: 4),
                Text('Pickup at: ${store.locationName(o.targetLocationId)}',
                    style: const TextStyle(
                        fontSize: 13, fontWeight: FontWeight.w600)),
              ],
            ),
          ],
          const SizedBox(height: 8),
          Text('${o.customerName}  ·  ${o.phone}${o.email.isEmpty ? '' : '  ·  ${o.email}'}',
              style: const TextStyle(fontSize: 13)),
          Text('Submitted ${fmtDateTime(o.createdAt)}',
              style: const TextStyle(color: C.muted, fontSize: 12)),
          if (o.note.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text('Note: ${o.note}',
                style: const TextStyle(color: C.muted, fontSize: 13)),
          ],
          const SizedBox(height: 12),
          Row(
            children: [
              const Text('Status:',
                  style: TextStyle(color: C.muted, fontSize: 13)),
              const SizedBox(width: 8),
              DropdownButton<String>(
                value: kOrderStatuses.contains(o.status) ? o.status : null,
                items: kOrderStatuses
                    .map((s) => DropdownMenuItem(value: s, child: Text(s)))
                    .toList(),
                onChanged: (s) {
                  if (s != null) _setStatus(o, s);
                },
              ),
              const Spacer(),
              if (isPending)
                FilledButton.icon(
                  style: FilledButton.styleFrom(backgroundColor: C.green),
                  onPressed: () => _approve(o),
                  icon: const Icon(Icons.check, size: 18),
                  label: const Text('Approve'),
                ),
              IconButton(
                  tooltip: 'Delete',
                  icon: const Icon(Icons.delete_outline, color: C.red),
                  onPressed: () => _delete(o)),
            ],
          ),
        ],
      ),
    );
  }
}

class PreOrdersPage extends StatefulWidget {
  const PreOrdersPage({super.key});
  @override
  State<PreOrdersPage> createState() => _PreOrdersPageState();
}

class _PreOrdersPageState extends State<PreOrdersPage> {
  bool _pendingOnly = false;

  void _toast(String m, [bool err = false]) {
    ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(m), backgroundColor: err ? C.red : C.text));
  }

  Vehicle? _carOf(AdminOrder o) {
    for (final v in store.vehicles) {
      if (v.id == o.vehicleId) return v;
    }
    return null;
  }

  // Accept: confirm the order and transfer the car to the gallery the
  // customer chose, so it leaves the warehouse and lands on that lot.
  Future<void> _accept(AdminOrder o) async {
    final prev = o.status;
    setState(() => o.status = 'CONFIRMED');
    try {
      await store.updateOrder(o);
      final car = _carOf(o);
      if (car != null && o.targetLocationId.isNotEmpty) {
        await store.moveVehicle(car, o.targetLocationId);
      }
      _toast('Pre-order accepted — car transferred');
    } catch (e) {
      setState(() => o.status = prev);
      _toast('Accept failed: $e', true);
    }
  }

  Future<void> _cancel(AdminOrder o) async {
    final prev = o.status;
    setState(() => o.status = 'CANCELLED');
    try {
      await store.updateOrder(o);
      _toast('Pre-order cancelled');
    } catch (e) {
      setState(() => o.status = prev);
      _toast('Cancel failed: $e', true);
    }
  }

  Future<void> _delete(AdminOrder o) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Delete pre-order?'),
        content: const Text('This permanently removes the pre-order.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel')),
          FilledButton(
              style: FilledButton.styleFrom(backgroundColor: C.red),
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Delete')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await store.deleteOrder(o.id);
    } catch (e) {
      _toast('Delete failed: $e', true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: store,
      builder: (context, _) {
        var list =
            store.orders.where((o) => o.type == 'PREORDER').toList();
        final pending = list.where((o) => o.status == 'PENDING').length;
        if (_pendingOnly) {
          list = list.where((o) => o.status == 'PENDING').toList();
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 20, 24, 8),
              child: Row(
                children: [
                  Text('${list.length} pre-orders · $pending pending',
                      style: const TextStyle(color: C.muted, fontSize: 13)),
                  const Spacer(),
                  FilterChip(
                    label: const Text('Pending only'),
                    selected: _pendingOnly,
                    onSelected: (s) => setState(() => _pendingOnly = s),
                  ),
                ],
              ),
            ),
            Expanded(
              child: list.isEmpty
                  ? const Center(
                      child: Text('No pre-orders yet',
                          style: TextStyle(color: C.muted)))
                  : ListView(
                      padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
                      children: list.map(_card).toList(),
                    ),
            ),
          ],
        );
      },
    );
  }

  Widget _card(AdminOrder o) {
    final isPending = o.status == 'PENDING';
    final target = o.targetLocationId.isEmpty
        ? 'No gallery chosen'
        : store.locationName(o.targetLocationId);
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: C.card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
            color: isPending ? C.gold : C.border, width: isPending ? 1.5 : 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(store.vehicleName(o.vehicleId),
                    style: const TextStyle(
                        fontWeight: FontWeight.w900, fontSize: 15)),
              ),
              _Pill(text: 'Pre-order', color: C.gold),
              const SizedBox(width: 8),
              _Pill(text: o.status, color: statusColor(o.status)),
            ],
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              const Icon(Icons.place_outlined, size: 15, color: C.muted),
              const SizedBox(width: 4),
              Text('Deliver to: $target',
                  style: const TextStyle(
                      fontSize: 13, fontWeight: FontWeight.w600)),
            ],
          ),
          const SizedBox(height: 6),
          Text('${o.customerName}  ·  ${o.phone}${o.email.isEmpty ? '' : '  ·  ${o.email}'}',
              style: const TextStyle(fontSize: 13)),
          Text('Submitted ${fmtDateTime(o.createdAt)}',
              style: const TextStyle(color: C.muted, fontSize: 12)),
          if (o.note.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text('Note: ${o.note}',
                style: const TextStyle(color: C.muted, fontSize: 13)),
          ],
          const SizedBox(height: 12),
          Row(
            children: [
              _Pill(text: o.status, color: statusColor(o.status)),
              const Spacer(),
              if (isPending) ...[
                FilledButton.icon(
                  style: FilledButton.styleFrom(backgroundColor: C.green),
                  onPressed: () => _accept(o),
                  icon: const Icon(Icons.check, size: 18),
                  label: const Text('Accept'),
                ),
                const SizedBox(width: 8),
                OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(foregroundColor: C.red),
                  onPressed: () => _cancel(o),
                  icon: const Icon(Icons.close, size: 18),
                  label: const Text('Cancel'),
                ),
              ],
              IconButton(
                  tooltip: 'Delete',
                  icon: const Icon(Icons.delete_outline, color: C.red),
                  onPressed: () => _delete(o)),
            ],
          ),
        ],
      ),
    );
  }
}
