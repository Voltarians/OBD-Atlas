import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/core/can_frame.dart';
import 'package:obd_atlas/core/gen1_bicm_125k.dart';

CanFrame frame(int id, List<int> data) => CanFrame(
      timestamp: DateTime.utc(2026, 9, 13),
      id: id,
      data: data,
      channel: 1,
      bus: 'bicm125',
    );

void main() {
  const decoder = Gen1Bicm125kDecoder();

  test('recognizes conservative Gen-1 internal BICM ranges', () {
    expect(decoder.isVoltageFrame(frame(0x460, [0, 0])), isTrue);
    expect(decoder.isVoltageFrame(frame(0x47F, [0, 0])), isTrue);
    expect(decoder.isVoltageFrame(frame(0x45F, [0, 0])), isFalse);
    expect(decoder.isTemperatureFrame(frame(0x7E0, [0, 0])), isTrue);
    expect(decoder.isTemperatureFrame(frame(0x7EF, [0, 0])), isTrue);
    expect(decoder.isTemperatureFrame(frame(0x7F0, [0, 0])), isFalse);
  });

  test('maps voltage CAN IDs to Yasko interleaved sequence slots', () {
    expect(decoder.voltageSequenceSlot(0x460), 0);
    expect(decoder.voltageSequenceSlot(0x461), 2);
    expect(decoder.voltageSequenceSlot(0x46F), 30);
    expect(decoder.voltageSequenceSlot(0x470), 1);
    expect(decoder.voltageSequenceSlot(0x471), 3);
    expect(decoder.voltageSequenceSlot(0x47F), 31);
  });

  test('decodes 12-bit cell voltage pairs with 1.25 mV scale', () {
    // 0xBB8 = 3000 -> 3.750 V
    // 0xC80 = 3200 -> 4.000 V
    final decoded = decoder.decodeVoltage(frame(0x460, [0x0B, 0xB8, 0x0C, 0x80]));

    expect(decoded, isNotNull);
    expect(decoded!.sequenceSlot, 0);
    expect(decoded.rawValues, [3000, 3200]);
    expect(decoded.volts[0], closeTo(3.75, 0.000001));
    expect(decoded.volts[1], closeTo(4.00, 0.000001));
  });

  test('ignores upper nibble while decoding voltage and temperature values', () {
    final voltage = decoder.decodeVoltage(frame(0x460, [0xAB, 0xB8]));
    expect(voltage!.rawValues.single, 3000);

    // Raw 2915 (0xB63) gives about 25 C using Yasko's formula.
    final temperature = decoder.decodeTemperature(frame(0x7E0, [0xAB, 0x63]));
    expect(temperature, isNotNull);
    expect(temperature!.rawValue, 2915);
    expect(temperature.celsius, closeTo(25.0, 0.1));
  });

  test('uses second byte pair for Yasko temperature IDs 0x7E2/5/9', () {
    final temperature = decoder.decodeTemperature(
      frame(0x7E2, [0x00, 0x00, 0x0B, 0x63]),
    );
    expect(temperature, isNotNull);
    expect(temperature!.temperatureIndex, 2);
    expect(temperature.rawValue, 2915);
  });

  test('does not claim unsupported temperature IDs', () {
    expect(decoder.decodeTemperature(frame(0x7E3, [0, 0, 0, 0])), isNull);
  });

  test('collector reconstructs a complete 96-value pack in reverse order', () {
    final state = Gen1Bicm125kState();

    // 24 frames x 4 values = 96 values. Use the first 12 even and first 12 odd
    // sequence slots to exercise ordering independent of arrival order.
    final ids = <int>[
      for (var i = 0; i < 12; i++) 0x460 + i,
      for (var i = 0; i < 12; i++) 0x470 + i,
    ]..sort((a, b) => b.compareTo(a));

    for (final id in ids) {
      state.ingest(frame(id, [0x0B, 0xB8, 0x0B, 0xB8, 0x0B, 0xB8, 0x0B, 0xB8]));
    }

    expect(state.observedVoltageValueCount, 96);
    expect(state.cellsVolts, isNotNull);
    expect(state.cellsVolts!.length, 96);
    expect(state.cellsVolts!.every((v) => (v - 3.75).abs() < 0.000001), isTrue);
  });
}
