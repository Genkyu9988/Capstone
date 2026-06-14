import 'package:flutter/material.dart';

class TechnicianDashboard extends StatefulWidget {
  const TechnicianDashboard({super.key});

  @override
  State<TechnicianDashboard> createState() => _TechnicianDashboardState();
}

class _TechnicianDashboardState extends State<TechnicianDashboard> {
  // Mock Data: Simulating the derived schedule from the Gurobi optimization backend
  // Mixed with a dynamic emergency 'Callback' injected by the Supervisor.
  final List<Map<String, dynamic>> dailyTasks = [
    {
      'id': 'T-101',
      'time': '09:00 AM',
      'type': 'Planned Maintenance',
      'unitName': 'Zorlu Center - Unit #0',
      'address': 'Levazım, Koru Sokağı No:2, Beşiktaş',
      'isEmergency': false,
      'status': 'IN_PROGRESS', // Currently active task
    },
    {
      'id': 'T-102',
      'time': '10:30 AM',
      'type': 'AA Priority Callback',
      'unitName': 'Zorlu Center - Unit #1',
      'address': 'Levazım, Koru Sokağı No:2, Beşiktaş',
      'isEmergency': true, // This will trigger the red UI highlight
      'status': 'ASSIGNED',
    },
    {
      'id': 'T-103',
      'time': '01:00 PM',
      'type': 'Planned Maintenance',
      'unitName': 'Zorlu Center - Unit #2',
      'address': 'Levazım, Koru Sokağı No:2, Beşiktaş',
      'isEmergency': false,
      'status': 'ASSIGNED',
    },
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.grey[50], // Slightly off-white for contrast with cards
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _buildHeader(),
              const SizedBox(height: 32),
              const Text(
                "Today's Schedule",
                style: TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.bold,
                  color: Colors.black87,
                ),
              ),
              const SizedBox(height: 16),
              // Expanded ensures the ListView takes up the remaining screen space
              Expanded(
                child: ListView.builder(
                  itemCount: dailyTasks.length,
                  itemBuilder: (context, index) {
                    final task = dailyTasks[index];
                    return _buildTaskCard(task);
                  },
                ),
              ),
            ],
          ),
        ),
      ),
      // Optional: A bottom navigation bar to match standard app layouts
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: 0,
        selectedItemColor: Colors.blue[800],
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.list_alt), label: 'Tasks'),
          BottomNavigationBarItem(icon: Icon(Icons.map_outlined), label: 'Map'),
          BottomNavigationBarItem(icon: Icon(Icons.person_outline), label: 'Profile'),
        ],
      ),
    );
  }

  // --- Widget: Top Left Header Information ---
  Widget _buildHeader() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Name
        const Text(
          'Cem Ekinci',
          style: TextStyle(
            fontSize: 28,
            fontWeight: FontWeight.w800,
            color: Colors.black87,
            letterSpacing: -0.5,
          ),
        ),
        const SizedBox(height: 4),
        // Role
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(
            color: Colors.blue[100],
            borderRadius: BorderRadius.circular(20),
          ),
          child: Text(
            'Callback Technician',
            style: TextStyle(
              fontSize: 14,
              color: Colors.blue[900],
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
        const SizedBox(height: 12),
        // Time of Day & Exact Time
        Row(
          children: [
            Icon(Icons.wb_sunny_outlined, size: 18, color: Colors.orange[600]),
            const SizedBox(width: 8),
            Text(
              'Good Morning • 09:15 AM',
              style: TextStyle(
                fontSize: 15,
                color: Colors.grey[700],
                fontWeight: FontWeight.w500,
              ),
            ),
          ],
        ),
      ],
    );
  }

  // --- Widget: Individual Task Card ---
  Widget _buildTaskCard(Map<String, dynamic> task) {
    final bool isEmergency = task['isEmergency'];
    final bool isActive = task['status'] == 'IN_PROGRESS';

    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      decoration: BoxDecoration(
        color: isEmergency ? Colors.red[50] : Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          // Red border for emergencies, blue for active tasks, grey for standard
          color: isEmergency 
              ? Colors.red[400]! 
              : (isActive ? Colors.blue[300]! : Colors.grey[200]!),
          width: isEmergency || isActive ? 2 : 1,
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.03),
            blurRadius: 10,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Row 1: Time and Emergency Badge
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  task['time'],
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                    color: isEmergency ? Colors.red[700] : Colors.black87,
                  ),
                ),
                if (isEmergency)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: Colors.red[600],
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: const Row(
                      children: [
                        Icon(Icons.warning_amber_rounded, color: Colors.white, size: 16),
                        SizedBox(width: 4),
                        Text(
                          'EMERGENCY',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 12,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 12),
            
            // Row 2: Task Type & Unit Name
            Text(
              '${task['type']} - ${task['unitName']}',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: Colors.grey[800],
              ),
            ),
            const SizedBox(height: 8),

            // Row 3: Address / Location
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.location_on_outlined, size: 18, color: Colors.grey[500]),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    task['address'],
                    style: TextStyle(
                      fontSize: 14,
                      color: Colors.grey[600],
                      height: 1.4,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),

            // Row 4: Action Button (Navigate)
            Align(
              alignment: Alignment.centerLeft,
              child: ElevatedButton.icon(
                onPressed: () {
                  // Logic to open Google Maps navigation
                },
                icon: const Icon(Icons.map, size: 18),
                label: const Text('Navigate'),
                style: ElevatedButton.styleFrom(
                  foregroundColor: isEmergency ? Colors.white : Colors.blue[800],
                  backgroundColor: isEmergency ? Colors.red[600] : Colors.blue[50],
                  elevation: 0,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(8),
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