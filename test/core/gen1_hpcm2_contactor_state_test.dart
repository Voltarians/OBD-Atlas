import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/core/can_frame.dart';
import 'package:obd_atlas/core/gen1_hpcm2_contactor_state.dart';

CanFrame frame(double seconds, int id, List<int> data, {int channel = 2}) {
  return CanFrame(
    timestamp: DateTime.fromMicrosecondsSinceEpoch(
      (seconds * 1000000).round(),
      isUtc: true,
    ),
    id: id,
    data: data,
    channel: channel,
  );
}

void main() {
  test('decodes vehicle-observed HPCM2 0x430E states', () {
    final off = Gen1Hpcm2ContactorStateDecoder.decodeDynamicPayload(
      didContext: 0x430E,
      payload: const <int>[0xFE, 0x68],
    )!;
    final first = Gen1Hpcm2ContactorStateDecoder.decodeDynamicPayload(
      didContext: 0x430E,
      payload: const <int>[0xFE, 0x6A],
    )!;
    final precharge = Gen1Hpcm2ContactorStateDecoder.decodeDynamicPayload(
      didContext: 0x430E,
      payload: const <int>[0xFE, 0x6F],
    )!;
    final ready = Gen1Hpcm2ContactorStateDecoder.decodeDynamicPayload(
      didContext: 0x430E,
      payload: const <int>[0xFE, 0x6B],
    )!;

    expect(off.phase, Gen1Hpcm2HvPhase.hvOff);
    expect(off.mainContactorBit0, isFalse);
    expect(off.mainContactorBit1, isFalse);
    expect(first.mainContactorBit1, isTrue);
    expect(precharge.prechargeBit2, isTrue);
    expect(ready.prechargeBit2, isFalse);
    expect(ready.phase, Gen1Hpcm2HvPhase.hvBusEstablished);
  });

  test('rejects payload without 0x430E context', () {
    expect(
      Gen1Hpcm2ContactorStateDecoder.decodeDynamicPayload(
        didContext: 0x432D,
        payload: const <int>[0xFE, 0x6B],
      ),
      isNull,
    );
  });

  test('classifies successful startup and normal shutdown', () {
    expect(
      Gen1Hpcm2ContactorStateDecoder.classifyRawStates(
        const <int>[0x68, 0x68, 0x6A, 0x6F, 0x6B, 0x6B],
      ),
      Gen1Hpcm2SequenceClassification.successfulStartup,
    );
    expect(
      Gen1Hpcm2ContactorStateDecoder.classifyRawStates(
        const <int>[0x6B, 0x6A, 0x68],
      ),
      Gen1Hpcm2SequenceClassification.normalShutdown,
    );
  });

  test('interrupted transitions are not classified as stable', () {
    expect(
      Gen1Hpcm2ContactorStateDecoder.classifyRawStates(
        const <int>[0x68, 0x6A, 0x68],
      ),
      Gen1Hpcm2SequenceClassification.unknownOrIncomplete,
    );
    expect(
      Gen1Hpcm2ContactorStateDecoder.classifyRawStates(
        const <int>[0x6B, 0x6A, 0x6B],
      ),
      Gen1Hpcm2SequenceClassification.unknownOrIncomplete,
    );
  });

  test('live tracker requires successful FE to 430E definition', () {
    final tracker = Gen1Hpcm2ContactorLiveTracker();

    tracker.observe(frame(1.000, 0x5EC, const <int>[0xFE, 0x6B]));
    expect(tracker.currentSample, isNull);

    tracker.observe(
      frame(1.100, 0x7E4, const <int>[0x04, 0x2C, 0xFE, 0x43, 0x0E, 0, 0, 0]),
    );
    tracker.observe(
      frame(1.110, 0x7EC, const <int>[0x02, 0x6C, 0xFE, 0, 0, 0, 0, 0]),
    );
    expect(tracker.hasConfirmedContactorContext, isTrue);

    tracker.observe(frame(1.200, 0x5EC, const <int>[0xFE, 0x68]));
    tracker.observe(frame(1.400, 0x5EC, const <int>[0xFE, 0x6A]));
    tracker.observe(frame(1.600, 0x5EC, const <int>[0xFE, 0x6F]));
    tracker.observe(frame(1.800, 0x5EC, const <int>[0xFE, 0x6B]));

    expect(tracker.currentSample!.phase, Gen1Hpcm2HvPhase.hvBusEstablished);
    expect(
      tracker.sequenceClassification,
      Gen1Hpcm2SequenceClassification.successfulStartup,
    );
  });

  test('live tracker stops decoding FE after confirmed redefinition', () {
    final tracker = Gen1Hpcm2ContactorLiveTracker();
    tracker.observe(
      frame(2.000, 0x7E4, const <int>[0x04, 0x2C, 0xFE, 0x43, 0x0E, 0, 0, 0]),
    );
    tracker.observe(
      frame(2.010, 0x7EC, const <int>[0x02, 0x6C, 0xFE, 0, 0, 0, 0, 0]),
    );
    tracker.observe(frame(2.100, 0x5EC, const <int>[0xFE, 0x68]));
    expect(tracker.currentSample!.rawState, 0x68);

    tracker.observe(
      frame(2.200, 0x7E4, const <int>[0x04, 0x2C, 0xFE, 0x43, 0x2D, 0, 0, 0]),
    );
    tracker.observe(
      frame(2.210, 0x7EC, const <int>[0x02, 0x6C, 0xFE, 0, 0, 0, 0, 0]),
    );
    tracker.observe(frame(2.300, 0x5EC, const <int>[0xFE, 0x6B]));

    expect(tracker.currentSample!.rawState, 0x68);
  });
}
