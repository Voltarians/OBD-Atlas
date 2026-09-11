import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/core/can_frame.dart';
import 'package:obd_atlas/core/signal_discovery.dart';

CanFrame frame(int value, {int id = 0x17d}) => CanFrame(
      timestamp: DateTime(2026),
      channel: 4,
      id: id,
      data: <int>[0x22, 0x24, value, 0xff, 0, 0],
    );

void main() {
  test('ranks a bit that changes only during a marked event', () {
    final discovery = SignalDiscoverySession()..start(label: 'Brake');
    for (var i = 0; i < 10; i++) {
      discovery.observe(frame(0x42));
      discovery.observe(frame(i.isEven ? 0 : 1, id: 0x200));
    }
    discovery.markEventStart();
    for (var i = 0; i < 10; i++) {
      discovery.observe(frame(0x62));
      discovery.observe(frame(i.isEven ? 0 : 1, id: 0x200));
    }
    discovery.markEventEnd();
    for (var i = 0; i < 10; i++) {
      discovery.observe(frame(0x42));
      discovery.observe(frame(i.isEven ? 0 : 1, id: 0x200));
    }

    final candidates = discovery.finish();

    expect(candidates, hasLength(1));
    expect(candidates.single.channel, 4);
    expect(candidates.single.id, 0x17d);
    expect(candidates.single.byteIndex, 2);
    expect(candidates.single.bitIndex, 5);
    expect(candidates.single.transition, '0% → 100% → 0%');
  });

  test('requires all three operator-marked windows', () {
    final discovery = SignalDiscoverySession()..start(label: 'Brake');
    for (var i = 0; i < 10; i++) {
      discovery.observe(frame(0x42));
    }

    expect(discovery.finish(), isEmpty);
    expect(discovery.phase, DiscoveryPhase.complete);
  });
}
