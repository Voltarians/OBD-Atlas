import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/core/can_frame.dart';
import 'package:obd_atlas/core/gm_live_diagnostic_monitor.dart';

CanFrame frame(double seconds, int id, List<int> data, {int channel = 2}) {
  return CanFrame(
    timestamp: DateTime.fromMicrosecondsSinceEpoch((seconds * 1000000).round(), isUtc: true),
    id: id,
    data: data,
    channel: channel,
  );
}

void main() {
  test('labels HPCM2 0x22 request response and latency', () {
    final snapshot = GmLiveDiagnosticMonitor.analyze(<CanFrame>[
      frame(1.000, 0x7E4, <int>[0x03, 0x22, 0x43, 0x56, 0, 0, 0, 0]),
      frame(1.009, 0x7EC, <int>[0x05, 0x62, 0x43, 0x56, 0xFF, 0xFA, 0, 0]),
    ]);

    expect(snapshot.endpointFrameCount, 2);
    final response = snapshot.events.first;
    expect(response.module, 'K114B HPCM2');
    expect(response.service, 'ReadDataByIdentifier');
    expect(response.did, 0x4356);
    expect(response.confidence, 'communityCandidate');
    expect(response.latencyMs, closeTo(9.0, 0.01));
  });

  test('keeps legacy BCM attribution separate from confidence', () {
    final snapshot = GmLiveDiagnosticMonitor.analyze(<CanFrame>[
      frame(2.000, 0x244, <int>[0x3E]),
      frame(2.012, 0x644, <int>[0x7E, 0, 0, 0, 0, 0]),
    ]);

    expect(snapshot.endpointFrameCount, 2);
    expect(snapshot.events.first.module, 'BCM');
    expect(snapshot.events.first.confidence, 'legacyReference');
    expect(snapshot.events.first.service, 'TesterPresent');
    expect(snapshot.events.first.latencyMs, closeTo(12.0, 0.01));
  });

  test('shows HPCM2 dynamic stream without decoding it as UDS', () {
    final snapshot = GmLiveDiagnosticMonitor.analyze(<CanFrame>[
      frame(3.000, 0x5EC, <int>[0xFE, 0x00, 0x64, 0x80, 0x00, 0, 0, 0]),
    ]);

    expect(snapshot.streamFrameCount, 1);
    expect(snapshot.events.single.addressRole, 'stream');
    expect(snapshot.events.single.module, 'K114B HPCM2');
    expect(snapshot.events.single.service, isNull);
  });

  test('preserves responsePending until final response', () {
    final snapshot = GmLiveDiagnosticMonitor.analyze(<CanFrame>[
      frame(4.000, 0x7E0, <int>[0x03, 0x36, 0x80, 0x40, 0, 0, 0, 0]),
      frame(4.010, 0x7E8, <int>[0x03, 0x7F, 0x36, 0x78, 0, 0, 0, 0]),
      frame(4.050, 0x7E8, <int>[0x02, 0x76, 0x80, 0, 0, 0, 0, 0]),
    ]);

    expect(snapshot.events.length, 3);
    final pending = snapshot.events[1];
    final finalResponse = snapshot.events[0];
    expect(pending.negativeResponseName, 'responsePending');
    expect(pending.latencyMs, closeTo(10.0, 0.01));
    expect(finalResponse.service, 'TransferData');
    expect(finalResponse.latencyMs, closeTo(50.0, 0.01));
  });

  test('reassembles multi-frame ISO-TP response', () {
    final snapshot = GmLiveDiagnosticMonitor.analyze(<CanFrame>[
      frame(5.000, 0x7E4, <int>[0x03, 0x22, 0x43, 0xAF, 0, 0, 0, 0]),
      frame(5.010, 0x7EC, <int>[0x10, 0x09, 0x62, 0x43, 0xAF, 1, 2, 3]),
      frame(5.011, 0x7EC, <int>[0x21, 4, 5, 6, 7, 8, 0, 0]),
    ]);

    final response = snapshot.events.first;
    expect(response.service, 'ReadDataByIdentifier');
    expect(response.did, 0x43AF);
    expect(response.latencyMs, closeTo(10.0, 0.01));
  });
}
