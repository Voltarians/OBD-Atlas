import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/adapters/linux_obdlink_mx_adapter.dart';

void main() {
  group('LinuxObdlinkMxAdapter monitor parser', () {
    test('parses an 11-bit CAN frame with displayed DLC', () {
      final frame = LinuxObdlinkMxAdapter.parseMonitorLine(
        '7E8 8 06 41 00 BE 3E B8 13 00',
        channel: 3,
      );

      expect(frame, isNotNull);
      expect(frame!.id, 0x7E8);
      expect(frame.channel, 3);
      expect(frame.extended, isFalse);
      expect(frame.data, <int>[0x06, 0x41, 0x00, 0xBE, 0x3E, 0xB8, 0x13, 0x00]);
    });

    test('parses a contiguous 29-bit CAN identifier', () {
      final frame = LinuxObdlinkMxAdapter.parseMonitorLine(
        '18DAF110 3 02 3E 00',
      );

      expect(frame, isNotNull);
      expect(frame!.id, 0x18DAF110);
      expect(frame.extended, isTrue);
      expect(frame.data, <int>[0x02, 0x3E, 0x00]);
    });

    test('parses a spaced 29-bit CAN identifier', () {
      final frame = LinuxObdlinkMxAdapter.parseMonitorLine(
        '18 DA F1 10 3 02 3E 00',
        channel: 5,
      );

      expect(frame, isNotNull);
      expect(frame!.id, 0x18DAF110);
      expect(frame.channel, 5);
      expect(frame.extended, isTrue);
    });

    test('parses an STMA fast-mode 11-bit frame without spaces or DLC', () {
      final frame = LinuxObdlinkMxAdapter.parseMonitorLine(
        '0C1AABBCCDDEEFF0011',
        channel: 2,
      );

      expect(frame, isNotNull);
      expect(frame!.id, 0x0C1);
      expect(frame.channel, 2);
      expect(frame.extended, isFalse);
      expect(
        frame.data,
        <int>[0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF, 0x00, 0x11],
      );
    });

    test('parses an STMA fast-mode 29-bit frame without spaces or DLC', () {
      final frame = LinuxObdlinkMxAdapter.parseMonitorLine(
        '18DAF110023E00',
      );

      expect(frame, isNotNull);
      expect(frame!.id, 0x18DAF110);
      expect(frame.extended, isTrue);
      expect(frame.data, <int>[0x02, 0x3E, 0x00]);
    });

    test('rejects status, truncated, and invalid channel lines', () {
      expect(LinuxObdlinkMxAdapter.parseMonitorLine('SEARCHING...'), isNull);
      expect(LinuxObdlinkMxAdapter.parseMonitorLine('7E8 8 01 02'), isNull);
      expect(
        LinuxObdlinkMxAdapter.parseMonitorLine('7E8 1 00', channel: 0),
        isNull,
      );
    });
  });
}
