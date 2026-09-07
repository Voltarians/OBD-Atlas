import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

/// A sink that can be replaced by a controlled writer in lifecycle tests.
abstract interface class CaptureOutput {
  void writeLine(String line);
  Future<void> finish();
}

class _FileCaptureOutput implements CaptureOutput {
  _FileCaptureOutput(File file, void Function(Object, StackTrace) onError)
      : _sink = file.openWrite(mode: FileMode.writeOnlyAppend) {
    // Observe asynchronous filesystem failures even before Stop is pressed.
    _sink.done.then<void>((_) {}, onError: (Object error, StackTrace stack) {
      onError(error, stack);
    });
  }

  final IOSink _sink;

  @override
  void writeLine(String line) => _sink.writeln(line);

  @override
  Future<void> finish() async {
    Object? failure;
    StackTrace? failureStack;
    try {
      await _sink.flush();
    } catch (error, stack) {
      failure = error;
      failureStack = stack;
    }
    // Always attempt close, even if flushing failed.
    try {
      await _sink.close();
    } catch (error, stack) {
      failure ??= error;
      failureStack ??= stack;
    }
    if (failure != null) {
      Error.throwWithStackTrace(failure, failureStack!);
    }
  }
}

enum CapturePhase { idle, starting, recording, stopping }

typedef CaptureOutputFactory = CaptureOutput Function(
  File file,
  void Function(Object, StackTrace) onError,
);

/// Owns one capture file. Start/stop requests are serialized, including a
/// Stop arriving while the asynchronous file creation is still in progress.
/// The frame callback never waits for disk I/O or rebuilds the UI.
class CaptureSession extends ChangeNotifier {
  CaptureSession({
    required Future<File> Function() createFile,
    CaptureOutputFactory? openOutput,
  })  : _createFile = createFile,
        _openOutput = openOutput ?? _FileCaptureOutput.new;

  final Future<File> Function() _createFile;
  final CaptureOutputFactory _openOutput;
  CapturePhase _phase = CapturePhase.idle;
  CaptureOutput? _output;
  Future<File>? _starting;
  Future<File?>? _stopping;
  bool _stopRequested = false;
  File? activeFile;
  File? lastCompletedFile;
  Object? lastError;
  int recordedFrames = 0;
  int lastCompletedFrames = 0;

  CapturePhase get phase => _phase;
  bool get isRecording => _phase == CapturePhase.recording;
  bool get isBusy => _phase == CapturePhase.starting || _phase == CapturePhase.stopping;
  bool get hasOpenCapture => _phase != CapturePhase.idle;

  void _setPhase(CapturePhase value) {
    _phase = value;
    notifyListeners();
  }

  Future<File> start() {
    if (_phase == CapturePhase.recording) return Future<File>.value(activeFile!);
    if (_phase == CapturePhase.starting) return _starting!;
    if (_phase == CapturePhase.stopping) {
      throw StateError('Wait for the previous capture to finish closing.');
    }
    _stopRequested = false;
    lastError = null;
    recordedFrames = 0;
    _setPhase(CapturePhase.starting);
    final completer = Completer<File>();
    _starting = completer.future;
    () async {
      try {
        final file = await _createFile();
        final output = _openOutput(file, _onOutputError);
        activeFile = file;
        _output = output;
        _setPhase(_stopRequested ? CapturePhase.stopping : CapturePhase.recording);
        completer.complete(file);
      } catch (error, stack) {
        lastError = error;
        if (!_stopRequested) _setPhase(CapturePhase.idle);
        completer.completeError(error, stack);
      } finally {
        _starting = null;
      }
    }();
    return completer.future;
  }

  void writeLine(String line) {
    if (!isRecording) return;
    try {
      _output?.writeLine(line);
      recordedFrames++;
    } catch (error, stack) {
      _onOutputError(error, stack);
    }
  }

  void _onOutputError(Object error, StackTrace stack) {
    lastError ??= error;
    notifyListeners();
    if (_phase == CapturePhase.recording || _phase == CapturePhase.starting) {
      unawaited(stop().catchError((Object _) => null));
    }
  }

  Future<File?> stop() {
    if (_stopping != null) return _stopping!;
    if (_phase == CapturePhase.idle) return Future<File?>.value(null);
    _stopRequested = true;
    _setPhase(CapturePhase.stopping);
    final completer = Completer<File?>();
    _stopping = completer.future;
    () async {
      try {
        // Wait for a pending Start to open its file before closing it.
        // A failed Start has no writer to close and its error is preserved.
        if (_starting != null) {
          try {
            await _starting;
          } catch (_) {}
        }
        final output = _output;
        final file = activeFile;
        // No subsequent frame may write to this output, even while close waits.
        _output = null;
        if (output != null) await output.finish();
        if (file != null) {
          lastCompletedFile = file;
          lastCompletedFrames = recordedFrames;
        }
        completer.complete(file);
      } catch (error, stack) {
        lastError ??= error;
        completer.completeError(error, stack);
      } finally {
        activeFile = null;
        _output = null;
        _starting = null;
        _stopping = null;
        _stopRequested = false;
        _setPhase(CapturePhase.idle);
      }
    }();
    return completer.future;
  }
}
