import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/adapters/linux_obdlink_mx_adapter.dart';

void main() {
  group('OBDLink MX+ CAN bus presets', () {
    test('selects documented raw protocols for HS-CAN and SWCAN', () {
      expect(ObdlinkMxCanBus.highSpeedCan.protocolNumber, 31);
      expect(ObdlinkMxCanBus.singleWireCan.protocolNumber, 61);
      expect(ObdlinkMxCanBus.singleWireCan.displayName, contains('pin 1'));
      expect(ObdlinkMxCanBus.singleWireCan.displayName, contains('33.3'));
      expect(
        LinuxObdlinkMxAdapter.monitorSetupCommands(
          ObdlinkMxCanBus.highSpeedCan,
        ).take(2),
        <String>['STP 31', 'STCMM 0'],
      );
      expect(
        LinuxObdlinkMxAdapter.monitorSetupCommands(
          ObdlinkMxCanBus.singleWireCan,
        ).take(3),
        <String>['STP 61', 'STCSWM 3', 'STCMM 0'],
      );
    });

    test('uses STFPA 000,000 for unrestricted HS-CAN full-bus monitoring', () {
      final commands = LinuxObdlinkMxAdapter.monitorSetupCommands(
        ObdlinkMxCanBus.highSpeedCan,
      );

      expect(commands, contains('STFAC'));
      expect(commands, contains('STFPA 000,000'));
      expect(
        commands.where((command) => command.startsWith('STFPA ')).length,
        1,
      );
    });

    test('programs exact HS-CAN pass filters within the MX+ production envelope', () {
      final commands = LinuxObdlinkMxAdapter.monitorSetupCommands(
        ObdlinkMxCanBus.highSpeedCan,
        filterIds: <int>[0x0C1, 0x1E5, 0x0D1],
      );

      expect(commands, contains('STFAC'));
      expect(commands, contains('STFPA 0C1,7FF'));
      expect(commands, contains('STFPA 0D1,7FF'));
      expect(commands, contains('STFPA 1E5,7FF'));
      expect(commands, isNot(contains('STFPA 000,000')));
    });

    test('rejects more than 16 MX+ exact filters', () {
      expect(
        () => LinuxObdlinkMxAdapter.monitorSetupCommands(
          ObdlinkMxCanBus.highSpeedCan,
          filterIds: List<int>.generate(17, (index) => index),
        ),
        throwsArgumentError,
      );
    });

    test('builds rotating discovery banks while preserving priority IDs', () {
      final banks = LinuxObdlinkMxAdapter.buildFilterBanks(
        priorityIds: <int>[0x0C1, 0x0D1],
        discoveryIds: List<int>.generate(20, (index) => 0x100 + index),
      );

      expect(banks.length, 2);
      expect(banks.every((bank) => bank.length <= 16), isTrue);
      expect(banks.every((bank) => bank.contains(0x0C1)), isTrue);
      expect(banks.every((bank) => bank.contains(0x0D1)), isTrue);
      expect(
        banks.expand((bank) => bank).where((id) => id >= 0x100).toSet().length,
        20,
      );
    });

    test('read-only diagnostic gate accepts reads and rejects writes', () {
      expect(
        LinuxObdlinkMxAdapter.normalizeReadOnlyDiagnosticRequest('22 F1 90'),
        '22F190',
      );
      expect(
        LinuxObdlinkMxAdapter.normalizeReadOnlyDiagnosticRequest('01 00'),
        '0100',
      );
      expect(
        () => LinuxObdlinkMxAdapter.normalizeReadOnlyDiagnosticRequest('2E F1 90 00'),
        throwsFormatException,
      );
      expect(
        () => LinuxObdlinkMxAdapter.normalizeReadOnlyDiagnosticRequest('31 01 FF 00'),
        throwsFormatException,
      );
    });

    test('validates 11-bit diagnostic headers', () {
      expect(LinuxObdlinkMxAdapter.normalize11BitHeader('7e0'), '7E0');
      expect(
        () => LinuxObdlinkMxAdapter.normalize11BitHeader('18DAF110'),
        throwsFormatException,
      );
    });

    test('identifies the selected physical bus in the adapter name', () {
      final adapter = LinuxObdlinkMxAdapter(
        '/dev/rfcomm0',
        channel: 5,
        canBus: ObdlinkMxCanBus.singleWireCan,
      );

      expect(adapter.displayName, contains('CH5'));
      expect(adapter.displayName, contains('SWCAN'));
    });

    test('discovers paired MX+ as a direct RFCOMM target', () {
      final targets = LinuxObdlinkMxAdapter.parsePairedDeviceLines('''
Device 00:04:3E:84:41:C1 OBDLink MX+ 92248
Device C4:B7:57:0D:1C:EC TOYOTA Corolla
''');

      expect(targets, <String>['rfcomm://00:04:3E:84:41:C1:1']);
    });
  });

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

    test('parses an compact STM 11-bit frame without spaces or DLC', () {
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

    test('parses an compact STM 29-bit frame without spaces or DLC', () {
      final frame = LinuxObdlinkMxAdapter.parseMonitorLine(
        '18DAF110023E00',
      );

      expect(frame, isNotNull);
      expect(frame!.id, 0x18DAF110);
      expect(frame.extended, isTrue);
      expect(frame.data, <int>[0x02, 0x3E, 0x00]);
    });

    test('identifies terminal monitor conditions', () {
      expect(
        LinuxObdlinkMxAdapter.monitorTerminalError('BUFFER FULL'),
        contains('buffer full'),
      );
      expect(
        LinuxObdlinkMxAdapter.monitorTerminalError('STOPPED'),
        contains('stopped'),
      );
      expect(
        LinuxObdlinkMxAdapter.monitorTerminalError('UART RX OVERFLOW'),
        contains('overflow'),
      );
      expect(
        LinuxObdlinkMxAdapter.monitorTerminalError('0C1AABB'),
        isNull,
      );
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
