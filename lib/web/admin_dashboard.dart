// =============================================================================
// admin_dashboard.dart   —   Admin web console (separate entry point)
//
// Run it like the supervisor dashboard but pointed at this file:
//     flutter run -d chrome -t lib/web/admin_dashboard.dart
//
// What it does:
//   * Generate tab (landing): set a schedule window + roll date, then GENERATE
//     for ALL supervisors at once (8 maintenance HQs + callbacks) via
//     POST /api/admin/generate/, with live progress.
//   * Observe tab: pick any supervisor and see their technicians (with today's
//     status off the roll-date clock) and the units they cover. No map — the
//     live route map stays on the supervisor side.
//
// Auth: logs in with the SAME /api/login/ token flow, but the account must be
// staff/superuser (create once: `python manage.py createsuperuser`). The admin
// endpoints reject non-staff tokens, and this app uses that to gate entry.
//
// Dependencies (already in the supervisor app): http, (flutter material).
// =============================================================================
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

const String kBaseUrl = 'http://localhost:8000';
String kAdminToken = '';
String kAdminName = 'Admin';

void main() => runApp(const AdminApp());

String _ymd(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-'
    '${d.month.toString().padLeft(2, '0')}-'
    '${d.day.toString().padLeft(2, '0')}';

// ----------------------------------------------------------------- theme
class AdminColors {
  static const bg = Color(0xFF0E1117);
  static const card = Color(0xFF171B22);
  static const cardHi = Color(0xFF202733);
  static const accent = Color(0xFF4F7CFF);
  static const good = Color(0xFF23C47E);
  static const warn = Color(0xFFF59E0B);
  static const bad = Color(0xFFEF4444);
  static const muted = Color(0xFF8A94A6);
}

class AdminApp extends StatelessWidget {
  const AdminApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Admin Console',
      theme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        scaffoldBackgroundColor: AdminColors.bg,
        colorScheme: const ColorScheme.dark(
          primary: AdminColors.accent,
          surface: AdminColors.card,
        ),
      ),
      home: const AdminLoginScreen(),
    );
  }
}

// ----------------------------------------------------------------- API
class AdminApi {
  static Map<String, String> get _h => {
        'Content-Type': 'application/json',
        if (kAdminToken.isNotEmpty) 'Authorization': 'Token $kAdminToken',
      };

  static Future<http.Response> login(String u, String p) => http.post(
        Uri.parse('$kBaseUrl/api/login/'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'username': u, 'password': p}),
      );

  static Future<http.Response> hqs() =>
      http.get(Uri.parse('$kBaseUrl/api/admin/hqs/'), headers: _h);

  static Future<http.Response> hqState(int gid) => http.get(
      Uri.parse('$kBaseUrl/api/admin/hq-state/?group_id=$gid'), headers: _h);

  static Future<http.Response> generate(String start, String end, bool init) =>
      http.post(Uri.parse('$kBaseUrl/api/admin/generate/'),
          headers: _h,
          body: jsonEncode({'start': start, 'end': end, 'init': init}));

  static Future<http.Response> generateStatus() =>
      http.get(Uri.parse('$kBaseUrl/api/admin/generate/'), headers: _h);

  static Future<http.Response> cancelGenerate() =>
      http.delete(Uri.parse('$kBaseUrl/api/admin/generate/'), headers: _h);

  // Roll the global operating clock to a date + time (existing clock endpoint).
  static Future<http.Response> setRollClock(String isoDate, String hhmm) =>
      http.post(Uri.parse('$kBaseUrl/api/clock/set/'),
          headers: _h, body: jsonEncode({'date': isoDate, 'time': hhmm}));
}

// ----------------------------------------------------------------- login
class AdminLoginScreen extends StatefulWidget {
  const AdminLoginScreen({super.key});
  @override
  State<AdminLoginScreen> createState() => _AdminLoginScreenState();
}

class _AdminLoginScreenState extends State<AdminLoginScreen> {
  final _user = TextEditingController();
  final _pass = TextEditingController();
  bool _loading = false;
  String? _error;

  Future<void> _login() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final r = await AdminApi.login(_user.text.trim(), _pass.text.trim());
      if (r.statusCode != 200) {
        throw Exception('Invalid username or password.');
      }
      final j = jsonDecode(r.body) as Map<String, dynamic>;
      kAdminToken = (j['token'] ?? '').toString();
      if (kAdminToken.isEmpty) throw Exception('No token returned.');

      // gate: must be an admin (staff/superuser) -> /api/admin/hqs/ must accept
      final check = await AdminApi.hqs();
      if (check.statusCode == 403 || check.statusCode == 401) {
        kAdminToken = '';
        throw Exception('This account is not an admin.');
      }
      if (check.statusCode != 200) {
        throw Exception('Admin check failed (${check.statusCode}).');
      }
      kAdminName = _user.text.trim();
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
          MaterialPageRoute(builder: (_) => const AdminHomeScreen()));
    } catch (e) {
      setState(() => _error = e.toString().replaceAll('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 400),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Icon(Icons.shield_moon_outlined,
                    size: 64, color: AdminColors.accent),
                const SizedBox(height: 16),
                const Text('Admin Console',
                    textAlign: TextAlign.center,
                    style:
                        TextStyle(fontSize: 28, fontWeight: FontWeight.w800)),
                const SizedBox(height: 6),
                const Text('Generate all schedules · observe every HQ',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: AdminColors.muted)),
                const SizedBox(height: 32),
                TextField(
                  controller: _user,
                  decoration: const InputDecoration(
                      labelText: 'Admin username',
                      prefixIcon: Icon(Icons.person_outline),
                      border: OutlineInputBorder()),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _pass,
                  obscureText: true,
                  onSubmitted: (_) => _login(),
                  decoration: const InputDecoration(
                      labelText: 'Password',
                      prefixIcon: Icon(Icons.lock_outline),
                      border: OutlineInputBorder()),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!,
                      style: const TextStyle(color: AdminColors.bad)),
                ],
                const SizedBox(height: 20),
                FilledButton(
                  onPressed: _loading ? null : _login,
                  style: FilledButton.styleFrom(
                      backgroundColor: AdminColors.accent,
                      padding: const EdgeInsets.symmetric(vertical: 16)),
                  child: _loading
                      ? const SizedBox(
                          height: 20,
                          width: 20,
                          child: CircularProgressIndicator(strokeWidth: 2))
                      : const Text('Sign in'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// ----------------------------------------------------------------- home
class AdminHomeScreen extends StatefulWidget {
  const AdminHomeScreen({super.key});
  @override
  State<AdminHomeScreen> createState() => _AdminHomeScreenState();
}

class _AdminHomeScreenState extends State<AdminHomeScreen> {
  int _idx = 0;

  @override
  Widget build(BuildContext context) {
    final pages = const [GenerateTab(), ObserveTab()];
    return Scaffold(
      appBar: AppBar(
        backgroundColor: AdminColors.bg,
        title: const Text('Admin Console',
            style: TextStyle(fontWeight: FontWeight.w800)),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: Center(
                child: Text(kAdminName,
                    style: const TextStyle(color: AdminColors.muted))),
          ),
        ],
      ),
      body: pages[_idx],
      bottomNavigationBar: NavigationBar(
        backgroundColor: AdminColors.card,
        selectedIndex: _idx,
        onDestinationSelected: (i) => setState(() => _idx = i),
        destinations: const [
          NavigationDestination(
              icon: Icon(Icons.play_circle_outline),
              selectedIcon: Icon(Icons.play_circle),
              label: 'Generate'),
          NavigationDestination(
              icon: Icon(Icons.visibility_outlined),
              selectedIcon: Icon(Icons.visibility),
              label: 'Observe'),
        ],
      ),
    );
  }
}

// ----------------------------------------------------------------- generate
class GenerateTab extends StatefulWidget {
  const GenerateTab({super.key});
  @override
  State<GenerateTab> createState() => _GenerateTabState();
}

class _GenerateTabState extends State<GenerateTab> {
  DateTime _start = DateTime.now();
  DateTime _end = DateTime.now().add(const Duration(days: 30));
  DateTime _roll = DateTime.now();
  TimeOfDay _rollTime = const TimeOfDay(hour: 8, minute: 0);
  bool _init = true;

  Map<String, dynamic>? _status;
  Timer? _poll;
  bool _busy = false;
  String? _rollMsg;

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _pick(DateTime initial, ValueChanged<DateTime> onPicked) async {
    final d = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: DateTime(2025, 1, 1),
      lastDate: DateTime(2027, 12, 31),
    );
    if (d != null) onPicked(d);
  }

  Future<void> _generate() async {
    setState(() => _busy = true);
    try {
      final r = await AdminApi.generate(_ymd(_start), _ymd(_end), _init);
      if (r.statusCode != 202 && r.statusCode != 200) {
        _snack('Generate failed (${r.statusCode}): ${r.body}');
        setState(() => _busy = false);
        return;
      }
      _startPolling();
    } catch (e) {
      _snack('Error: $e');
      setState(() => _busy = false);
    }
  }

  void _startPolling() {
    _poll?.cancel();
    _poll = Timer.periodic(const Duration(seconds: 2), (_) async {
      try {
        final r = await AdminApi.generateStatus();
        if (r.statusCode == 200) {
          final j = jsonDecode(r.body) as Map<String, dynamic>;
          setState(() => _status = j);
          final st = j['state'];
          if (st == 'DONE' || st == 'FAILED' || st == 'idle') {
            _poll?.cancel();
            setState(() => _busy = false);
          }
        }
      } catch (_) {}
    });
  }

  Future<void> _cancel() async {
    await AdminApi.cancelGenerate();
    _poll?.cancel();
    setState(() {
      _busy = false;
      _status = null;
    });
  }

  String get _hhmm =>
      '${_rollTime.hour.toString().padLeft(2, '0')}:'
      '${_rollTime.minute.toString().padLeft(2, '0')}';

  Future<void> _pickTime() async {
    final t = await showTimePicker(context: context, initialTime: _rollTime);
    if (t != null) setState(() => _rollTime = t);
  }

  Future<void> _setRoll() async {
    try {
      final r = await AdminApi.setRollClock(_ymd(_roll), _hhmm);
      setState(() => _rollMsg = (r.statusCode >= 200 && r.statusCode < 300)
          ? 'Operating clock set to ${_ymd(_roll)} $_hhmm.'
          : 'Set failed (${r.statusCode}): ${r.body}');
    } catch (e) {
      setState(() => _rollMsg = 'Error: $e');
    }
  }

  void _snack(String m) => ScaffoldMessenger.of(context)
      .showSnackBar(SnackBar(content: Text(m)));

  @override
  Widget build(BuildContext context) {
    final st = _status;
    final running = st != null && st['state'] == 'RUNNING';
    final done = st != null && st['state'] == 'DONE';
    final failed = st != null && st['state'] == 'FAILED';
    final prog = (st?['progress'] as num?)?.toDouble();
    final logTail = (st?['log_tail'] as List?)?.cast<String>() ?? const [];

    return ListView(
      padding: const EdgeInsets.all(18),
      children: [
        // ---- schedule window ----
        _Section(
          title: 'Generate full schedule',
          subtitle:
              'Runs all 8 maintenance HQs + callbacks in one job, for every supervisor.',
          child: Column(
            children: [
              _DateRow(
                  label: 'Start',
                  value: _ymd(_start),
                  onTap: () => _pick(_start, (d) => setState(() => _start = d))),
              _DateRow(
                  label: 'End',
                  value: _ymd(_end),
                  onTap: () => _pick(_end, (d) => setState(() => _end = d))),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Clean slate (--init)'),
                subtitle: const Text(
                    'Clear old schedules/tasks/leave and re-seed clocks first',
                    style: TextStyle(color: AdminColors.muted, fontSize: 12)),
                value: _init,
                activeColor: AdminColors.accent,
                onChanged: running ? null : (v) => setState(() => _init = v),
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: FilledButton.icon(
                      onPressed: (_busy || running) ? null : _generate,
                      style: FilledButton.styleFrom(
                          backgroundColor: AdminColors.accent,
                          padding: const EdgeInsets.symmetric(vertical: 14)),
                      icon: const Icon(Icons.play_arrow),
                      label: Text(running ? 'Generating…' : 'Generate for all'),
                    ),
                  ),
                  if (running) ...[
                    const SizedBox(width: 10),
                    OutlinedButton(
                        onPressed: _cancel, child: const Text('Cancel')),
                  ],
                ],
              ),
            ],
          ),
        ),

        // ---- progress ----
        if (st != null)
          _Section(
            title: 'Progress',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(
                        done
                            ? Icons.check_circle
                            : failed
                                ? Icons.error
                                : Icons.autorenew,
                        color: done
                            ? AdminColors.good
                            : failed
                                ? AdminColors.bad
                                : AdminColors.accent,
                        size: 18),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        failed
                            ? (st['error']?.toString() ?? 'Failed')
                            : '${st['state']} · ${st['current_group'] ?? ''}'
                                '${st['groups_total'] != null ? '  (${st['groups_done'] ?? 0}/${st['groups_total']})' : ''}',
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                LinearProgressIndicator(
                  value: prog,
                  backgroundColor: AdminColors.cardHi,
                  color: done ? AdminColors.good : AdminColors.accent,
                  minHeight: 6,
                ),
                if (logTail.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                        color: Colors.black,
                        borderRadius: BorderRadius.circular(8)),
                    child: Text(
                      logTail.join('\n'),
                      style: const TextStyle(
                          fontFamily: 'monospace',
                          fontSize: 11,
                          color: AdminColors.muted),
                    ),
                  ),
                ],
              ],
            ),
          ),

        // ---- roll date ----
        _Section(
          title: 'Roll date',
          subtitle:
              'The operating date every supervisor sees (the “now” of the simulation).',
          child: Column(
            children: [
              _DateRow(
                  label: 'Roll to',
                  value: _ymd(_roll),
                  onTap: () => _pick(_roll, (d) => setState(() => _roll = d))),
              _DateRow(
                  label: 'Time',
                  value: _hhmm,
                  icon: Icons.access_time,
                  onTap: _pickTime),
              const SizedBox(height: 8),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: _setRoll,
                  icon: const Icon(Icons.event),
                  label: const Text('Set roll date & time'),
                ),
              ),
              if (_rollMsg != null) ...[
                const SizedBox(height: 8),
                Text(_rollMsg!,
                    style: const TextStyle(
                        color: AdminColors.muted, fontSize: 12)),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

// ----------------------------------------------------------------- observe
class ObserveTab extends StatefulWidget {
  const ObserveTab({super.key});
  @override
  State<ObserveTab> createState() => _ObserveTabState();
}

class _ObserveTabState extends State<ObserveTab> {
  List<dynamic> _hqs = [];
  int? _selected;
  Map<String, dynamic>? _state;
  String? _activeRoll;
  bool _loadingHqs = true;
  bool _loadingState = false;

  @override
  void initState() {
    super.initState();
    _loadHqs();
  }

  Future<void> _loadHqs() async {
    setState(() => _loadingHqs = true);
    try {
      final r = await AdminApi.hqs();
      if (r.statusCode == 200) {
        final j = jsonDecode(r.body) as Map<String, dynamic>;
        final at = j['active_time']?.toString();
        setState(() {
          _hqs = (j['hqs'] as List?) ?? [];
          _activeRoll = (at != null && at.length >= 16)
              ? at.substring(0, 16).replaceAll('T', ' ')
              : j['active_date']?.toString();
        });
      }
    } catch (_) {}
    if (mounted) setState(() => _loadingHqs = false);
  }

  Future<void> _loadState(int gid) async {
    setState(() {
      _selected = gid;
      _loadingState = true;
      _state = null;
    });
    try {
      final r = await AdminApi.hqState(gid);
      if (r.statusCode == 200) {
        setState(() => _state = jsonDecode(r.body) as Map<String, dynamic>);
      }
    } catch (_) {}
    if (mounted) setState(() => _loadingState = false);
  }

  Color _statusColor(String s) {
    switch (s) {
      case 'working':
        return AdminColors.good;
      case 'onLeave':
        return AdminColors.warn;
      default:
        return AdminColors.muted;
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loadingHqs) {
      return const Center(child: CircularProgressIndicator());
    }
    return ListView(
      padding: const EdgeInsets.all(18),
      children: [
        Row(
          children: [
            const Text('Observe supervisor',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
            IconButton(
              tooltip: 'Refresh',
              icon: const Icon(Icons.refresh, size: 20),
              onPressed: () =>
                  _selected != null ? _loadState(_selected!) : _loadHqs(),
            ),
            const Spacer(),
            if (_activeRoll != null)
              Text('Roll: $_activeRoll',
                  style: const TextStyle(color: AdminColors.muted)),
          ],
        ),
        const SizedBox(height: 12),
        // supervisor picker
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: _hqs.map((h) {
            final gid = h['id'] as int;
            final sel = gid == _selected;
            return ChoiceChip(
              selected: sel,
              label: Text(h['name']?.toString() ?? '—'),
              selectedColor: AdminColors.accent,
              backgroundColor: AdminColors.cardHi,
              labelStyle: TextStyle(
                  color: sel ? Colors.white : AdminColors.muted,
                  fontWeight: FontWeight.w600),
              onSelected: (_) => _loadState(gid),
            );
          }).toList(),
        ),
        const SizedBox(height: 16),
        if (_selected == null)
          const Padding(
            padding: EdgeInsets.only(top: 60),
            child: Center(
                child: Text('Pick a supervisor to view their team.',
                    style: TextStyle(color: AdminColors.muted))),
          )
        else if (_loadingState)
          const Padding(
            padding: EdgeInsets.only(top: 60),
            child: Center(child: CircularProgressIndicator()),
          )
        else if (_state != null)
          ..._buildState(_state!),
      ],
    );
  }

  List<Widget> _buildState(Map<String, dynamic> s) {
    final techs = (s['technicians'] as List?) ?? [];
    final covered = (s['units_covered'] as Map?) ?? {};
    final type = s['group_type']?.toString() ?? '';

    return [
      // summary card
      Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
            color: AdminColors.card, borderRadius: BorderRadius.circular(14)),
        child: Row(
          children: [
            _stat('Technicians', '${s['tech_count'] ?? techs.length}'),
            _stat('Working today', '${s['working_today'] ?? 0}'),
            _stat('Units covered', '${covered['total'] ?? 0}'),
            _stat('Type', type),
          ],
        ),
      ),
      const SizedBox(height: 8),
      Text(
        'Units: ${covered['elevator'] ?? 0} elevator · ${covered['escalator'] ?? 0} escalator',
        style: const TextStyle(color: AdminColors.muted, fontSize: 12),
      ),
      const SizedBox(height: 16),
      const Text('Technicians',
          style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800)),
      const SizedBox(height: 8),
      ...techs.map((t) {
        final status = t['status']?.toString() ?? '';
        return Container(
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          decoration: BoxDecoration(
              color: AdminColors.card, borderRadius: BorderRadius.circular(12)),
          child: Row(
            children: [
              CircleAvatar(
                  radius: 5, backgroundColor: _statusColor(status)),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(t['name']?.toString() ?? '—',
                        style: const TextStyle(fontWeight: FontWeight.w600)),
                    Text(
                      '${t['tech_role'] ?? ''} · ${t['specialty'] ?? ''}',
                      style: const TextStyle(
                          color: AdminColors.muted, fontSize: 12),
                    ),
                  ],
                ),
              ),
              Text(
                t['on_leave'] == true
                    ? 'On leave'
                    : '${t['stops_today'] ?? 0} stops',
                style: TextStyle(
                    color: _statusColor(status),
                    fontWeight: FontWeight.w600,
                    fontSize: 12),
              ),
            ],
          ),
        );
      }),
    ];
  }

  Widget _stat(String label, String value) => Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(value,
                style: const TextStyle(
                    fontSize: 20, fontWeight: FontWeight.w800)),
            Text(label,
                style:
                    const TextStyle(color: AdminColors.muted, fontSize: 11)),
          ],
        ),
      );
}

// ----------------------------------------------------------------- shared bits
class _Section extends StatelessWidget {
  final String title;
  final String? subtitle;
  final Widget child;
  const _Section({required this.title, this.subtitle, required this.child});
  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
          color: AdminColors.card, borderRadius: BorderRadius.circular(14)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title,
              style:
                  const TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
          if (subtitle != null) ...[
            const SizedBox(height: 4),
            Text(subtitle!,
                style: const TextStyle(color: AdminColors.muted, fontSize: 12)),
          ],
          const SizedBox(height: 14),
          child,
        ],
      ),
    );
  }
}

class _DateRow extends StatelessWidget {
  final String label;
  final String value;
  final IconData icon;
  final VoidCallback onTap;
  const _DateRow(
      {required this.label,
      required this.value,
      required this.onTap,
      this.icon = Icons.calendar_today});
  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(10),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 10),
        child: Row(
          children: [
            SizedBox(
                width: 70,
                child: Text(label,
                    style: const TextStyle(color: AdminColors.muted))),
            Text(value,
                style: const TextStyle(
                    fontWeight: FontWeight.w700, fontSize: 16)),
            const Spacer(),
            Icon(icon, size: 16, color: AdminColors.muted),
          ],
        ),
      ),
    );
  }
}
