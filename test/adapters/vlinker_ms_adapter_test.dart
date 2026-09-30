import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/adapters/vlinker_ms_adapter.dart';

void main() {
  test('parses compact 11-bit STM frame', () {
    final frame = VlinkerMsAdapter.parseMonitorLine(
      '3E912345678',
      channel: 1,
    );

    expect(frame, isNotNull);
    expect(frame!.id, 0x3E9);
    expect(frame.data, <int>[0x12, 0x34, 0x56, 0x78]);
    expect(frame.extended, isFalse);
    expect(frame.channel, 1);
  });

  test('parses compact 29-bit STM frame', () {
    final frame = VlinkerMsAdapter.parseMonitorLine(
      '18DAF11001020304',
      channel: 2,
    );

    expect(frame, isNotNull);
    expect(frame!.id, 0x18DAF110);
    expect(frame.data, <int>[1, 2, 3, 4]);
    expect(frame.extended, isTrue);
    expect(frame.channel, 2);
  });

  test('parses spaced frame with displayed DLC', () {
    final frame = VlinkerMsAdapter.parseMonitorLine(
      '3E9 04 12 34 56 78',
      channel: 3,
    );

    expect(frame, isNotNull);
    expect(frame!.id, 0x3E9);
    expect(frame.data, <int>[0x12, 0x34, 0x56, 0x78]);
    expect(frame.channel, 3);
  });

  test('rejects monitor chatter and malformed payloads', () {
    expect(VlinkerMsAdapter.parseMonitorLine('SEARCHING...'), isNull);
    expect(VlinkerMsAdapter.parseMonitorLine('BUFFER FULL'), isNull);
    expect(VlinkerMsAdapter.parseMonitorLine('3E9ABC'), isNull);
  });

  test('extracts Android RFCOMM address from paired-device label', () {
    expect(
      VlinkerMsAdapter.androidAddressFromLabel(
        'vLinker MS • 12:34:56:78:9A:BC',
      ),
      '12:34:56:78:9A:BC',
    );
    expect(
      VlinkerMsAdapter.androidAddressFromLabel('vLinker MS'),
      isNull,
    );
  });

  test('reports terminal monitor errors', () {
    expect(
      VlinkerMsAdapter.monitorTerminalError('BUFFER FULL'),
      contains('buffer full'),
    );
    expect(
      VlinkerMsAdapter.monitorTerminalError('?'),
      contains('rejected'),
    );
    expect(VlinkerMsAdapter.monitorTerminalError('3E91234'), isNull);
  });

  test('packs production filter banks under the configured throughput budget', () {
    final banks = VlinkerMsAdapter.planProductionFilterBanks(
      <int, int>{
        0x100: 1000,
        0x101: 900,
        0x102: 800,
        0x103: 700,
        0x104: 600,
        0x105: 500,
      },
      const Duration(seconds: 2),
      targetFramesPerSecond: 1500,
      headroom: 0.80,
    );

    expect(banks, isNotEmpty);
    expect(banks.expand((bank) => bank).toSet(), hasLength(6));
    expect(banks.every((bank) => bank.length <= 32), isTrue);

    final rates = <int, double>{
      0x100: 500,
      0x101: 450,
      0x102: 400,
      0x103: 350,
      0x104: 300,
      0x105: 250,
    };
    for (final bank in banks) {
      final total = bank.fold<double>(
        0,
        (sum, id) => sum + rates[id]!,
      );
      expect(total, lessThanOrEqualTo(1200));
    }
  });

  test('production filter planning covers more than 32 observed IDs by rotating banks', () {
    final counts = <int, int>{
      for (var id = 0; id < 70; id++) 0x100 + id: 2,
    };

    final banks = VlinkerMsAdapter.planProductionFilterBanks(
      counts,
      const Duration(seconds: 2),
    );

    expect(banks.length, greaterThanOrEqualTo(3));
    expect(banks.every((bank) => bank.length <= 32), isTrue);
    expect(banks.expand((bank) => bank).toSet(), hasLength(70));
  });

  test('production filter planning ignores invalid and extended identifiers', () {
    final banks = VlinkerMsAdapter.planProductionFilterBanks(
      <int, int>{
        -1: 10,
        0x100: 10,
        0x7FF: 10,
        0x800: 10,
      },
      const Duration(seconds: 1),
    );

    expect(banks.expand((bank) => bank).toSet(), <int>{0x100, 0x7FF});
  });


  test('exposes capture provenance counters and mode', () {
    final adapter = VlinkerMsAdapter('COM9');
    final provenance = adapter.captureProvenance;

    expect(provenance['mode'], isNotNull);
    expect(provenance['monitorErrorCount'], 0);
    expect(provenance['overflowCount'], 0);
    expect(provenance['filterBanks'], isA<List<Object?>>());
  });

}
