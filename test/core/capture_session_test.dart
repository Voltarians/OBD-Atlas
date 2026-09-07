import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/core/capture_session.dart';

class _MemoryOutput implements CaptureOutput {
  final lines = <String>[];
  final Completer<void> closeGate = Completer<void>();
  bool finished = false;
  int finishCalls = 0;

  @override
  void writeLine(String line) {
    if (finished) throw StateError('Write after close');
    lines.add(line);
  }

  @override
  Future<void> finish() async {
    finishCalls++;
    await closeGate.future;
    finished = true;
  }
}

void main() {
  late _MemoryOutput output;
  late CaptureSession session;
  final file = File('test-capture.log');

  setUp(() {
    output = _MemoryOutput();
    session = CaptureSession(
      createFile: () async => file,
      openOutput: (_, __) => output,
    );
  });

  test('stop rejects further writes immediately and waits for close', () async {
    await session.start();
    session.writeLine('before');
    final stopping = session.stop();
    expect(session.phase, CapturePhase.stopping);
    expect(session.isRecording, isFalse);
    session.writeLine('after');
    expect(output.lines, ['before']);
    expect(() => session.start(), throwsStateError);
    expect(identical(stopping, session.stop()), isTrue);
    output.closeGate.complete();
    expect(await stopping, file);
    expect(session.phase, CapturePhase.idle);
    expect(session.lastCompletedFile, file);
    expect(session.lastCompletedFrames, 1);
    expect(output.finishCalls, 1);
  });

  test('Stop during Start cannot leave a writer running', () async {
    final creation = Completer<File>();
    session = CaptureSession(
      createFile: () => creation.future,
      openOutput: (_, __) => output,
    );
    final starting = session.start();
    expect(session.phase, CapturePhase.starting);
    final stopping = session.stop();
    expect(session.phase, CapturePhase.stopping);
    creation.complete(file);
    expect(await starting, file);
    session.writeLine('not recorded');
    output.closeGate.complete();
    expect(await stopping, file);
    expect(output.lines, isEmpty);
    expect(session.phase, CapturePhase.idle);
  });

  test('a failed Start returns to idle and preserves the error', () async {
    session = CaptureSession(
      createFile: () async => throw const FileSystemException('disk unavailable'),
      openOutput: (_, __) => output,
    );
    await expectLater(session.start(), throwsA(isA<FileSystemException>()));
    expect(session.phase, CapturePhase.idle);
    expect(session.lastError, isA<FileSystemException>());
    expect(await session.stop(), isNull);
  });

  test('a completed capture can be followed by a separate session', () async {
    await session.start();
    session.writeLine('one');
    final firstStop = session.stop();
    output.closeGate.complete();
    await firstStop;
    final second = _MemoryOutput();
    session = CaptureSession(
      createFile: () async => File('second.log'),
      openOutput: (_, __) => second,
    );
    await session.start();
    session.writeLine('two');
    final secondStop = session.stop();
    second.closeGate.complete();
    await secondStop;
    expect(output.lines, ['one']);
    expect(second.lines, ['two']);
    expect(session.lastCompletedFrames, 1);
  });
}
