import 'dart:convert';

import 'can_frame.dart';

/// A human-entered timestamp marker captured while another diagnostic app is
/// operating the vehicle through a pass-through adapter.
class ObservationMarker {
  const ObservationMarker({
    required this.label,
    required this.timestamp,
  });

  final String label;
  final DateTime timestamp;

  Map<String, Object> toJson() => <String, Object>{
        'label': label,
        'timestamp': timestamp.toUtc().toIso8601String(),
      };

  factory ObservationMarker.fromJson(Map<String, Object?> json) {
    return ObservationMarker(
      label: json['label'] as String,
      timestamp: DateTime.parse(json['timestamp'] as String).toUtc(),
    );
  }
}

/// One CAN identifier that changed around an observation marker.
class ObservationCandidate {
  const ObservationCandidate({
    required this.marker,
    required this.channel,
    required this.id,
    required this.beforeFrames,
    required this.afterFrames,
    required this.beforePayloads,
    required this.afterPayloads,
    required this.newPayloads,
    required this.score,
    required this.diagnosticLike,
    required this.likelyResponseId,
  });

  final ObservationMarker marker;
  final int channel;
  final int id;
  final int beforeFrames;
  final int afterFrames;
  final int beforePayloads;
  final int afterPayloads;
  final int newPayloads;
  final double score;
  final bool diagnosticLike;
  final int? likelyResponseId;

  String get idHex => id.toRadixString(16).toUpperCase().padLeft(id > 0x7FF ? 8 : 3, '0');
  String? get likelyResponseIdHex => likelyResponseId == null
      ? null
      : likelyResponseId!.toRadixString(16).toUpperCase().padLeft(likelyResponseId! > 0x7FF ? 8 : 3, '0');

  Map<String, Object?> toJson() => <String, Object?>{
        'marker': marker.label,
        'marker_timestamp': marker.timestamp.toUtc().toIso8601String(),
        'channel': channel,
        'id': idHex,
        'before_frames': beforeFrames,
        'after_frames': afterFrames,
        'before_payloads': beforePayloads,
        'after_payloads': afterPayloads,
        'new_payloads': newPayloads,
        'score': double.parse(score.toStringAsFixed(3)),
        'diagnostic_like': diagnosticLike,
        if (likelyResponseIdHex != null) 'likely_response_id': likelyResponseIdHex,
      };
}

class ObservationReport {
  const ObservationReport({
    required this.marker,
    required this.window,
    required this.candidates,
  });

  final ObservationMarker marker;
  final Duration window;
  final List<ObservationCandidate> candidates;

  Map<String, Object> toJson() => <String, Object>{
        'marker': marker.toJson(),
        'window_ms': window.inMilliseconds,
        'candidates': candidates.map((candidate) => candidate.toJson()).toList(),
      };
}

/// In-memory evidence recorder/correlator for passively observing commands sent
/// by an external app such as Voltage while OBD Atlas listens on several buses.
///
/// This class never transmits CAN frames. It only records [CanFrame] objects
/// supplied by the existing Atlas adapters and compares activity immediately
/// before and after user markers.
class ExternalAppObservationSession {
  ExternalAppObservationSession({
    this.maxFrames = 500000,
    this.defaultWindow = const Duration(seconds: 3),
  });

  final int maxFrames;
  final Duration defaultWindow;

  final List<CanFrame> _frames = <CanFrame>[];
  final List<ObservationMarker> _markers = <ObservationMarker>[];
  bool _running = false;
  bool _truncated = false;

  bool get isRunning => _running;
  bool get truncated => _truncated;
  int get frameCount => _frames.length;
  List<ObservationMarker> get markers => List<ObservationMarker>.unmodifiable(_markers);

  void start() {
    _frames.clear();
    _markers.clear();
    _truncated = false;
    _running = true;
  }

  void observe(CanFrame frame) {
    if (!_running) return;
    if (_frames.length >= maxFrames) {
      _frames.removeAt(0);
      _truncated = true;
    }
    _frames.add(frame);
  }

  ObservationMarker mark(String label, {DateTime? timestamp}) {
    if (!_running) {
      throw StateError('Observation session is not running.');
    }
    final normalized = label.trim();
    if (normalized.isEmpty) {
      throw ArgumentError.value(label, 'label', 'Marker label cannot be empty.');
    }
    final marker = ObservationMarker(
      label: normalized,
      timestamp: (timestamp ?? DateTime.now()).toUtc(),
    );
    _markers.add(marker);
    return marker;
  }

  void finish() => _running = false;

  ObservationReport correlate(
    ObservationMarker marker, {
    Duration? window,
    int limit = 40,
  }) {
    final span = window ?? defaultWindow;
    final beforeStart = marker.timestamp.subtract(span);
    final afterEnd = marker.timestamp.add(span);

    final before = <_Key, _Stats>{};
    final after = <_Key, _Stats>{};

    for (final frame in _frames) {
      final timestamp = frame.timestamp.toUtc();
      if (timestamp.isBefore(beforeStart) || timestamp.isAfter(afterEnd)) continue;
      if (timestamp.isBefore(marker.timestamp)) {
        _statsFor(before, frame).add(frame);
      } else {
        _statsFor(after, frame).add(frame);
      }
    }

    final keys = <_Key>{...before.keys, ...after.keys};
    final availableIdsByChannel = <int, Set<int>>{};
    for (final key in keys) {
      availableIdsByChannel.putIfAbsent(key.channel, () => <int>{}).add(key.id);
    }

    final candidates = <ObservationCandidate>[];
    for (final key in keys) {
      final b = before[key] ?? _Stats.empty();
      final a = after[key] ?? _Stats.empty();
      if (a.frames == 0) continue;

      final newPayloadCount = a.payloads.difference(b.payloads).length;
      final appeared = b.frames == 0 ? 1.0 : 0.0;
      final rateIncrease = b.frames == 0
          ? a.frames.toDouble()
          : ((a.frames - b.frames) / b.frames).clamp(0.0, 10.0).toDouble();
      final payloadNovelty = a.payloads.isEmpty ? 0.0 : newPayloadCount / a.payloads.length;
      final diagnosticLike = _diagnosticLike(key.id);
      final responseId = _likelyResponseId(key.id, availableIdsByChannel[key.channel] ?? const <int>{});

      // Prefer IDs that appear at the marker, increase in frequency, or begin
      // emitting new payload states. Diagnostic-range IDs receive only a small
      // bonus so normal body/powertrain IDs can still rank first when warranted.
      final score =
          appeared * 4.0 + rateIncrease * 1.5 + payloadNovelty * 3.0 + newPayloadCount * 0.2 + (diagnosticLike ? 0.75 : 0.0) + (responseId != null ? 0.5 : 0.0);

      candidates.add(ObservationCandidate(
        marker: marker,
        channel: key.channel,
        id: key.id,
        beforeFrames: b.frames,
        afterFrames: a.frames,
        beforePayloads: b.payloads.length,
        afterPayloads: a.payloads.length,
        newPayloads: newPayloadCount,
        score: score,
        diagnosticLike: diagnosticLike,
        likelyResponseId: responseId,
      ));
    }

    candidates.sort((a, b) {
      final score = b.score.compareTo(a.score);
      if (score != 0) return score;
      final channel = a.channel.compareTo(b.channel);
      if (channel != 0) return channel;
      return a.id.compareTo(b.id);
    });

    return ObservationReport(
      marker: marker,
      window: span,
      candidates: candidates.take(limit).toList(growable: false),
    );
  }

  List<ObservationReport> correlateAll({Duration? window, int limitPerMarker = 40}) {
    return _markers
        .map((marker) => correlate(marker, window: window, limit: limitPerMarker))
        .toList(growable: false);
  }

  String exportJson({Duration? window, int limitPerMarker = 40}) {
    final reports = correlateAll(window: window, limitPerMarker: limitPerMarker);
    return const JsonEncoder.withIndent('  ').convert(<String, Object>{
      'schema': 'obd-atlas.external-app-observation.v1',
      'passive_only': true,
      'frame_count': _frames.length,
      'truncated': _truncated,
      'markers': _markers.map((marker) => marker.toJson()).toList(),
      'reports': reports.map((report) => report.toJson()).toList(),
    });
  }

  static _Stats _statsFor(Map<_Key, _Stats> map, CanFrame frame) {
    final key = _Key(frame.channel, frame.id);
    return map.putIfAbsent(key, _Stats.new);
  }

  static bool _diagnosticLike(int id) => id >= 0x700 && id <= 0x7FF;

  static int? _likelyResponseId(int requestId, Set<int> ids) {
    if (!_diagnosticLike(requestId)) return null;
    final plusEight = requestId + 8;
    if (plusEight <= 0x7FF && ids.contains(plusEight)) return plusEight;
    return null;
  }
}

class _Key {
  const _Key(this.channel, this.id);

  final int channel;
  final int id;

  @override
  bool operator ==(Object other) => other is _Key && other.channel == channel && other.id == id;

  @override
  int get hashCode => Object.hash(channel, id);
}

class _Stats {
  _Stats();
  _Stats.empty();

  int frames = 0;
  Set<String> payloads = <String>{};

  void add(CanFrame frame) {
    frames++;
    payloads.add(frame.data.map((byte) => byte.toRadixString(16).padLeft(2, '0')).join());
  }
}
