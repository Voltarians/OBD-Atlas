import 'can_frame.dart';

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
    if (didContext != did ||
        payload.length < 2 ||
        payload[0] != dynamicPacketId) {
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
    if (_equals(compressed, const <int>[0x68])) {
      return Gen1Hpcm2SequenceClassification.stableHvOff;
    }
    if (_equals(compressed, const <int>[0x6B])) {
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

/// Stateful live tracker for the HPCM2 dynamic packet definition and stream.
///
/// DPID 0xFE is reusable. The tracker therefore fails closed: a 0x5EC FE xx
/// frame is decoded only after the same Atlas channel has shown a successful
/// single-frame 0x2C definition of 0xFE -> 0x430E.
class Gen1Hpcm2ContactorLiveTracker {
  static const int requestCanId = 0x7E4;
  static const int responseCanId = 0x7EC;

  final Map<int, Map<int, int>> _definitionsByChannel = <int, Map<int, int>>{};
  final Map<int, _PendingDynamicDefinition> _pendingByChannel =
      <int, _PendingDynamicDefinition>{};
  final List<int> _compressedHistory = <int>[];

  Gen1Hpcm2ContactorSample? currentSample;
  DateTime? lastSampleTimestamp;
  int? activeChannel;

  bool get hasConfirmedContactorContext => _definitionsByChannel.values.any(
        (definitions) =>
            definitions[Gen1Hpcm2ContactorStateDecoder.dynamicPacketId] ==
            Gen1Hpcm2ContactorStateDecoder.did,
      );

  Gen1Hpcm2SequenceClassification get sequenceClassification =>
      Gen1Hpcm2ContactorStateDecoder.classifyRawStates(_compressedHistory);

  List<int> get compressedHistory => List<int>.unmodifiable(_compressedHistory);

  void reset() {
    _definitionsByChannel.clear();
    _pendingByChannel.clear();
    _compressedHistory.clear();
    currentSample = null;
    lastSampleTimestamp = null;
    activeChannel = null;
  }

  void observe(CanFrame frame) {
    if (frame.id == requestCanId) {
      final payload = _singleFramePayload(frame.data);
      if (payload != null && payload.length >= 4 && payload[0] == 0x2C) {
        _pendingByChannel[frame.channel] = _PendingDynamicDefinition(
          dpid: payload[1],
          did: (payload[2] << 8) | payload[3],
        );
      }
      return;
    }

    if (frame.id == responseCanId) {
      final payload = _singleFramePayload(frame.data);
      final pending = _pendingByChannel[frame.channel];
      if (payload == null || pending == null) return;
      if (payload.length >= 2 &&
          payload[0] == 0x6C &&
          payload[1] == pending.dpid) {
        _definitionsByChannel
            .putIfAbsent(frame.channel, () => <int, int>{})[pending.dpid] =
            pending.did;
        _pendingByChannel.remove(frame.channel);
      } else if (payload.length >= 3 &&
          payload[0] == 0x7F &&
          payload[1] == 0x2C) {
        _pendingByChannel.remove(frame.channel);
      }
      return;
    }

    if (frame.id != Gen1Hpcm2ContactorStateDecoder.dynamicResponseCanId ||
        frame.data.length < 2) {
      return;
    }

    final dpid = frame.data[0];
    final didContext = _definitionsByChannel[frame.channel]?[dpid];
    if (didContext != Gen1Hpcm2ContactorStateDecoder.did) return;

    final sample = Gen1Hpcm2ContactorStateDecoder.decodeDynamicPayload(
      didContext: didContext!,
      payload: frame.data,
    );
    if (sample == null) return;

    currentSample = sample;
    lastSampleTimestamp = frame.timestamp;
    activeChannel = frame.channel;
    if (_compressedHistory.isEmpty ||
        _compressedHistory.last != sample.rawState) {
      _compressedHistory.add(sample.rawState);
      if (_compressedHistory.length > 16) {
        _compressedHistory.removeAt(0);
      }
    }
  }

  static List<int>? _singleFramePayload(List<int> data) {
    if (data.isEmpty || (data[0] >> 4) != 0) return null;
    final length = data[0] & 0x0F;
    if (length == 0 || length > 7 || data.length < length + 1) return null;
    return data.sublist(1, length + 1);
  }
}

class _PendingDynamicDefinition {
  const _PendingDynamicDefinition({required this.dpid, required this.did});

  final int dpid;
  final int did;
}
