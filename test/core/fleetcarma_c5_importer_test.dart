import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/core/fleetcarma_c5_importer.dart';

void main() {
  test('decodes FleetCarma configured ID, CAN frame, and GPS TLVs', () {
    final bytes = Uint8List.fromList([
      0x01, 0x05,
      0x01, 0xED, 0x01, 0x10, 0x00,
      0x05, 0x10,
      0x01, 0xED, 0x01, 0x03,
      0x40, 0xE2, 0x01, 0x00,
      0x11, 0x22, 0x33, 0x00, 0x00, 0x00, 0x00, 0x00,
      0x24, 0x0C,
      0x50, 0xC3, 0x00, 0x00,
      0x47, 0x50, 0x56, 0x54, 0x47, 0x2C, 0x31, 0x2E,
    ]);

    final result = const FleetCarmaC5Importer().decode(bytes);

    expect(result.malformedTail, isFalse);
    expect(result.configuredIds, hasLength(1));
    expect(result.configuredIds.single.bus, 1);
    expect(result.configuredIds.single.canId, 0x1ED);

    expect(result.canRecords, hasLength(1));
    final frame = result.canRecords.single;
    expect(frame.loggerTimestampMs, 123456);
    expect(frame.bus, 1);
    expect(frame.canId, 0x1ED);
    expect(frame.data, [0x11, 0x22, 0x33]);
    expect(frame.toRelativeCandump(), '(123.456000) can0 1ED#112233');

    expect(result.gpsRecords, hasLength(1));
    expect(result.gpsRecords.single.loggerTimestampMs, 50000);
    expect(result.gpsRecords.single.sentence, 'GPVTG,1.');
  });

  test('preserves valid records before a truncated tail', () {
    final bytes = Uint8List.fromList([
      0x05, 0x10,
      0x02, 0x10, 0x02, 0x01,
      0xE8, 0x03, 0x00, 0x00,
      0xAA, 0, 0, 0, 0, 0, 0, 0,
      0x24, 0x20, 0x01, 0x02,
    ]);

    final result = const FleetCarmaC5Importer().decode(bytes);

    expect(result.canRecords, hasLength(1));
    expect(result.canRecords.single.bus, 2);
    expect(result.canRecords.single.canId, 0x210);
    expect(result.malformedTail, isTrue);
  });

  test('maps logger time to Atlas CanFrame with an explicit anchor', () {
    final bytes = Uint8List.fromList([
      0x05, 0x10,
      0x01, 0x06, 0x02, 0x01,
      0xD0, 0x07, 0x00, 0x00,
      0x55, 0, 0, 0, 0, 0, 0, 0,
    ]);

    final record =
        const FleetCarmaC5Importer().decode(bytes).canRecords.single;
    final anchor = DateTime.utc(2016, 1, 7, 12);
    final frame = record.toCanFrame(
      anchorTime: anchor,
      anchorLoggerTimestampMs: 1000,
    );

    expect(frame.timestamp, DateTime.utc(2016, 1, 7, 12, 0, 1));
    expect(frame.channel, 1);
    expect(frame.bus, 'can0');
    expect(frame.id, 0x206);
  });
}
