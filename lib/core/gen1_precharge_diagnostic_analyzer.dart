import 'gen1_hpcm2_contactor_state.dart';

enum Gen1PrechargeDiagnosticResult {
  successfulStartup,
  noMainContactorEngagement,
  stalledAfterFirstMainContactor,
  stalledInPrecharge,
  unexpectedOrIncompleteSequence,
}

class Gen1TimedHpcm2State {
  const Gen1TimedHpcm2State({
    required this.timestamp,
    required this.rawState,
  });

  final Duration timestamp;
  final int rawState;
}

class Gen1PrechargeDiagnosticReport {
  const Gen1PrechargeDiagnosticReport({
    required this.result,
    required this.sequence,
    required this.reachedFirstMainContactor,
    required this.reachedPrecharge,
    required this.reachedHvBusEstablished,
    this.firstMainContactorAt,
    this.prechargeAt,
    this.hvBusEstablishedAt,
  });

  final Gen1PrechargeDiagnosticResult result;
  final List<int> sequence;
  final bool reachedFirstMainContactor;
  final bool reachedPrecharge;
  final bool reachedHvBusEstablished;
  final Duration? firstMainContactorAt;
  final Duration? prechargeAt;
  final Duration? hvBusEstablishedAt;

  Duration? get firstMainToPrecharge {
    final a = firstMainContactorAt;
    final b = prechargeAt;
    if (a == null || b == null) return null;
    return b - a;
  }

  Duration? get prechargeToHvBusEstablished {
    final a = prechargeAt;
    final b = hvBusEstablishedAt;
    if (a == null || b == null) return null;
    return b - a;
  }
}

/// Interprets the vehicle-confirmed HPCM2 DID 0x430E state sequence.
///
/// The analyzer intentionally does not identify the individual positive and
/// negative main contactors. Current vehicle evidence proves the phase order,
/// but not which of bits 0 and 1 maps to positive versus negative.
class Gen1PrechargeDiagnosticAnalyzer {
  static Gen1PrechargeDiagnosticReport analyze(
    Iterable<Gen1TimedHpcm2State> samples,
  ) {
    final ordered = samples.toList()
      ..sort((a, b) => a.timestamp.compareTo(b.timestamp));

    final compressed = <Gen1TimedHpcm2State>[];
    for (final sample in ordered) {
      final raw = sample.rawState & 0xFF;
      if (compressed.isEmpty || compressed.last.rawState != raw) {
        compressed.add(
          Gen1TimedHpcm2State(timestamp: sample.timestamp, rawState: raw),
        );
      }
    }

    final rawSequence = compressed.map((sample) => sample.rawState).toList();
    final firstMain = _first(compressed, 0x6A);
    final precharge = _first(compressed, 0x6F);
    final established = _first(compressed, 0x6B);

    final classification =
        Gen1Hpcm2ContactorStateDecoder.classifyRawStates(rawSequence);

    final result = switch (classification) {
      Gen1Hpcm2SequenceClassification.successfulStartup =>
        Gen1PrechargeDiagnosticResult.successfulStartup,
      _ => _classifyFailure(rawSequence),
    };

    return Gen1PrechargeDiagnosticReport(
      result: result,
      sequence: List.unmodifiable(rawSequence),
      reachedFirstMainContactor: firstMain != null,
      reachedPrecharge: precharge != null,
      reachedHvBusEstablished: established != null,
      firstMainContactorAt: firstMain?.timestamp,
      prechargeAt: precharge?.timestamp,
      hvBusEstablishedAt: established?.timestamp,
    );
  }

  static Gen1PrechargeDiagnosticResult _classifyFailure(List<int> sequence) {
    if (sequence.isEmpty) {
      return Gen1PrechargeDiagnosticResult.unexpectedOrIncompleteSequence;
    }

    final startsOff = sequence.first == 0x68;
    if (startsOff && !sequence.contains(0x6A)) {
      return Gen1PrechargeDiagnosticResult.noMainContactorEngagement;
    }
    if (startsOff && sequence.contains(0x6A) && !sequence.contains(0x6F)) {
      return Gen1PrechargeDiagnosticResult.stalledAfterFirstMainContactor;
    }
    if (startsOff && sequence.contains(0x6F) && !sequence.contains(0x6B)) {
      return Gen1PrechargeDiagnosticResult.stalledInPrecharge;
    }

    return Gen1PrechargeDiagnosticResult.unexpectedOrIncompleteSequence;
  }

  static Gen1TimedHpcm2State? _first(
    List<Gen1TimedHpcm2State> samples,
    int rawState,
  ) {
    for (final sample in samples) {
      if (sample.rawState == rawState) return sample;
    }
    return null;
  }
}
