import 'package:flutter_test/flutter_test.dart';

import 'package:obd_atlas/core/can_frame.dart';
import 'package:obd_atlas/core/external_app_observation.dart';

CanFrame frame(DateTime t, int channel, int id, List<int> data) => CanFrame(
      timestamp: t,
      channel: channel,
      id: id,
      data: data,
    );

void main() {
  test('ranks a newly appearing diagnostic request and response pair', () {
    final session = ExternalAppObservationSession();
    final markerTime = DateTime.utc(2026, 9, 10, 3, 0, 10);
    session.start();

    for (var i = 0; i < 8; i++) {
      session.observe(frame(
        markerTime.subtract(Duration(milliseconds: 2500 - i * 200)),
        1,
        0x123,
        <int>[0x10, i],
      ));
    }

    final marker = session.mark('Voltage battery screen opened', timestamp: markerTime);

    for (var i = 0; i < 5; i++) {
      session.observe(frame(
        markerTime.add(Duration(milliseconds: 100 + i * 250)),
        2,
        0x7E7,
        const <int>[0x03, 0x22, 0x41, 0x81],
      ));
      session.observe(frame(
        markerTime.add(Duration(milliseconds: 140 + i * 250)),
        2,
        0x7EF,
        const <int>[0x10, 0x0A, 0x62, 0x41, 0x81, 0x00, 0x01, 0x02],
      ));
    }

    final report = session.correlate(marker);
    expect(report.candidates, isNotEmpty);
    final request = report.candidates.firstWhere((c) => c.id == 0x7E7);
    expect(request.channel, 2);
    expect(request.beforeFrames, 0);
    expect(request.afterFrames, 5);
    expect(request.diagnosticLike, isTrue);
    expect(request.likelyResponseId, 0x7EF);
  });

  test('keeps channels separate when the same arbitration id exists on two buses', () {
    final session = ExternalAppObservationSession();
    final markerTime = DateTime.utc(2026, 9, 10, 4, 0, 0);
    session.start();
    final marker = session.mark('DTC screen opened', timestamp: markerTime);

    session.observe(frame(markerTime.add(const Duration(milliseconds: 100)), 1, 0x7E0, const <int>[1]));
    session.observe(frame(markerTime.add(const Duration(milliseconds: 110)), 4, 0x7E0, const <int>[2]));

    final report = session.correlate(marker);
    final matches = report.candidates.where((candidate) => candidate.id == 0x7E0).toList();
    expect(matches.length, 2);
    expect(matches.map((candidate) => candidate.channel).toSet(), <int>{1, 4});
  });

  test('exports passive observation schema and marker labels', () {
    final session = ExternalAppObservationSession(maxFrames: 2);
    final markerTime = DateTime.utc(2026, 9, 10, 5, 0, 0);
    session.start();
    session.observe(frame(markerTime.subtract(const Duration(seconds: 1)), 1, 0x100, const <int>[0]));
    session.observe(frame(markerTime, 1, 0x101, const <int>[1]));
    session.observe(frame(markerTime.add(const Duration(seconds: 1)), 1, 0x102, const <int>[2]));
    session.mark('Voltage connected', timestamp: markerTime);
    session.finish();

    final json = session.exportJson();
    expect(json, contains('obd-atlas.external-app-observation.v1'));
    expect(json, contains('Voltage connected'));
    expect(json, contains('"passive_only": true'));
    expect(session.truncated, isTrue);
  });
}
