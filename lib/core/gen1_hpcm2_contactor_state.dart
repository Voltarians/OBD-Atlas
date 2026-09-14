/// Vehicle-observed Gen-1 Chevrolet Volt HPCM2 contactor/precharge state.
///
/// Controlled GDS2 + passive Atlas captures on 2026-09-14 established that
/// HPCM2 parameter 0x430E can be streamed as dynamic packet 0xFE on CAN 0x5EC.
///
/// This decoder deliberately does not name bit 0 vs bit 1 as positive/negative
/// until an independent controlled test separates those two contactor bits.
enum Gen1Hpcm2HvPhase {
  hvOff,
  firstMainContactorEngaged,
  prechargeActive,
  hvBusEstablished,
  unknown,
}

enum Gen1Hpcm2SequenceClassification {
  successfulStartup,
  normalShutdown,
  stableHvOff,
  stableHvEstablished,
  unknownOrIncomplete,
}

class Gen1Hpcm2ContactorSample {
  const Gen1Hpcm2ContactorSample({
    required this.rawState,
    required this.phase,
  });

  final int rawState;
  final Gen1Hpcm2HvPhase phase;

  bool get mainContactorBit0 => (rawState & 0x01) != 0;
  bool get mainContactorBit1 => (rawState & 0x02) != 0;
  bool get prechargeBit2 => (rawState & 0x04) != 0;

  String get rawHex =>
      '0x${rawState.toRadixString(16).toUpperCase().padLeft(2, '0')}';
}

class Gen1Hpcm2ContactorStateDecoder {
  static const int did = 0x430E;
  static const int dynamicPacketId = 0xFE;
  static const int dynamicResponseCanId = 0x5EC;

  static Gen1Hpcm2ContactorSample? decodeDynamicPayload({
    required int didContext,
    required List<int> payload,
  }) {
    if (didContext != did || payload.length < 2 || payload[0] != dynamicPacketId) {
      return null;
    }

    final raw = payload[1] & 0xFF;
    final phase = switch (raw) {
      0x68 => Gen1Hpcm2HvPhase.hvOff,
      0x6A => Gen1Hpcm2HvPhase.firstMainContactorEngaged,
      0x6F => Gen1Hpcm2HvPhase.prechargeActive,
      0x6B => Gen1Hpcm2HvPhase.hvBusEstablished,
      _ => Gen1Hpcm2HvPhase.unknown,
    };
    return Gen1Hpcm2ContactorSample(rawState: raw, phase: phase);
  }

  static Gen1Hpcm2SequenceClassification classifyRawStates(
    Iterable<int> rawStates,
  ) {
    final compressed = <int>[];
    for (final value in rawStates) {
      final raw = value & 0xFF;
      if (compressed.isEmpty || compressed.last != raw) {
        compressed.add(raw);
      }
    }

    if (_equals(compressed, const <int>[0x68, 0x6A, 0x6F, 0x6B])) {
      return Gen1Hpcm2SequenceClassification.successfulStartup;
    }
    if (_equals(compressed, const <int>[0x6B, 0x6A, 0x68])) {
      return Gen1Hpcm2SequenceClassification.normalShutdown;
    }
    if (compressed.isNotEmpty &&
        compressed.first == 0x68 &&
        compressed.last == 0x68) {
      return Gen1Hpcm2SequenceClassification.stableHvOff;
    }
    if (compressed.isNotEmpty &&
        compressed.first == 0x6B &&
        compressed.last == 0x6B) {
      return Gen1Hpcm2SequenceClassification.stableHvEstablished;
    }
    return Gen1Hpcm2SequenceClassification.unknownOrIncomplete;
  }

  static bool _equals(List<int> a, List<int> b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }
}
