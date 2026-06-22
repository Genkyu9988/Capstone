// generate_schedule_tab.dart
// =============================================================================
// "Generate Schedule" tab for the supervisor dashboard.
//
// Self-contained (takes baseUrl + token as params, like showcase_route_map.dart),
// so it adds a tab without touching anything private in supervisor_dashboard.dart.
// Constructor is unchanged, so supervisor_dashboard.dart needs no edits:
//
//   GenerateScheduleTab(baseUrl: kBaseUrl, token: kSupervisorToken)
//
// What's here:
//   1. Length chips + "Generate"          -> POST   /api/simulation/run/ {months}
//   2. "Reset & Generate" (clean slate)    -> POST   /api/simulation/reset/  then generate
//   3. "Cancel" while a run is in progress -> DELETE /api/simulation/run/
//   4. LEFT panel  : the generated schedule's full span (start -> finish)
//   5. RIGHT panel : the operating "rolled" clock, ticking forward in real time
//                    (polls GET /api/clock/set/ and advances 1:1 between polls)
//   6. Roll-from-date card -> POST /api/clock/set/ {date,time}
//
// The reset endpoint clears the previous plan, re-seeds the unit maintenance
// clocks, and resets the operating clock, so each generate starts fresh.
// =============================================================================
import 'dart:async';
import 'dart:convert';
import 'dart:ui' show FontFeature;

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
  static final Color _danger = Colors.red.shade700;

  // --- generate state ---
  int _months = 3;
  bool _busy = false;        // generate request in flight
  bool _resetting = false;   // reset request in flight
  Timer? _poll;
  String _state = 'idle';    // idle | RUNNING | DONE | FAILED
  double? _progress;
  String? _group, _start, _end, _latestDay, _error;
  int? _totalDays;
  List<String> _log = const [];

  // --- live operating clock ("rolled time") ---
  Timer? _clockPoll;   // pulls the server clock every few seconds
  Timer? _clockTick;   // repaints every second so it visibly ticks
  bool _clockSet = false;
  DateTime? _clockNowUtc;      // last value read from the server (UTC)
  DateTime? _clockReadAtLocal; // local instant we read it (to advance 1:1)
  String? _clockStatus;

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

  // displayed operating time = last server value + real time elapsed since we read it
  DateTime? get _displayClock {
    if (_clockNowUtc == null || _clockReadAtLocal == null) return null;
    return _clockNowUtc!.add(DateTime.now().difference(_clockReadAtLocal!));
  }

  @override
  void initState() {
    super.initState();
    _fetchStatus();
    _fetchClock();
    _clockPoll = Timer.periodic(const Duration(seconds: 3), (_) => _fetchClock());
    _clockTick = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted && _clockSet) setState(() {}); // tick the readout
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    _clockPoll?.cancel();
    _clockTick?.cancel();
    super.dispose();
  }

  String _strip(String s) => s.replaceAll(RegExp(r'\x1B\[[0-9;]*m'), '');
  String _two(int n) => n.toString().padLeft(2, '0');
  String _fmtDate(DateTime d) => '${d.year}-${_two(d.month)}-${_two(d.day)}';
  String _fmtClock(DateTime d) =>
      '${d.year}-${_two(d.month)}-${_two(d.day)}   ${_two(d.hour)}:${_two(d.minute)}:${_two(d.second)}';

  // ----------------------------------------------------------- generate
  Future<void> _generate() async {
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
        body: jsonEncode({'months': _months}),
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

  // ----------------------------------------------------- reset & generate
  Future<void> _resetAndGenerate() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Reset and generate a fresh schedule?'),
        content: const Text(
          'This wipes the current plan and resets the maintenance clocks back '
          'to the start, then generates a brand-new schedule from today. '
          'Use this when a re-generate keeps showing the old plan.',
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: _danger),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Reset & generate'),
          ),
        ],
      ),
    );
    if (ok != true) return;

    setState(() {
      _resetting = true;
      _error = null;
      _state = 'idle';
      _start = null;
      _end = null;
      _log = const [];
      _clockMsg = null;
    });
    try {
      final r = await http.post(
        Uri.parse('${widget.baseUrl}/api/simulation/reset/'),
        headers: _headers,
        body: jsonEncode({}),
      );
      if (r.statusCode != 200) {
        final j = _tryJson(r.body);
        setState(() {
          _state = 'FAILED';
          _error = 'Reset failed: ${(j?['error'] ?? r.body)}';
        });
        return;
      }
      await _fetchClock(); // reflect the clock reset immediately
    } catch (e) {
      setState(() {
        _state = 'FAILED';
        _error = 'Reset failed: $e';
      });
      return;
    } finally {
      if (mounted) setState(() => _resetting = false);
    }
    await _generate(); // clean slate -> build the new plan
  }

  // ----------------------------------------------------------- cancel
  Future<void> _cancel() async {
    try {
      await http.delete(
        Uri.parse('${widget.baseUrl}/api/simulation/run/'),
        headers: _headers,
      );
    } catch (_) {/* ignore */}
    _poll?.cancel();
    if (mounted) setState(() => _state = 'idle');
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

  // ----------------------------------------------------- live clock fetch
  Future<void> _fetchClock() async {
    try {
      final r = await http.get(
        Uri.parse('${widget.baseUrl}/api/clock/set/'),
        headers: _headers,
      );
      if (r.statusCode != 200 || !mounted) return;
      final j = jsonDecode(r.body) as Map<String, dynamic>;
      final set = j['set'] == true;
      final nowRaw = j['now']?.toString();
      setState(() {
        _clockSet = set;
        _clockStatus = j['status']?.toString();
        if (set && nowRaw != null) {
          final parsed = DateTime.tryParse(nowRaw);
          if (parsed != null) {
            _clockNowUtc = parsed.toUtc();          // show operating time as set
            _clockReadAtLocal = DateTime.now();
          }
        } else {
          _clockNowUtc = null;
          _clockReadAtLocal = null;
        }
      });
    } catch (_) {/* transient */}
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
      final dateStr =
          '${_rollDate!.year}-${_two(_rollDate!.month)}-${_two(_rollDate!.day)}';
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
            ? 'Clock set to $dateStr $timeStr — watch it roll on the right.'
            : 'Failed: ${(j?['error'] ?? r.body)}';
      });
      if (ok) await _fetchClock();
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
          constraints: const BoxConstraints(maxWidth: 880),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _generateCard(running),
              const SizedBox(height: 16),
              _twoPanels(),
              if (showRoll) ...[
                const SizedBox(height: 16),
                _rollCard(),
              ],
            ],
          ),
        ),
      ),
    );
  }

  // ----- the two panels: LEFT = generated span, RIGHT = live rolled time -----
  Widget _twoPanels() {
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(child: _generatedSpanPanel()),
          const SizedBox(width: 16),
          Expanded(child: _rolledTimePanel()),
        ],
      ),
    );
  }

  Widget _generatedSpanPanel() {
    final s = _rangeStart, e = _rangeEnd;
    final has = s != null && e != null;
    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(Icons.event_note, color: _accent),
            const SizedBox(width: 8),
            const Text('Generated schedule',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
          ]),
          const SizedBox(height: 4),
          Text('The full plan you generated',
              style: TextStyle(color: Colors.grey.shade600, fontSize: 13)),
          const SizedBox(height: 16),
          if (!has)
            Text('No schedule yet — generate one above.',
                style: TextStyle(color: Colors.grey.shade500))
          else ...[
            _spanRow('Start', _fmtDate(s!)),
            const SizedBox(height: 10),
            _spanRow('Finish', _fmtDate(e!)),
            const SizedBox(height: 10),
            _spanRow('Group', _group ?? '—'),
            const SizedBox(height: 10),
            _spanRow(
                'Working days',
                _totalDays != null
                    ? '$_totalDays'
                    : '${e.difference(s).inDays + 1} calendar days'),
          ],
        ],
      ),
    );
  }

  Widget _spanRow(String k, String v) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 96,
          child: Text(k,
              style: TextStyle(color: Colors.grey.shade600, fontSize: 13)),
        ),
        Expanded(
          child: Text(v,
              style: const TextStyle(
                  fontSize: 15, fontWeight: FontWeight.w600)),
        ),
      ],
    );
  }

  Widget _rolledTimePanel() {
    final now = _displayClock;
    final s = _rangeStart, e = _rangeEnd;
    double? frac;
    if (now != null && s != null && e != null) {
      final total = e.difference(s).inSeconds;
      if (total > 0) {
        frac = now.difference(s).inSeconds / total;
        if (frac < 0) frac = 0;
        if (frac > 1) frac = 1;
      }
    }
    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(Icons.timelapse,
                color: _clockSet ? Colors.green.shade700 : Colors.grey),
            const SizedBox(width: 8),
            const Text('Rolled time (live)',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
            const Spacer(),
            if (_clockSet)
              Container(
                width: 9,
                height: 9,
                decoration: BoxDecoration(
                    color: Colors.green.shade500, shape: BoxShape.circle),
              ),
          ]),
          const SizedBox(height: 4),
          Text('The operating clock, ticking in real time',
              style: TextStyle(color: Colors.grey.shade600, fontSize: 13)),
          const SizedBox(height: 16),
          if (!_clockSet || now == null) ...[
            Text('Not rolling yet.',
                style: TextStyle(color: Colors.grey.shade500)),
            const SizedBox(height: 6),
            Text('Generate a schedule, then roll from a date below.',
                style: TextStyle(color: Colors.grey.shade500, fontSize: 13)),
          ] else ...[
            Text(
              _fmtClock(now),
              style: TextStyle(
                fontSize: 22,
                fontWeight: FontWeight.bold,
                fontFeatures: const [FontFeature.tabularFigures()],
                color: Colors.green.shade900,
              ),
            ),
            const SizedBox(height: 14),
            if (frac != null) ...[
              ClipRRect(
                borderRadius: BorderRadius.circular(6),
                child: LinearProgressIndicator(
                  value: frac,
                  minHeight: 8,
                  backgroundColor: Colors.grey.shade200,
                  color: Colors.green.shade600,
                ),
              ),
              const SizedBox(height: 6),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(_fmtDate(s!),
                      style: TextStyle(
                          color: Colors.grey.shade500, fontSize: 11)),
                  Text('${(frac * 100).round()}% through plan',
                      style: TextStyle(
                          color: Colors.grey.shade600,
                          fontSize: 11,
                          fontWeight: FontWeight.w600)),
                  Text(_fmtDate(e!),
                      style: TextStyle(
                          color: Colors.grey.shade500, fontSize: 11)),
                ],
              ),
            ],
          ],
        ],
      ),
    );
  }

  Widget _generateCard(bool running) {
    final busy = _busy || _resetting || running;
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
          Text(
            'Build a maintenance schedule for your group. '
            'Use "Reset & Generate" for a clean slate if a re-run keeps showing the old plan.',
            style: TextStyle(color: Colors.grey.shade600),
          ),
          const SizedBox(height: 20),
          Text('Length',
              style: TextStyle(fontWeight: FontWeight.w600, color: Colors.grey.shade800)),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            children: [
              for (final m in [1, 2, 3, 4, 5, 6])
                ChoiceChip(
                  label: Text(m == 1 ? '1 month' : '$m months'),
                  selected: _months == m,
                  onSelected: busy ? null : (_) => setState(() => _months = m),
                  selectedColor: _accent.withOpacity(0.15),
                  labelStyle: TextStyle(
                    color: _months == m ? _accent : Colors.grey.shade800,
                    fontWeight: _months == m ? FontWeight.bold : FontWeight.normal,
                  ),
                ),
            ],
          ),
          const SizedBox(height: 20),
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  onPressed: busy ? null : _generate,
                  style: FilledButton.styleFrom(
                      backgroundColor: _accent,
                      padding: const EdgeInsets.symmetric(vertical: 14)),
                  icon: (running && !_resetting)
                      ? const SizedBox(
                          height: 18, width: 18,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: Colors.white))
                      : const Icon(Icons.play_arrow),
                  label: Text(running ? 'Generating…' : 'Generate'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: busy ? null : _resetAndGenerate,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: _danger,
                    side: BorderSide(color: _danger.withOpacity(0.5)),
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                  icon: _resetting
                      ? SizedBox(
                          height: 18, width: 18,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: _danger))
                      : const Icon(Icons.restart_alt),
                  label: Text(_resetting ? 'Resetting…' : 'Reset & Generate'),
                ),
              ),
            ],
          ),
          if (running) ...[
            const SizedBox(height: 12),
            TextButton.icon(
              onPressed: _cancel,
              icon: const Icon(Icons.stop_circle_outlined, size: 18),
              label: const Text('Cancel'),
              style: TextButton.styleFrom(foregroundColor: Colors.grey.shade700),
            ),
          ],
          if (running) ...[const SizedBox(height: 16), _progressBlock()],
          if (_state == 'DONE') ...[const SizedBox(height: 22), _doneBlock()],
          if (_state == 'FAILED') ...[const SizedBox(height: 22), _errorBlock()],
        ],
      ),
    );
  }

  Widget _rollCard() {
    final dateLabel = _rollDate == null
        ? 'Pick a date'
        : '${_rollDate!.year}-${_two(_rollDate!.month)}-${_two(_rollDate!.day)}';
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
            '(${_start ?? ''} → ${_end ?? ''}). The clock on the right, the Live Map, '
            'and mobile all play forward from here.',
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
        Text(
          [
            if (_group != null) 'Building $_group',
            if (_latestDay != null) 'day $_latestDay',
            if (_totalDays != null) 'of ~$_totalDays working days',
            if (pct != null) '· $pct%',
          ].join('  '),
          style: TextStyle(color: Colors.grey.shade700, fontSize: 13),
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
        child: Text(
          _log.join('\n'),
          style: const TextStyle(
              color: Color(0xFFB9F6CA),
              fontFamily: 'monospace',
              fontSize: 12,
              height: 1.4),
        ),
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
                'See the span on the left; roll from a date below to start the clock.',
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
