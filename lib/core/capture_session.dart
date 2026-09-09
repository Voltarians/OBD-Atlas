import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

import 'local_store.dart';

abstract interface class CaptureOutput {
  void writeLine(String line);
  Future<void> flush();
  Future<void> finish();
}

class _FileCaptureOutput implements CaptureOutput {
  _FileCaptureOutput(this._file, void Function(Object, StackTrace) _);
  final File _file;
  StringBuffer _buffer = StringBuffer();
  Future<void> _writes = Future<void>.value();

  @override
  void writeLine(String line) => _buffer.writeln(line);

  @override
  Future<void> flush() {
    final batch = _buffer.toString();
    _buffer = StringBuffer();
    if (batch.isNotEmpty) {
      _writes = _writes.then<void>((_) async {
        await _file.writeAsString(batch, mode: FileMode.writeOnlyAppend, flush: true);
      });
    }
    return _writes;
  }

  @override
  Future<void> finish() => flush();
}

enum CapturePhase { idle, starting, recording, stopping }

typedef CaptureOutputFactory = CaptureOutput Function(
  File file,
  void Function(Object, StackTrace) onError,
);

typedef CaptureCompleted = Future<void> Function(File file, int frames, Object? error);

/// Owns one capture file. Start/stop requests are serialized, including a
/// Stop arriving while asynchronous file creation is still in progress.
/// A completed session is finalized only after all buffered writes finish.
class CaptureSession extends ChangeNotifier {
  CaptureSession({
    required Future<File> Function() createFile,
    CaptureOutputFactory? openOutput,
    CaptureCompleted? onCompleted,
  })  : _createFile = createFile,
        _openOutput = openOutput ?? _FileCaptureOutput.new,
        _onCompleted = onCompleted ?? AtlasLocalStore.instance.completeCapture;

  final Future<File> Function() _createFile;
  final CaptureOutputFactory _openOutput;
  final CaptureCompleted _onCompleted;
  CapturePhase _phase = CapturePhase.idle;
  CaptureOutput? _output;
  Future<File>? _starting;
  Future<File?>? _stopping;
  Future<void> _flushTask = Future<void>.value();
  Timer? _flushTimer;
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
      File? file;
      try {
        file = await _createFile();
        final output = _openOutput(file, _onOutputError);
        activeFile = file;
        _output = output;
        _setPhase(_stopRequested ? CapturePhase.stopping : CapturePhase.recording);
        if (!_stopRequested) {
          _flushTimer = Timer.periodic(
            const Duration(seconds: 1),
            (_) => _scheduleFlush(output),
          );
        }
        completer.complete(file);
      } catch (error, stack) {
        lastError = error;
        if (file != null) {
          try { await _onCompleted(file, recordedFrames, error); }
          catch (finalizeError) { lastError ??= finalizeError; }
        }
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

  void _scheduleFlush(CaptureOutput output) {
    _flushTask = _flushTask.then<void>((_) async {
      if (identical(_output, output) && isRecording) await output.flush();
    }).catchError((Object error, StackTrace stack) {
      _onOutputError(error, stack);
    });
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
    _flushTimer?.cancel();
    _flushTimer = null;
    _setPhase(CapturePhase.stopping);
    final completer = Completer<File?>();
    _stopping = completer.future;
    () async {
      File? file;
      Object? failure;
      StackTrace? failureStack;
      try {
        if (_starting != null) {
          try { await _starting; } catch (_) {}
        }
        final output = _output;
        file = activeFile;
        _output = null;
        try {
          await _flushTask;
          if (output != null) await output.finish();
        } catch (error, stack) {
          failure = error;
          failureStack = stack;
          lastError ??= error;
        }
        if (file != null) {
          try {
            await _onCompleted(file, recordedFrames, lastError ?? failure);
          } catch (error, stack) {
            failure ??= error;
            failureStack ??= stack;
            lastError ??= error;
          }
          if (failure == null) {
            lastCompletedFile = file;
            lastCompletedFrames = recordedFrames;
          }
        }
        if (failure != null) {
          Error.throwWithStackTrace(failure, failureStack ?? StackTrace.current);
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
        _flushTask = Future<void>.value();
        _flushTimer?.cancel();
        _flushTimer = null;
        _stopRequested = false;
        _setPhase(CapturePhase.idle);
      }
    }();
    return completer.future;
  }
}
