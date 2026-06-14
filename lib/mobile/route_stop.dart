// route_stop.dart
class RouteStop {
  final String taskId;
  final String type;        // "DEPOT" or "TASK"
  final String location;    // task type name from the API ("title")
  final String unitName;    // building/unit name (empty if backend doesn't send it)
  final double latitude;
  final double longitude;
  final int sequenceOrder;  // 0 = depot, then 1,2,3...
  final String priority;    // "AA" / "NORMAL" / "NONE"
  final int durationMin;    // estimated minutes for this stop

  RouteStop({
    required this.taskId,
    required this.type,
    required this.location,
    required this.unitName,
    required this.latitude,
    required this.longitude,
    required this.sequenceOrder,
    required this.priority,
    required this.durationMin,
  });

  factory RouteStop.fromJson(Map<String, dynamic> json) {
    final lat = json['latitude'];
    final lng = json['longitude'];
    final name = json['title'] ?? 'Unknown Location';
    final taskNo = json['task_no'] ?? 'Unit Only';
    final jobType = json['type'] ?? 'Elevator';
    final seq = json['stop_number'] ?? 1;
    final dur = json['duration_min'] ?? 60;

    return RouteStop(
      taskId: taskNo.toString(),
      type: jobType.toString(),
      location: name.toString(),
      unitName: (json['unit_name'] ?? '').toString(),
      latitude: double.tryParse(lat?.toString() ?? '') ?? 41.0082,
      longitude: double.tryParse(lng?.toString() ?? '') ?? 28.9784,
      sequenceOrder: seq is int ? seq : int.tryParse(seq.toString()) ?? 1,
      priority: (json['priority'] ?? 'NORMAL').toString(),
      durationMin: dur is int ? dur : int.tryParse(dur.toString()) ?? 60,
    );
  }
}
