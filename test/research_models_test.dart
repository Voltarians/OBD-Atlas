import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/src/research_models.dart';

void main() {
  test('capture integrity fails closed', () {
    final good = CaptureManifest(
      sessionId: 'test',
      startedUtc: DateTime.utc(2026),
      adapterIdentity: 'OBDLink MX+',
      protocol: ObdProtocol.iso15765,
      validFrames: 3000,
      malformedFrames: 0,
      bufferOverflows: 0,
      writeErrors: 0,
      operatorApprovedUpload: false,
    );
    expect(good.integrityPassed, isTrue);
    expect(good.operatorApprovedUpload, isFalse);
  });
}
