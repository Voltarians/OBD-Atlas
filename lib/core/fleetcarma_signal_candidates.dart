import 'dart:convert';

import 'package:flutter/foundation.dart';

import 'can_frame.dart';

class FleetCarmaSignalCandidate {
  const FleetCarmaSignalCandidate({
    required this.bus,
    required this.canId,
    required this.kind,
    required this.offset,
    required this.speedCorrelation,
    required this.overlap,
    required this.confidence,
  });

  final int bus;
  final int canId;
  final String kind;
  final int offset;
  final double speedCorrelation;
  final int overlap;
  final String confidence;

  String get canIdHex => canId.toRadixString(16).toUpperCase().padLeft(3, '0');
  double get absSpeedCorrelation => speedCorrelation.abs();

  int? decode(CanFrame frame) {
    if (frame.id != canId || offset < 0) return null;
    if (kind == 'u8') {
      if (offset >= frame.data.length) return null;
      return frame.data[offset];
    }
    if (offset + 1 >= frame.data.length) return null;
    final a = frame.data[offset];
    final b = frame.data[offset + 1];
    if (kind == 'u16le') return a | (b << 8);
    if (kind == 'u16be') return (a << 8) | b;
    return null;
  }

  factory FleetCarmaSignalCandidate.fromJson(Map<String, dynamic> json) {
    final hex = (json['canIdHex'] ?? '').toString().trim();
    return FleetCarmaSignalCandidate(
      bus: (json['bus'] as num?)?.toInt() ?? 0,
      canId: int.tryParse(hex, radix: 16) ?? -1,
      kind: (json['kind'] ?? '').toString(),
      offset: (json['offset'] as num?)?.toInt() ?? -1,
      speedCorrelation: (json['speedCorrelation'] as num?)?.toDouble() ?? 0,
      overlap: (json['overlap'] as num?)?.toInt() ?? 0,
      confidence: (json['confidence'] ?? 'background').toString(),
    );
  }
}

class FleetCarmaCandidateReport {
  const FleetCarmaCandidateReport({
    required this.schema,
    required this.mappingStatus,
    required this.evidenceBoundary,
    required this.sourceFiles,
    required this.canFrames,
    required this.gpsSpeedSamples,
    required this.topSpeedCandidates,
  });

  final String schema;
  final String mappingStatus;
  final String evidenceBoundary;
  final int sourceFiles;
  final int canFrames;
  final int gpsSpeedSamples;
  final List<FleetCarmaSignalCandidate> topSpeedCandidates;

  factory FleetCarmaCandidateReport.fromJson(Map<String, dynamic> json) {
    final raw = json['topSpeedCandidates'];
    final candidates = raw is List
        ? raw
            .whereType<Map>()
            .map((item) => FleetCarmaSignalCandidate.fromJson(
                  item.map((key, value) => MapEntry(key.toString(), value)),
                ))
            .where((candidate) => candidate.canId >= 0)
            .toList(growable: false)
        : const <FleetCarmaSignalCandidate>[];

    return FleetCarmaCandidateReport(
      schema: (json['schema'] ?? '').toString(),
      mappingStatus: (json['mappingStatus'] ?? '').toString(),
      evidenceBoundary: (json['evidenceBoundary'] ?? '').toString(),
      sourceFiles: (json['sourceFiles'] as num?)?.toInt() ?? 0,
      canFrames: (json['canFrames'] as num?)?.toInt() ?? 0,
      gpsSpeedSamples: (json['gpsSpeedSamples'] as num?)?.toInt() ?? 0,
      topSpeedCandidates: candidates,
    );
  }

  static FleetCarmaCandidateReport? tryParse(String text) {
    try {
      final decoded = jsonDecode(text);
      if (decoded is! Map) return null;
      final json = decoded.map((key, value) => MapEntry(key.toString(), value));
      if (json['schema'] != 'atlas.fleetcarma-signal-correlation.v1') return null;
      return FleetCarmaCandidateReport.fromJson(json);
    } catch (_) {
      return null;
    }
  }
}

class FleetCarmaValidationSample {
  const FleetCarmaValidationSample({
    required this.timestamp,
    required this.channel,
    required this.rawValue,
    required this.payloadHex,
    required this.targetMph,
  });

  final DateTime timestamp;
  final int channel;
  final int rawValue;
  final String payloadHex;
  final double? targetMph;

  Map<String, dynamic> toJson() => {
        'timestamp': timestamp.toUtc().toIso8601String(),
        'channel': channel,
        'rawValue': rawValue,
        'payloadHex': payloadHex,
        'targetMph': targetMph,
      };
}

class FleetCarmaValidationMarker {
  const FleetCarmaValidationMarker({
    required this.timestamp,
    required this.label,
    this.targetMph,
  });

  final DateTime timestamp;
  final String label;
  final double? targetMph;

  Map<String, dynamic> toJson() => {
        'timestamp': timestamp.toUtc().toIso8601String(),
        'label': label,
        'targetMph': targetMph,
      };
}

class FleetCarmaCandidateWorkspace extends ChangeNotifier {
  FleetCarmaCandidateWorkspace._();

  static final FleetCarmaCandidateWorkspace instance =
      FleetCarmaCandidateWorkspace._();

  FleetCarmaCandidateReport? report;
  FleetCarmaSignalCandidate? selectedCandidate;

  bool validationActive = false;
  DateTime? validationStarted;
  DateTime? validationEnded;
  double? currentTargetMph;
  final List<FleetCarmaValidationSample> samples = <FleetCarmaValidationSample>[];
  final List<FleetCarmaValidationMarker> markers = <FleetCarmaValidationMarker>[];

  bool loadJsonText(String text) {
    final parsed = FleetCarmaCandidateReport.tryParse(text);
    if (parsed == null) return false;
    report = parsed;
    selectedCandidate = parsed.topSpeedCandidates.isEmpty
        ? null
        : parsed.topSpeedCandidates.first;
    notifyListeners();
    return true;
  }

  void selectCandidate(FleetCarmaSignalCandidate candidate) {
    if (validationActive) {
      throw StateError('Finish the active validation before changing candidates.');
    }
    selectedCandidate = candidate;
    notifyListeners();
  }

  void startValidation() {
    if (selectedCandidate == null) {
      throw StateError('Select a FleetCarma candidate first.');
    }
    samples.clear();
    markers.clear();
    validationStarted = DateTime.now().toUtc();
    validationEnded = null;
    currentTargetMph = null;
    validationActive = true;
    notifyListeners();
  }

  void markStep(String label, {double? targetMph}) {
    if (!validationActive) {
      throw StateError('Start FleetCarma candidate validation first.');
    }
    currentTargetMph = targetMph;
    markers.add(FleetCarmaValidationMarker(
      timestamp: DateTime.now().toUtc(),
      label: label,
      targetMph: targetMph,
    ));
    notifyListeners();
  }

  void observe(CanFrame frame) {
    if (!validationActive) return;
    final candidate = selectedCandidate;
    if (candidate == null) return;
    final value = candidate.decode(frame);
    if (value == null) return;
    samples.add(FleetCarmaValidationSample(
      timestamp: frame.timestamp,
      channel: frame.channel,
      rawValue: value,
      payloadHex: frame.dataHex,
      targetMph: currentTargetMph,
    ));
  }

  Map<String, dynamic> finishValidation() {
    validationActive = false;
    validationEnded = DateTime.now().toUtc();
    final reportJson = buildValidationReport();
    notifyListeners();
    return reportJson;
  }

  Map<String, dynamic> buildValidationReport() {
    final candidate = selectedCandidate;
    if (candidate == null) {
      throw StateError('No FleetCarma candidate selected.');
    }

    final grouped = <double, List<int>>{};
    for (final sample in samples) {
      final target = sample.targetMph;
      if (target == null) continue;
      grouped.putIfAbsent(target, () => <int>[]).add(sample.rawValue);
    }

    final steps = grouped.entries.map((entry) {
      final values = entry.value;
      final sum = values.fold<int>(0, (total, value) => total + value);
      return {
        'targetMph': entry.key,
        'samples': values.length,
        'rawMin': values.reduce((a, b) => a < b ? a : b),
        'rawMax': values.reduce((a, b) => a > b ? a : b),
        'rawMean': sum / values.length,
      };
    }).toList()
      ..sort((a, b) =>
          (a['targetMph'] as double).compareTo(b['targetMph'] as double));

    return {
      'schema': 'atlas.fleetcarma-live-validation.v1',
      'mappingStatus': 'candidateOnly',
      'promotionAllowed': false,
      'evidenceBoundary':
          'Live samples are validation evidence only. Semantic confirmation requires review of repeatability, scaling, and independent captures.',
      'candidate': {
        'historicalBus': candidate.bus,
        'canIdHex': candidate.canIdHex,
        'kind': candidate.kind,
        'offset': candidate.offset,
        'historicalSpeedCorrelation': candidate.speedCorrelation,
        'historicalOverlap': candidate.overlap,
        'historicalConfidence': candidate.confidence,
      },
      'startedUtc': validationStarted?.toIso8601String(),
      'endedUtc': validationEnded?.toIso8601String(),
      'sampleCount': samples.length,
      'markers': markers.map((marker) => marker.toJson()).toList(),
      'steps': steps,
      'samples': samples.map((sample) => sample.toJson()).toList(),
    };
  }
}
