enum ObdProtocol { iso15765, iso14230, iso9141, j1850Vpw, j1850Pwm, unknown }

final class EcuObservation {
  const EcuObservation({
    required this.requestId,
    required this.responseId,
    required this.protocol,
    required this.firstSeenUtc,
    required this.evidenceFrameCount,
  });

  final String requestId;
  final String responseId;
  final ObdProtocol protocol;
  final DateTime firstSeenUtc;
  final int evidenceFrameCount;
}

final class CaptureManifest {
  const CaptureManifest({
    required this.sessionId,
    required this.startedUtc,
    required this.adapterIdentity,
    required this.protocol,
    required this.validFrames,
    required this.malformedFrames,
    required this.bufferOverflows,
    required this.writeErrors,
    required this.operatorApprovedUpload,
  });

  final String sessionId;
  final DateTime startedUtc;
  final String adapterIdentity;
  final ObdProtocol protocol;
  final int validFrames;
  final int malformedFrames;
  final int bufferOverflows;
  final int writeErrors;
  final bool operatorApprovedUpload;

  bool get integrityPassed =>
      validFrames > 0 && malformedFrames == 0 && bufferOverflows == 0 && writeErrors == 0;
}
