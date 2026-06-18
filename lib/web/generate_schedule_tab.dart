// generate_schedule_tab.dart
// =============================================================================
// "Generate Schedule" content for the supervisor flow.
//
// Self-contained (takes baseUrl + token as params). Used inside the post-login
// Generate Schedule gate (see generate_schedule_gate.dart).
//
//   1. Pick a date RANGE (any length) -> POST /api/simulation/run/ {start,end}
//      (Gurobi/v5 solve over that range)
//   2. Pick a date to roll from        -> POST /api/clock/set/ {date,time}
//      (sets the sim clock; Live Map + mobile follow)
// =============================================================================
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

class GenerateScheduleTab extends StatefulWidget {
  final String baseUrl;
  final String token;
  const GenerateScheduleTab({
    super.key,
    this.baseUrl = 'http://localhost:8000',
    this.token = '',
  });

  @override
  State<GenerateScheduleTab> createState() => _GenerateScheduleTabState();
}

class _GenerateScheduleTabState extends State<GenerateScheduleTab> {
  static final Color _accent = Colors.blue.shade800;

  // --- generate state ---
  DateTimeRange? _schedRange;
  bool _busy = false;
  Timer? _poll;
  String _state = 'idle'; // idle | RUNNING | DONE | FAILED
  double? _progress;
  String? _group, _start, _end, _latestDay, _error;
  int? _totalDays;
  List<String> _log = const [];

  // --- roll-from-date state ---
  DateTime? _rollDate;
  TimeOfDay _rollTime = const TimeOfDay(hour: 8, minute: 0);
  bool _settingClock = false;
  String? _clockMsg;
  bool _clockOk = false;

  Map<String, String> get _headers {
    final h = <String, String>{'Content-Type': 'application/json'};
    if (widget.token.isNotEmpty) h['Authorization'] = 'Token ${widget.token}';
    return h;
  }

  DateTime? get _rangeStart => _start != null ? DateTime.tryParse(_start!) : null;
  DateTime? get _rangeEnd => _end != null ? DateTime.tryParse(_end!) : null;

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    _schedRange = DateTimeRange(start: today, end: today.add(const Duration(days: 30)));
    _fetchStatus();
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  String _strip(String s) => s.replaceAll(RegExp(r'\x1B\[[0-9;]*m'), '');
  String _two(int n) => n.toString().padLeft(2, '0');
  String _ymd(DateTime d) => '${d.year}-${_two(d.month)}-${_two(d.day)}';

  // ----------------------------------------------------------- generate
  Future<void> _pickSchedRange() async {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final picked = await showDateRangePicker(
      context: context,
      firstDate: DateTime(today.year - 1),
      lastDate: today.add(const Duration(days: 365)),
      initialDateRange: _schedRange,
      helpText: 'Select the schedule range',
    );
    if (picked != null) setState(() => _schedRange = picked);
  }

  Future<void> _generate() async {
    if (_schedRange == null) return;
    setState(() {
      _busy = true;
      _error = null;
      _log = const [];
      _clockMsg = null;
    });
    try {
      final r = await http.post(
        Uri.parse('${widget.baseUrl}/api/simulation/run/'),
        headers: _headers,
        body: jsonEncode({
          'start': _ymd(_schedRange!.start),
          'end': _ymd(_schedRange!.end),
        }),
      );
      if (r.statusCode == 202) {
        setState(() {
          _state = 'RUNNING';
          _progress = 0;
        });
        _startPolling();
      } else {
        final j = _tryJson(r.body);
        setState(() {
          _state = 'FAILED';
          _error = (j?['error'] ?? r.body).toString();
        });
      }
    } catch (e) {
      setState(() {
        _state = 'FAILED';
        _error = e.toString();
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _startPolling() {
    _poll?.cancel();
    _poll = Timer.periodic(const Duration(seconds: 2), (_) => _fetchStatus());
  }

  Future<void> _fetchStatus() async {
    try {
      final r = await http.get(
        Uri.parse('${widget.baseUrl}/api/simulation/run/'),
        headers: _headers,
      );
      if (r.statusCode != 200 || !mounted) return;
      final j = jsonDecode(r.body) as Map<String, dynamic>;
      setState(() {
        _state = (j['state'] ?? 'idle').toString();
        if (j['progress'] is num) _progress = (j['progress'] as num).toDouble();
        _latestDay = j['latest_day']?.toString();
        _group = j['group']?.toString();
        _start = j['start']?.toString();
        _end = j['end']?.toString();
        _error = j['error']?.toString();
        _totalDays =
            (j['total_working_days'] is num) ? (j['total_working_days'] as num).toInt() : null;
        final lt = (j['log_tail'] as List?) ?? const [];
        _log = lt.map((e) => _strip(e.toString())).toList();
      });
      if (_state != 'RUNNING') _poll?.cancel();
    } catch (_) {/* transient */}
  }

  Future<void> _cancel() async {
    try {
      await http.delete(
        Uri.parse('${widget.baseUrl}/api/simulation/run/'),
        headers: _headers,
      );
    } catch (_) {/* ignore — we reset locally regardless */}
    _poll?.cancel();
    if (!mounted) return;
    setState(() {
      _state = 'idle';
      _progress = null;
      _latestDay = null;
      _group = null;
      _log = const [];
      _error = null;
    });
  }

  // ----------------------------------------------------------- roll clock
  Future<void> _pickRollDate() async {
    final lo = _rangeStart ?? DateTime(2025);
    final hi = _rangeEnd ?? DateTime(2027);
    final init = _rollDate ?? lo;
    final picked = await showDatePicker(
      context: context,
      initialDate: init.isBefore(lo) ? lo : (init.isAfter(hi) ? hi : init),
      firstDate: lo,
      lastDate: hi,
      helpText: 'Pick a day inside the schedule',
    );
    if (picked != null) setState(() => _rollDate = picked);
  }

  Future<void> _pickRollTime() async {
    final t = await showTimePicker(context: context, initialTime: _rollTime);
    if (t != null) setState(() => _rollTime = t);
  }

  Future<void> _setClock() async {
    if (_rollDate == null) return;
    setState(() {
      _settingClock = true;
      _clockMsg = null;
    });
    try {
      final dateStr = _ymd(_rollDate!);
      final timeStr = '${_two(_rollTime.hour)}:${_two(_rollTime.minute)}';
      final r = await http.post(
        Uri.parse('${widget.baseUrl}/api/clock/set/'),
        headers: _headers,
        body: jsonEncode({'date': dateStr, 'time': timeStr}),
      );
      final ok = r.statusCode == 200;
      final j = _tryJson(r.body);
      setState(() {
        _clockOk = ok;
        _clockMsg = ok
            ? 'Clock set to $dateStr $timeStr — the Live Map rolls from here.'
            : 'Failed: ${(j?['error'] ?? r.body)}';
      });
    } catch (e) {
      setState(() {
        _clockOk = false;
        _clockMsg = 'Failed: $e';
      });
    } finally {
      if (mounted) setState(() => _settingClock = false);
    }
  }

  // ----------------------------------------------------------- build
  @override
  Widget build(BuildContext context) {
    final running = _state == 'RUNNING';
    final showRoll = _rangeStart != null && _rangeEnd != null && !running;
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _generateCard(running),
              if (showRoll) ...[const SizedBox(height: 16), _rollCard()],
            ],
          ),
        ),
      ),
    );
  }

  Widget _generateCard(bool running) {
    final r = _schedRange;
    final days = r == null ? 0 : r.duration.inDays + 1;
    final rangeLabel = r == null ? 'Pick a range' : '${_ymd(r.start)} → ${_ymd(r.end)}';
    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            Icon(Icons.auto_awesome, color: _accent),
            const SizedBox(width: 8),
            const Text('Generate Full Schedule',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
          ]),
          const SizedBox(height: 6),
          Text('Build a maintenance schedule for your group with Gurobi.',
              style: TextStyle(color: Colors.grey.shade600)),
          const SizedBox(height: 20),
          Text('Schedule range',
              style: TextStyle(fontWeight: FontWeight.w600, color: Colors.grey.shade800)),
          const SizedBox(height: 8),
          Row(children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: running ? null : _pickSchedRange,
                icon: const Icon(Icons.date_range, size: 18),
                label: Text(rangeLabel),
                style: OutlinedButton.styleFrom(
                    foregroundColor: Colors.grey.shade900,
                    padding: const EdgeInsets.symmetric(vertical: 14)),
              ),
            ),
            const SizedBox(width: 12),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
              decoration: BoxDecoration(
                color: _accent.withOpacity(0.10),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text('$days days',
                  style: TextStyle(color: _accent, fontWeight: FontWeight.bold)),
            ),
          ]),
          const SizedBox(height: 20),
          FilledButton.icon(
            onPressed: (_busy || running || _schedRange == null) ? null : _generate,
            style: FilledButton.styleFrom(
                backgroundColor: _accent, padding: const EdgeInsets.symmetric(vertical: 14)),
            icon: running
                ? const SizedBox(
                    height: 18, width: 18,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : const Icon(Icons.play_arrow),
            label: Text(running ? 'Generating…' : 'Generate Schedule'),
          ),
          if (running) ...[const SizedBox(height: 22), _progressBlock()],
          if (_state == 'DONE') ...[const SizedBox(height: 22), _doneBlock()],
          if (_state == 'FAILED') ...[const SizedBox(height: 22), _errorBlock()],
        ],
      ),
    );
  }

  Widget _rollCard() {
    final dateLabel = _rollDate == null ? 'Pick a date' : _ymd(_rollDate!);
    final timeLabel = '${_two(_rollTime.hour)}:${_two(_rollTime.minute)}';
    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            Icon(Icons.play_circle_outline, color: _accent),
            const SizedBox(width: 8),
            const Text('Roll real time from a date',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
          ]),
          const SizedBox(height: 6),
          Text(
            'Pick a moment inside the generated schedule '
            '(${_start ?? ''} → ${_end ?? ''}). The Live Map and mobile play forward from here.',
            style: TextStyle(color: Colors.grey.shade600),
          ),
          const SizedBox(height: 18),
          Row(children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _pickRollDate,
                icon: const Icon(Icons.calendar_today, size: 18),
                label: Text(dateLabel),
                style: OutlinedButton.styleFrom(
                    foregroundColor: Colors.grey.shade900,
                    padding: const EdgeInsets.symmetric(vertical: 14)),
              ),
            ),
            const SizedBox(width: 12),
            OutlinedButton.icon(
              onPressed: _pickRollTime,
              icon: const Icon(Icons.schedule, size: 18),
              label: Text(timeLabel),
              style: OutlinedButton.styleFrom(
                  foregroundColor: Colors.grey.shade900,
                  padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 16)),
            ),
          ]),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: (_rollDate == null || _settingClock) ? null : _setClock,
            style: FilledButton.styleFrom(
                backgroundColor: _accent, padding: const EdgeInsets.symmetric(vertical: 14)),
            icon: _settingClock
                ? const SizedBox(
                    height: 18, width: 18,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : const Icon(Icons.play_arrow),
            label: const Text('Roll from this date'),
          ),
          if (_clockMsg != null) ...[
            const SizedBox(height: 14),
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: _clockOk ? Colors.green.shade50 : Colors.red.shade50,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(
                    color: _clockOk ? Colors.green.shade200 : Colors.red.shade200),
              ),
              child: Row(children: [
                Icon(_clockOk ? Icons.check_circle : Icons.error_outline,
                    color: _clockOk ? Colors.green.shade700 : Colors.red.shade700),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(_clockMsg!,
                      style: TextStyle(
                          color: _clockOk ? Colors.green.shade900 : Colors.red.shade900)),
                ),
              ]),
            ),
          ],
        ],
      ),
    );
  }

  Widget _progressBlock() {
    final pct = _progress == null ? null : (_progress! * 100).round();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: LinearProgressIndicator(
            value: _progress,
            minHeight: 10,
            backgroundColor: Colors.grey.shade200,
            color: _accent,
          ),
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: Text(
                [
                  if (_group != null) 'Building $_group',
                  if (_latestDay != null) 'day $_latestDay',
                  if (_totalDays != null) 'of ~$_totalDays working days',
                  if (pct != null) '· $pct%',
                ].join('  '),
                style: TextStyle(color: Colors.grey.shade700, fontSize: 13),
              ),
            ),
            TextButton.icon(
              onPressed: _cancel,
              icon: const Icon(Icons.close, size: 16),
              label: const Text('Cancel'),
              style: TextButton.styleFrom(foregroundColor: Colors.red.shade700),
            ),
          ],
        ),
        if (_log.isNotEmpty) ...[const SizedBox(height: 12), _logBox()],
      ],
    );
  }

  Widget _logBox() {
    return Container(
      height: 150,
      width: double.infinity,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
          color: const Color(0xFF1E1E1E), borderRadius: BorderRadius.circular(8)),
      child: SingleChildScrollView(
        reverse: true,
        child: Text(_log.join('\n'),
            style: const TextStyle(
                color: Color(0xFFB9F6CA),
                fontFamily: 'monospace',
                fontSize: 12,
                height: 1.4)),
      ),
    );
  }

  Widget _doneBlock() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.green.shade50,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.green.shade200),
      ),
      child: Row(children: [
        Icon(Icons.check_circle, color: Colors.green.shade700),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Schedule ready',
                  style:
                      TextStyle(fontWeight: FontWeight.bold, color: Colors.green.shade900)),
              const SizedBox(height: 2),
              Text(
                '${_group ?? ''}  ·  ${_start ?? ''} → ${_end ?? ''}. '
                'Pick a date below to roll real time from.',
                style: TextStyle(color: Colors.green.shade900),
              ),
            ],
          ),
        ),
      ]),
    );
  }

  Widget _errorBlock() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.red.shade50,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.red.shade200),
      ),
      child: Row(children: [
        Icon(Icons.error_outline, color: Colors.red.shade700),
        const SizedBox(width: 12),
        Expanded(
            child: Text(_error ?? 'Generation failed.',
                style: TextStyle(color: Colors.red.shade900))),
      ]),
    );
  }

  Widget _card({required Widget child}) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        boxShadow: [
          BoxShadow(
              color: Colors.black.withOpacity(0.05),
              blurRadius: 10,
              offset: const Offset(0, 3)),
        ],
      ),
      child: child,
    );
  }

  Map<String, dynamic>? _tryJson(String s) {
    try {
      return jsonDecode(s) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }
}
