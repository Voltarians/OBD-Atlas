import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

enum EventMarkerMode {
  click,
  voice,
  clickAndVoice,
  off,
}

extension EventMarkerModeInfo on EventMarkerMode {
  String get displayName => switch (this) {
        EventMarkerMode.click => 'Click markers',
        EventMarkerMode.voice => 'Voice markers',
        EventMarkerMode.clickAndVoice => 'Click + voice',
        EventMarkerMode.off => 'Off',
      };

  bool get usesClick =>
      this == EventMarkerMode.click || this == EventMarkerMode.clickAndVoice;

  bool get usesVoice =>
      this == EventMarkerMode.voice || this == EventMarkerMode.clickAndVoice;
}

/// Records a synchronized operator voice track beside an Atlas CAN capture.
///
/// Voice is supporting evidence only. The recorder deliberately does not claim
/// sample-accurate synchronization because ALSA input latency is not calibrated.
/// The sidecar metadata preserves the application start/stop anchors so later
/// offline transcription can correlate spoken observations with the raw CAN log.
class VoiceAnnotationCapture extends ChangeNotifier {
  Process? _process;
  bool _stopping = false;
  DateTime? _startRequestedUtc;
  DateTime? _stopRequestedUtc;

  File? activeAudioFile;
  File? activeMetadataFile;
  File? lastCompletedAudioFile;
  File? lastCompletedMetadataFile;
  Object? lastError;

  bool get isRecording => _process != null && !_stopping;
  bool get isStopping => _stopping;

  static String _withoutExtension(String path) {
    final slash = path.lastIndexOf(Platform.pathSeparator);
    final dot = path.lastIndexOf('.');
    if (dot <= slash) return path;
    return path.substring(0, dot);
  }

  static File audioFileForCapture(File captureFile) =>
      File('${_withoutExtension(captureFile.path)}.voice.wav');

  static File metadataFileForCapture(File captureFile) =>
      File('${_withoutExtension(captureFile.path)}.voice.json');

  Future<bool> isAvailable() async {
    if (!Platform.isLinux) return false;
    try {
      final result = await Process.run(
        'sh',
        const ['-c', 'command -v arecord >/dev/null 2>&1'],
      );
      return result.exitCode == 0;
    } catch (_) {
      return false;
    }
  }

  Future<File> start(
    File canCaptureFile, {
    String device = 'default',
    int sampleRateHz = 16000,
  }) async {
    if (_process != null) return activeAudioFile!;
    if (!Platform.isLinux) {
      throw UnsupportedError('Voice annotation capture currently requires Linux/ALSA.');
    }
    if (!await isAvailable()) {
      throw StateError('ALSA arecord was not found. Install alsa-utils to enable voice markers.');
    }

    lastError = null;
    _stopping = false;
    _startRequestedUtc = DateTime.now().toUtc();
    _stopRequestedUtc = null;

    final audio = audioFileForCapture(canCaptureFile);
    final metadata = metadataFileForCapture(canCaptureFile);
    if (await audio.exists()) await audio.delete();
    if (await metadata.exists()) await metadata.delete();

    final process = await Process.start(
      'arecord',
      [
        '-q',
        '-D',
        device,
        '-f',
        'S16_LE',
        '-r',
        '$sampleRateHz',
        '-c',
        '1',
        '-t',
        'wav',
        audio.path,
      ],
    );

    _process = process;
    activeAudioFile = audio;
    activeMetadataFile = metadata;
    notifyListeners();

    unawaited(process.exitCode.then((code) {
      if (identical(_process, process) && !_stopping) {
        lastError = StateError('Voice recorder exited unexpectedly with code $code.');
        _process = null;
        notifyListeners();
      }
    }));

    return audio;
  }

  Future<File?> stop() async {
    final process = _process;
    if (process == null) return lastCompletedAudioFile;

    _stopping = true;
    _stopRequestedUtc = DateTime.now().toUtc();
    notifyListeners();

    try {
      process.kill(ProcessSignal.sigint);
      try {
        await process.exitCode.timeout(const Duration(seconds: 3));
      } on TimeoutException {
        process.kill(ProcessSignal.sigterm);
        await process.exitCode.timeout(const Duration(seconds: 2));
      }
    } catch (error) {
      lastError ??= error;
    }

    final audio = activeAudioFile;
    final metadata = activeMetadataFile;
    if (audio != null && metadata != null) {
      await _writeMetadata(audio, metadata);
      lastCompletedAudioFile = audio;
      lastCompletedMetadataFile = metadata;
    }

    _process = null;
    activeAudioFile = null;
    activeMetadataFile = null;
    _stopping = false;
    notifyListeners();
    return lastCompletedAudioFile;
  }

  Future<void> _writeMetadata(File audio, File metadata) async {
    final start = _startRequestedUtc;
    final stop = _stopRequestedUtc ?? DateTime.now().toUtc();
    final payload = <String, dynamic>{
      'schema': 'obd-atlas.voice-annotation.v1',
      'role': 'synchronized_voice_annotation',
      'audio_file': audio.uri.pathSegments.last,
      'format': 'wav_pcm_s16le',
      'sample_rate_hz': 16000,
      'channels': 1,
      'start_requested_utc': start?.toIso8601String(),
      'stop_requested_utc': stop.toIso8601String(),
      'audio_start_epoch_seconds': start == null
          ? null
          : start.microsecondsSinceEpoch / 1000000.0,
      'audio_stop_epoch_seconds': stop.microsecondsSinceEpoch / 1000000.0,
      'size_bytes': await audio.exists() ? await audio.length() : null,
      'alignment': <String, dynamic>{
        'method': 'same_application_process_start_anchor',
        'input_latency_calibrated': false,
        'timing_confidence': 'supportingEvidenceOnly',
        'note': 'ALSA microphone onset latency is not independently calibrated; voice observations must not be promoted to confirmed signal definitions without CAN evidence.',
      },
    };
    await metadata.writeAsString(
      const JsonEncoder.withIndent('  ').convert(payload),
      flush: true,
    );
  }
}
