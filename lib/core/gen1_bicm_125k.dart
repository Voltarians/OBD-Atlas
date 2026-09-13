import 'can_frame.dart';

/// Passive Chevrolet Volt / Opel Ampera Gen-1 internal BECM<->BICM decoder.
///
/// Source lineage: yasko-pv/gw-ev (2021), cross-referenced against the
/// Tom-evnut/AmperaBattery community material. This decoder is deliberately
/// EXPERIMENTAL until Atlas captures from a known Gen-1 pack verify the mapping.
///
/// Important: this file only decodes observed traffic. It does not transmit
/// BECM master/query/control frames.
class Gen1Bicm125kDecoder {
  const Gen1Bicm125kDecoder();

  static const int bitrateKbps = 125;
  static const int expectedCellCount = 96;
  static const int expectedTemperatureSlots = 16;

  static const String status = 'experimental';
  static const String primarySource = 'yasko-pv/gw-ev';

  /// Yasko's decoder treats 0x4xx frames as voltage traffic, but its slot
  /// arithmetic is based at 0x460. Atlas intentionally narrows the accepted
  /// range to 0x460..0x47F until captures prove additional IDs are valid.
  bool isVoltageFrame(CanFrame frame) =>
      !frame.extended && frame.id >= 0x460 && frame.id <= 0x47F;

  bool isTemperatureFrame(CanFrame frame) =>
      !frame.extended && frame.id >= 0x7E0 && frame.id <= 0x7EF;

  /// Maps arbitration IDs to Yasko's interleaved logical frame order:
  /// 0x460..0x46F -> slots 0,2,4...30
  /// 0x470..0x47F -> slots 1,3,5...31
  int? voltageSequenceSlot(int canId) {
    if (canId < 0x460 || canId > 0x47F) return null;
    final relative = canId - 0x460;
    return relative >= 16 ? (relative - 16) * 2 + 1 : relative * 2;
  }

  Gen1BicmVoltageFrame? decodeVoltage(CanFrame frame) {
    if (!isVoltageFrame(frame) || frame.data.length < 2) return null;
    final slot = voltageSequenceSlot(frame.id)!;
    final values = <double>[];
    final rawValues = <int>[];

    for (var offset = 0; offset + 1 < frame.data.length; offset += 2) {
      final raw = ((frame.data[offset] & 0x0F) << 8) | frame.data[offset + 1];
      rawValues.add(raw);
      values.add(raw * 0.00125);
    }

    return Gen1BicmVoltageFrame(
      canId: frame.id,
      sequenceSlot: slot,
      rawValues: List.unmodifiable(rawValues),
      volts: List.unmodifiable(values),
    );
  }

  /// Temperature extraction follows gw-ev.c exactly. Only eight of the
  /// sixteen 0x7Ex slots are decoded there, with some values stored in bytes
  /// 0..1 and others in bytes 2..3.
  Gen1BicmTemperature? decodeTemperature(CanFrame frame) {
    if (!isTemperatureFrame(frame)) return null;
    final index = frame.id - 0x7E0;

    final pairIndex = switch (index) {
      0 || 1 || 8 || 12 || 13 => 0,
      2 || 5 || 9 => 1,
      _ => null,
    };
    if (pairIndex == null) return null;

    final offset = pairIndex * 2;
    if (frame.data.length <= offset + 1) return null;

    final raw = ((frame.data[offset] & 0x0F) << 8) | frame.data[offset + 1];
    final celsius = 110.7 - raw * 0.0294;

    return Gen1BicmTemperature(
      canId: frame.id,
      temperatureIndex: index,
      rawValue: raw,
      celsius: celsius,
    );
  }
}

class Gen1BicmVoltageFrame {
  const Gen1BicmVoltageFrame({
    required this.canId,
    required this.sequenceSlot,
    required this.rawValues,
    required this.volts,
  });

  final int canId;
  final int sequenceSlot;
  final List<int> rawValues;
  final List<double> volts;
}

class Gen1BicmTemperature {
  const Gen1BicmTemperature({
    required this.canId,
    required this.temperatureIndex,
    required this.rawValue,
    required this.celsius,
  });

  final int canId;
  final int temperatureIndex;
  final int rawValue;
  final double celsius;
}

/// Stateful passive collector that reconstructs Yasko's 96-value array once
/// a complete set of voltage frame payloads has been observed.
class Gen1Bicm125kState {
  Gen1Bicm125kState({this.decoder = const Gen1Bicm125kDecoder()});

  final Gen1Bicm125kDecoder decoder;
  final Map<int, Gen1BicmVoltageFrame> _voltageFramesBySlot = {};
  final Map<int, Gen1BicmTemperature> temperatures = {};

  int get observedVoltageValueCount => _voltageFramesBySlot.values.fold(
        0,
        (sum, frame) => sum + frame.volts.length,
      );

  void ingest(CanFrame frame) {
    final voltage = decoder.decodeVoltage(frame);
    if (voltage != null) {
      _voltageFramesBySlot[voltage.sequenceSlot] = voltage;
      return;
    }

    final temperature = decoder.decodeTemperature(frame);
    if (temperature != null) {
      temperatures[temperature.temperatureIndex] = temperature;
    }
  }

  /// Returns cell 1..96 in the ordering used by gw-ev.c, or null until exactly
  /// 96 values are available. Yasko reverses the concatenated sequence before
  /// exposing the cell array; Atlas preserves that behavior for validation.
  List<double>? get cellsVolts {
    final slots = _voltageFramesBySlot.keys.toList()..sort();
    final sequence = <double>[];
    for (final slot in slots) {
      sequence.addAll(_voltageFramesBySlot[slot]!.volts);
    }
    if (sequence.length != Gen1Bicm125kDecoder.expectedCellCount) return null;
    return List.unmodifiable(sequence.reversed);
  }

  void clear() {
    _voltageFramesBySlot.clear();
    temperatures.clear();
  }
}
