import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/core/voice_annotation_capture.dart';

void main() {
  test('event marker modes expose click and voice capabilities', () {
    expect(EventMarkerMode.click.usesClick, isTrue);
    expect(EventMarkerMode.click.usesVoice, isFalse);

    expect(EventMarkerMode.voice.usesClick, isFalse);
    expect(EventMarkerMode.voice.usesVoice, isTrue);

    expect(EventMarkerMode.clickAndVoice.usesClick, isTrue);
    expect(EventMarkerMode.clickAndVoice.usesVoice, isTrue);

    expect(EventMarkerMode.off.usesClick, isFalse);
    expect(EventMarkerMode.off.usesVoice, isFalse);
  });

  test('voice evidence files stay beside the CAN capture', () {
    final capture = File('/tmp/atlas_capture_20260913_170000.log');
    expect(
      VoiceAnnotationCapture.audioFileForCapture(capture).path,
      '/tmp/atlas_capture_20260913_170000.voice.wav',
    );
    expect(
      VoiceAnnotationCapture.metadataFileForCapture(capture).path,
      '/tmp/atlas_capture_20260913_170000.voice.json',
    );
  });
}
