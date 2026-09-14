import 'gen1_hpcm2_contactor_state.dart';

enum Gen1PrechargeDiagnosticResult {
  successfulStartup,
  noMainContactorEngagement,
  stalledAfterFirstMainContactor,
  stalledInPrecharge,
  prechargeVoltageFailedToRise,
  prechargeVoltageDidNotConverge,
  unexpectedOrIncompleteSequence,
}

enum Gen1PrechargeVoltageResult {
  notEvaluated,
  insufficientData,
  failedToRise,
  roseButDidNotConverge,
  converged,
}

class Gen1TimedHpcm2State {
  const Gen1TimedHpcm2State({
    required this.timestamp,
    required this.rawState,
  });

  final Duration timestamp;
  final int rawState;
}

/// Decoded high-voltage measurements used by the contactor/precharge analyzer.
///
/// [packVoltage] should come from the Atlas-confirmed Gen-1 pack-voltage signal.
/// [dcLinkVoltage] remains an explicitly supplied decoded value so the analyzer
/// does not guess a CAN ID or scale before Atlas has vehicle-confirmed it.
class Gen1TimedPrechargeVoltage {
  const Gen1TimedPrechargeVoltage({
    required this.timestamp,
    required this.packVoltage,
    required this.dcLinkVoltage,
  });

  final Duration timestamp;
  final double packVoltage;
  final double dcLinkVoltage;
}

class Gen1PrechargeVoltageAssessment {
  const Gen1PrechargeVoltageAssessment({
    required this.result,
    required this.sampleCount,
    this.prechargeStartDcLinkVoltage,
    this.maximumDcLinkVoltage,
    this.maximumPackVoltage,
    this.bestConvergenceRatio,
  });

  final Gen1PrechargeVoltageResult result;
  final int sampleCount;
  final double? prechargeStartDcLinkVoltage;
  final double? maximumDcLinkVoltage;
  final double? maximumPackVoltage;
  final double? bestConvergenceRatio;
}

class Gen1PrechargeDiagnosticReport {
  const Gen1PrechargeDiagnosticReport({
    required this.result,
    required this.sequence,
    required this.reachedFirstMainContactor,
    required this.reachedPrecharge,
    required this.reachedHvBusEstablished,
    required this.voltageAssessment,
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
  final Gen1PrechargeVoltageAssessment voltageAssessment;

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

/// Interprets the vehicle-confirmed HPCM2 DID 0x430E state sequence and, when
/// available, correlates it with pack/DC-link voltage behavior.
///
/// The analyzer intentionally does not identify the individual positive and
/// negative main contactors. Current vehicle evidence proves the phase order,
/// but not which of bits 0 and 1 maps to positive versus negative.
class Gen1PrechargeDiagnosticAnalyzer {
  static Gen1PrechargeDiagnosticReport analyze(
    Iterable<Gen1TimedHpcm2State> samples, {
    Iterable<Gen1TimedPrechargeVoltage> voltageSamples = const [],
    double minimumRiseVolts = 20.0,
    double convergenceRatio = 0.90,
  }) {
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

    final voltageAssessment = _assessVoltage(
      voltageSamples,
      prechargeAt: precharge?.timestamp,
      establishedAt: established?.timestamp,
      minimumRiseVolts: minimumRiseVolts,
      convergenceRatio: convergenceRatio,
    );

    final stateResult = switch (classification) {
      Gen1Hpcm2SequenceClassification.successfulStartup =>
        Gen1PrechargeDiagnosticResult.successfulStartup,
      _ => _classifyFailure(rawSequence),
    };

    final result = _combineStateAndVoltage(
      stateResult,
      voltageAssessment,
      reachedPrecharge: precharge != null,
    );

    return Gen1PrechargeDiagnosticReport(
      result: result,
      sequence: List.unmodifiable(rawSequence),
      reachedFirstMainContactor: firstMain != null,
      reachedPrecharge: precharge != null,
      reachedHvBusEstablished: established != null,
      firstMainContactorAt: firstMain?.timestamp,
      prechargeAt: precharge?.timestamp,
      hvBusEstablishedAt: established?.timestamp,
      voltageAssessment: voltageAssessment,
    );
  }

  static Gen1PrechargeDiagnosticResult _combineStateAndVoltage(
    Gen1PrechargeDiagnosticResult stateResult,
    Gen1PrechargeVoltageAssessment voltageAssessment, {
    required bool reachedPrecharge,
  }) {
    if (!reachedPrecharge) return stateResult;

    switch (voltageAssessment.result) {
      case Gen1PrechargeVoltageResult.failedToRise:
        return Gen1PrechargeDiagnosticResult.prechargeVoltageFailedToRise;
      case Gen1PrechargeVoltageResult.roseButDidNotConverge:
        return Gen1PrechargeDiagnosticResult.prechargeVoltageDidNotConverge;
      case Gen1PrechargeVoltageResult.insufficientData:
      case Gen1PrechargeVoltageResult.notEvaluated:
      case Gen1PrechargeVoltageResult.converged:
        return stateResult;
    }
  }

  static Gen1PrechargeVoltageAssessment _assessVoltage(
    Iterable<Gen1TimedPrechargeVoltage> samples, {
    required Duration? prechargeAt,
    required Duration? establishedAt,
    required double minimumRiseVolts,
    required double convergenceRatio,
  }) {
    if (prechargeAt == null) {
      return const Gen1PrechargeVoltageAssessment(
        result: Gen1PrechargeVoltageResult.notEvaluated,
        sampleCount: 0,
      );
    }

    final ordered = samples
        .where(
          (sample) =>
              sample.timestamp >= prechargeAt &&
              (establishedAt == null || sample.timestamp <= establishedAt),
        )
        .toList()
      ..sort((a, b) => a.timestamp.compareTo(b.timestamp));

    if (ordered.length < 2) {
      return Gen1PrechargeVoltageAssessment(
        result: Gen1PrechargeVoltageResult.insufficientData,
        sampleCount: ordered.length,
      );
    }

    final startDc = ordered.first.dcLinkVoltage;
    var maxDc = ordered.first.dcLinkVoltage;
    var maxPack = ordered.first.packVoltage;
    var bestRatio = _safeRatio(ordered.first.dcLinkVoltage, ordered.first.packVoltage);

    for (final sample in ordered.skip(1)) {
      if (sample.dcLinkVoltage > maxDc) maxDc = sample.dcLinkVoltage;
      if (sample.packVoltage > maxPack) maxPack = sample.packVoltage;
      final ratio = _safeRatio(sample.dcLinkVoltage, sample.packVoltage);
      if (ratio > bestRatio) bestRatio = ratio;
    }

    final rise = maxDc - startDc;
    final result = bestRatio >= convergenceRatio
        ? Gen1PrechargeVoltageResult.converged
        : rise < minimumRiseVolts
            ? Gen1PrechargeVoltageResult.failedToRise
            : Gen1PrechargeVoltageResult.roseButDidNotConverge;

    return Gen1PrechargeVoltageAssessment(
      result: result,
      sampleCount: ordered.length,
      prechargeStartDcLinkVoltage: startDc,
      maximumDcLinkVoltage: maxDc,
      maximumPackVoltage: maxPack,
      bestConvergenceRatio: bestRatio,
    );
  }

  static double _safeRatio(double dcLinkVoltage, double packVoltage) {
    if (!dcLinkVoltage.isFinite || !packVoltage.isFinite || packVoltage <= 0) {
      return 0.0;
    }
    return dcLinkVoltage / packVoltage;
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
