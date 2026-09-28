import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/core/can_frame.dart';
import 'package:obd_atlas/core/fleetcarma_signal_candidates.dart';

void main() {
  test('parses FleetCarma candidate report and keeps candidate-only evidence', () {
    final report = FleetCarmaCandidateReport.tryParse(jsonEncode({
      'schema': 'atlas.fleetcarma-signal-correlation.v1',
      'mappingStatus': 'candidateOnly',
      'evidenceBoundary': 'test boundary',
      'sourceFiles': 22663,
      'canFrames': 14066934,
      'gpsSpeedSamples': 518504,
      'topSpeedCandidates': [
        {
          'bus': 1,
          'canIdHex': '3E9',
          'kind': 'u16be',
          'offset': 0,
          'speedCorrelation': 0.838752,
          'overlap': 2211110,
          'confidence': 'candidate',
        }
      ],
    }));

    expect(report, isNotNull);
    expect(report!.mappingStatus, 'candidateOnly');
    expect(report.topSpeedCandidates, hasLength(1));
    expect(report.topSpeedCandidates.single.canId, 0x3E9);
  });

  test('decodes u8 and u16 candidates from a CAN frame', () {
    final frame = CanFrame(
      timestamp: DateTime.utc(2026, 9, 28),
      id: 0x3E9,
      data: const [0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC],
    );

    const u8 = FleetCarmaSignalCandidate(
      bus: 1,
      canId: 0x3E9,
      kind: 'u8',
      offset: 4,
      speedCorrelation: 0.8,
      overlap: 100,
      confidence: 'candidate',
    );
    const be = FleetCarmaSignalCandidate(
      bus: 1,
      canId: 0x3E9,
      kind: 'u16be',
      offset: 0,
      speedCorrelation: 0.8,
      overlap: 100,
      confidence: 'candidate',
    );
    const le = FleetCarmaSignalCandidate(
      bus: 1,
      canId: 0x3E9,
      kind: 'u16le',
      offset: 0,
      speedCorrelation: 0.8,
      overlap: 100,
      confidence: 'candidate',
    );

    expect(u8.decode(frame), 0x9A);
    expect(be.decode(frame), 0x1234);
    expect(le.decode(frame), 0x3412);
  });

  test('live validation report remains candidate-only and groups speed steps', () {
    final workspace = FleetCarmaCandidateWorkspace.instance;
    expect(
      workspace.loadJsonText(jsonEncode({
        'schema': 'atlas.fleetcarma-signal-correlation.v1',
        'mappingStatus': 'candidateOnly',
        'topSpeedCandidates': [
          {
            'bus': 1,
            'canIdHex': '3E9',
            'kind': 'u16be',
            'offset': 0,
            'speedCorrelation': 0.838752,
            'overlap': 2211110,
            'confidence': 'candidate',
          }
        ],
      })),
      isTrue,
    );

    workspace.startValidation();
    workspace.markStep('10 mph', targetMph: 10);
    workspace.observe(CanFrame(
      timestamp: DateTime.utc(2026, 9, 28, 12),
      id: 0x3E9,
      data: const [0x00, 0x64, 0, 0, 0, 0, 0, 0],
      channel: 2,
    ));
    workspace.observe(CanFrame(
      timestamp: DateTime.utc(2026, 9, 28, 12, 0, 1),
      id: 0x3E9,
      data: const [0x00, 0x66, 0, 0, 0, 0, 0, 0],
      channel: 2,
    ));

    final output = workspace.finishValidation();

    expect(output['mappingStatus'], 'candidateOnly');
    expect(output['promotionAllowed'], isFalse);
    expect(output['sampleCount'], 2);
    final steps = output['steps'] as List<dynamic>;
    expect(steps, hasLength(1));
    expect((steps.single as Map<String, dynamic>)['rawMean'], 101.0);
  });
}
