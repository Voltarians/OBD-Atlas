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
}
