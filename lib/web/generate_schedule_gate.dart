// generate_schedule_gate.dart
// =============================================================================
// Post-login gate. After a supervisor signs in, this screen shows first —
// they generate a schedule and pick a roll date here — then tap "Continue to
// Dashboard" to enter the main dashboard.
//
// It takes the dashboard widget as `next`, so it never imports the dashboard
// (no circular import). The login screen constructs it like:
//
//   GenerateScheduleGate(
//     baseUrl: kBaseUrl,
//     token: kSupervisorToken,
//     next: SupervisorDashboardScreen(supervisorName: kSupervisorName),
//   )
// =============================================================================
import 'package:flutter/material.dart';

import 'generate_schedule_tab.dart';

class GenerateScheduleGate extends StatelessWidget {
  final String baseUrl;
  final String token;
  final Widget next;
  const GenerateScheduleGate({
    super.key,
    required this.baseUrl,
    required this.token,
    required this.next,
  });

  @override
  Widget build(BuildContext context) {
    final accent = Colors.blue.shade800;
    return Scaffold(
      backgroundColor: Colors.grey.shade100,
      appBar: AppBar(
        backgroundColor: Colors.white,
        foregroundColor: Colors.black87,
        elevation: 0.5,
        title: const Text('Set up your schedule'),
      ),
      body: Column(
        children: [
          Expanded(
            child: GenerateScheduleTab(baseUrl: baseUrl, token: token),
          ),
          Material(
            color: Colors.white,
            elevation: 8,
            child: SafeArea(
              top: false,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text('Generate a schedule, then continue.',
                        style: TextStyle(color: Colors.grey.shade600)),
                    FilledButton.icon(
                      onPressed: () => Navigator.pushReplacement(
                        context,
                        MaterialPageRoute(builder: (_) => next),
                      ),
                      style: FilledButton.styleFrom(
                        backgroundColor: accent,
                        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
                      ),
                      icon: const Icon(Icons.arrow_forward),
                      label: const Text('Continue to Dashboard'),
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
