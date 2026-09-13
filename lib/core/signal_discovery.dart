import 'can_frame.dart';

enum DiscoveryPhase { idle, baseline, event, after, complete }

class SignalCandidate {
  const SignalCandidate({
    required this.channel,
    required this.id,
    required this.extended,
    required this.byteIndex,
    required this.bitIndex,
    required this.baselineProbability,
    required this.eventProbability,
    required this.afterProbability,
    required this.score,
  });

  final int channel;
  final int id;
  final bool extended;
  final int byteIndex;
  final int bitIndex;
  final double baselineProbability;
  final double eventProbability;
  final double afterProbability;
  final double score;

  String get idHex =>
      id.toRadixString(16).toUpperCase().padLeft(extended ? 8 : 3, '0');
  String get transition =>
      '${_percent(baselineProbability)} → ${_percent(eventProbability)} → ${_percent(afterProbability)}';

  static String _percent(double value) => '${(value * 100).round()}%';
}

class _SignalKey {
  const _SignalKey(this.channel, this.id, this.extended, this.length);

  final int channel;
  final int id;
  final bool extended;
  final int length;

  @override
  bool operator ==(Object other) =>
      other is _SignalKey &&
      channel == other.channel &&
      id == other.id &&
      extended == other.extended &&
      length == other.length;

  @override
  int get hashCode => Object.hash(channel, id, extended, length);
}

class _BitCounts {
  _BitCounts(int bitCount) : ones = List<int>.filled(bitCount, 0);

  int frames = 0;
  final List<int> ones;

  void add(List<int> data) {
    frames++;
    for (var byte = 0; byte < data.length; byte++) {
      for (var bit = 0; bit < 8; bit++) {
        if ((data[byte] & (1 << bit)) != 0) ones[byte * 8 + bit]++;
      }
    }
  }

  double probability(int bit) => frames == 0 ? 0 : ones[bit] / frames;
}

/// Bounded-memory, event-correlated CAN signal discovery.
///
/// Frames are reduced to per-bit occurrence counts in three operator-marked
/// windows: baseline, event, and after. A candidate must change during the
/// event and return close to its baseline state afterward.
class SignalDiscoverySession {
  DiscoveryPhase phase = DiscoveryPhase.idle;
  String eventLabel = 'Event';
  DateTime? startedAt;
  DateTime? eventStartedAt;
  DateTime? eventEndedAt;
  List<SignalCandidate> candidates = const <SignalCandidate>[];

  final Map<_SignalKey, List<_BitCounts>> _counts =
      <_SignalKey, List<_BitCounts>>{};

  bool get isRunning =>
      phase == DiscoveryPhase.baseline ||
      phase == DiscoveryPhase.event ||
      phase == DiscoveryPhase.after;

  void start({String label = 'Event', DateTime? now}) {
    _counts.clear();
    candidates = const <SignalCandidate>[];
    eventLabel = label.trim().isEmpty ? 'Event' : label.trim();
    startedAt = now ?? DateTime.now();
    eventStartedAt = null;
    eventEndedAt = null;
    phase = DiscoveryPhase.baseline;
  }

  void markEventStart({DateTime? now}) {
    if (phase != DiscoveryPhase.baseline) {
      throw StateError('Event start can only be marked after a baseline.');
    }
    eventStartedAt = now ?? DateTime.now();
    phase = DiscoveryPhase.event;
  }

  void markEventEnd({DateTime? now}) {
    if (phase != DiscoveryPhase.event) {
      throw StateError('Event end can only be marked while the event is active.');
    }
    eventEndedAt = now ?? DateTime.now();
    phase = DiscoveryPhase.after;
  }

  void observe(CanFrame frame) {
    final phaseIndex = switch (phase) {
      DiscoveryPhase.baseline => 0,
      DiscoveryPhase.event => 1,
      DiscoveryPhase.after => 2,
      _ => -1,
    };
    if (phaseIndex < 0 || frame.remote || frame.data.isEmpty) return;
    final key = _SignalKey(frame.channel, frame.id, frame.extended, frame.data.length);
    final phases = _counts.putIfAbsent(
      key,
      () => List<_BitCounts>.generate(3, (_) => _BitCounts(frame.data.length * 8)),
    );
    phases[phaseIndex].add(frame.data);
  }

  List<SignalCandidate> finish() {
    if (phase != DiscoveryPhase.after) {
      candidates = const <SignalCandidate>[];
      phase = DiscoveryPhase.complete;
      return candidates;
    }
    final found = <SignalCandidate>[];
    for (final entry in _counts.entries) {
      final baseline = entry.value[0];
      final event = entry.value[1];
      final after = entry.value[2];
      if (baseline.frames < 3 || event.frames < 3 || after.frames < 3) continue;
      for (var bit = 0; bit < entry.key.length * 8; bit++) {
        final beforeProbability = baseline.probability(bit);
        final eventProbability = event.probability(bit);
        final afterProbability = after.probability(bit);
        final eventChange = (eventProbability -
                ((beforeProbability + afterProbability) / 2))
            .abs();
        final failureToRestore = (beforeProbability - afterProbability).abs();
        if (eventChange < 0.65 || failureToRestore > 0.20) continue;
        found.add(
          SignalCandidate(
            channel: entry.key.channel,
            id: entry.key.id,
            extended: entry.key.extended,
            byteIndex: bit ~/ 8,
            bitIndex: bit % 8,
            baselineProbability: beforeProbability,
            eventProbability: eventProbability,
            afterProbability: afterProbability,
            score: eventChange - failureToRestore / 2,
          ),
        );
      }
    }
    found.sort((a, b) => b.score.compareTo(a.score));
    candidates = List<SignalCandidate>.unmodifiable(found);
    phase = DiscoveryPhase.complete;
    return candidates;
  }
}
