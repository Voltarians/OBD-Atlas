import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/core/gen1_hpcm2_contactor_state.dart';

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
}
