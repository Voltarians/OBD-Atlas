import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/adapters/uc2_receive.dart';

void main() {
  test('empty queue never enters blocking receive', () {
    var calls = 0;
    final count = drainUc2Receive(
      source: 'test CAN0',
      pending: () => 0,
      receive: (_, __) {
        calls++;
        return 1;
      },
      onFrame: () {},
    );
    expect(count, 0);
    expect(calls, 0);
  });

  test('uses the validated single-frame positive-timeout call', () {
    var queued = 3;
    var delivered = 0;
    final requests = <(int, int)>[];
    final count = drainUc2Receive(
      source: 'test CAN0',
      pending: () => queued,
      receive: (requested, waitMs) {
        requests.add((requested, waitMs));
        queued--;
        return 1;
      },
      onFrame: () => delivered++,
    );
    expect(count, 3);
    expect(delivered, 3);
    expect(requests, [(1, 100), (1, 100), (1, 100)]);
  });

  test('bounded draining leaves time for other physical ports', () {
    var queued = 100;
    var delivered = 0;
    final count = drainUc2Receive(
      source: 'test CAN0',
      pending: () => queued,
      receive: (_, __) {
        queued--;
        return 1;
      },
      onFrame: () => delivered++,
    );
    expect(count, uc2ReceiveBurstLimit);
    expect(delivered, uc2ReceiveBurstLimit);
    expect(queued, 100 - uc2ReceiveBurstLimit);
  });

  test('zero receive result stops without emitting a phantom frame', () {
    var calls = 0;
    final count = drainUc2Receive(
      source: 'test CAN0',
      pending: () => 10,
      receive: (_, __) {
        calls++;
        return 0;
      },
      onFrame: () => fail('No frame was retrieved.'),
    );
    expect(count, 0);
    expect(calls, 1);
  });

  test('native pending error is not mistaken for a huge queue', () {
    expect(
      () => drainUc2Receive(
        source: 'test CAN0',
        pending: () => 0xffffffff,
        receive: (_, __) => 0,
        onFrame: () {},
      ),
      throwsA(isA<StateError>()),
    );
  });

  test('native receive errors and invalid counts are reported', () {
    for (final result in [0xffffffff, 2, -1]) {
      expect(
        () => drainUc2Receive(
          source: 'test CAN0',
          pending: () => 1,
          receive: (_, __) => result,
          onFrame: () => fail('Invalid native result.'),
        ),
        throwsA(isA<StateError>()),
      );
    }
  });

  test('invalid burst and timeout settings are rejected', () {
    for (final settings in [(0, 100), (1, -1)]) {
      expect(
        () => drainUc2Receive(
          source: 'test CAN0',
          pending: () => 0,
          receive: (_, __) => 0,
          onFrame: () {},
          maxFrames: settings.$1,
          waitMs: settings.$2,
        ),
        throwsArgumentError,
      );
    }
  });
}
