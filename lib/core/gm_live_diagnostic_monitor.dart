import 'can_frame.dart';

/// Observation-only live GM diagnostic decoder used by the Windows capture UI.
///
/// The endpoint labels below retain their evidence source/confidence. Seeing a
/// frame on one of these IDs does not promote a candidate/legacy mapping to a
/// vehicle-confirmed mapping.
class GmDiagnosticEndpoint {
  const GmDiagnosticEndpoint({
    required this.module,
    required this.requestId,
    required this.responseId,
    this.streamId,
    required this.confidence,
    required this.source,
  });

  final String module;
  final int requestId;
  final int responseId;
  final int? streamId;
  final String confidence;
  final String source;
}

class GmLiveDiagnosticEvent {
  const GmLiveDiagnosticEvent({
    required this.timestamp,
    required this.channel,
    required this.canId,
    required this.module,
    required this.addressRole,
    required this.confidence,
    required this.source,
    this.direction,
    this.service,
    this.serviceId,
    this.did,
    this.negativeResponseCode,
    this.negativeResponseName,
    this.latencyMs,
    this.payloadHex,
  });

  final DateTime timestamp;
  final int channel;
  final int canId;
  final String module;
  final String addressRole;
  final String confidence;
  final String source;
  final String? direction;
  final String? service;
  final int? serviceId;
  final int? did;
  final int? negativeResponseCode;
  final String? negativeResponseName;
  final double? latencyMs;
  final String? payloadHex;

  String get canIdHex =>
      canId.toRadixString(16).toUpperCase().padLeft(3, '0');

  String get didHex => did == null
      ? '—'
      : '0x${did!.toRadixString(16).toUpperCase().padLeft(4, '0')}';

  String get summary {
    if (addressRole == 'stream') {
      return '$module • dynamic/data stream • 0x$canIdHex';
    }
    final parts = <String>[
      module,
      if (service != null) service!,
      if (did != null) didHex,
      if (negativeResponseName != null) negativeResponseName!,
      if (latencyMs != null) '${latencyMs!.toStringAsFixed(1)} ms',
    ];
    return parts.join(' • ');
  }
}

class GmLiveDiagnosticSnapshot {
  const GmLiveDiagnosticSnapshot({
    required this.events,
    required this.endpointFrameCount,
    required this.streamFrameCount,
  });

  final List<GmLiveDiagnosticEvent> events;
  final int endpointFrameCount;
  final int streamFrameCount;

  bool get hasTraffic => endpointFrameCount > 0 || streamFrameCount > 0;
}

class GmLiveDiagnosticMonitor {
  static const List<GmDiagnosticEndpoint> endpoints = <GmDiagnosticEndpoint>[
    GmDiagnosticEndpoint(
      module: 'K114B HPCM2',
      requestId: 0x7E4,
      responseId: 0x7EC,
      streamId: 0x5EC,
      confidence: 'communityCandidate',
      source: 'Gen-1 HPCM2 candidate transport catalog',
    ),
    GmDiagnosticEndpoint(
      module: 'ECM',
      requestId: 0x7E0,
      responseId: 0x7E8,
      streamId: 0x5E8,
      confidence: 'legacyReference',
      source: 'GM Simulation.txt reference',
    ),
    GmDiagnosticEndpoint(
      module: 'TCM',
      requestId: 0x7E2,
      responseId: 0x7EA,
      streamId: 0x5EA,
      confidence: 'legacyReference',
      source: 'GM Simulation.txt reference',
    ),
    GmDiagnosticEndpoint(
      module: 'Fuel Pump Module',
      requestId: 0x7E3,
      responseId: 0x7EB,
      streamId: 0x5EB,
      confidence: 'legacyReference',
      source: 'GM Simulation.txt reference',
    ),
    GmDiagnosticEndpoint(
      module: 'BCM',
      requestId: 0x244,
      responseId: 0x644,
      streamId: 0x544,
      confidence: 'legacyReference',
      source: 'GM Simulation.txt reference',
    ),
    GmDiagnosticEndpoint(
      module: 'Electronic Brake Control Module',
      requestId: 0x243,
      responseId: 0x643,
      streamId: 0x543,
      confidence: 'legacyReference',
      source: 'GM Simulation.txt reference',
    ),
    GmDiagnosticEndpoint(
      module: 'Electronic Power Steering Control Module',
      requestId: 0x24A,
      responseId: 0x64A,
      streamId: 0x54A,
      confidence: 'legacyReference',
      source: 'GM Simulation.txt reference',
    ),
    GmDiagnosticEndpoint(
      module: 'Immobilizer Control Module',
      requestId: 0x248,
      responseId: 0x648,
      streamId: 0x548,
      confidence: 'legacyReference',
      source: 'GM Simulation.txt reference',
    ),
    GmDiagnosticEndpoint(
      module: 'Instrument Cluster',
      requestId: 0x245,
      responseId: 0x645,
      streamId: 0x545,
      confidence: 'legacyReference',
      source: 'GM Simulation.txt reference',
    ),
    GmDiagnosticEndpoint(
      module: 'Keyless Entry Control Module',
      requestId: 0x258,
      responseId: 0x658,
      streamId: 0x558,
      confidence: 'legacyReference',
      source: 'GM Simulation.txt reference',
    ),
    GmDiagnosticEndpoint(
      module: 'Radio',
      requestId: 0x249,
      responseId: 0x649,
      streamId: 0x549,
      confidence: 'legacyReference',
      source: 'GM Simulation.txt reference',
    ),
    GmDiagnosticEndpoint(
      module: 'Inflatable Restraint Sensing and Diagnostic Module',
      requestId: 0x247,
      responseId: 0x647,
      streamId: 0x547,
      confidence: 'legacyReference',
      source: 'GM Simulation.txt reference',
    ),
  ];

  static const Map<int, String> _services = <int, String>{
    0x04: 'ClearDiagnosticInformationLegacy',
    0x09: 'RequestVehicleInformation',
    0x10: 'DiagnosticSessionControl',
    0x11: 'ECUReset',
    0x12: 'GMFailureRecord',
    0x18: 'ReadDTCInformationLegacy',
    0x22: 'ReadDataByIdentifier',
    0x27: 'SecurityAccess',
    0x28: 'CommunicationControl',
    0x2C: 'DynamicallyDefineDataIdentifier',
    0x2E: 'WriteDataByIdentifier',
    0x31: 'RoutineControl',
    0x34: 'RequestDownload',
    0x35: 'RequestUpload',
    0x36: 'TransferData',
    0x37: 'RequestTransferExit',
    0x3E: 'TesterPresent',
    0x85: 'ControlDTCSetting',
    0xA9: 'GMReadDTCInformation',
    0xAA: 'GMDynamicDataPacketControl',
  };

  static const Map<int, String> _nrcNames = <int, String>{
    0x10: 'generalReject',
    0x11: 'serviceNotSupported',
    0x12: 'subFunctionNotSupported',
    0x13: 'incorrectMessageLengthOrInvalidFormat',
    0x21: 'busyRepeatRequest',
    0x22: 'conditionsNotCorrect',
    0x24: 'requestSequenceError',
    0x31: 'requestOutOfRange',
    0x33: 'securityAccessDenied',
    0x35: 'invalidKey',
    0x36: 'exceedNumberOfAttempts',
    0x37: 'requiredTimeDelayNotExpired',
    0x70: 'uploadDownloadNotAccepted',
    0x71: 'transferDataSuspended',
    0x72: 'generalProgrammingFailure',
    0x73: 'wrongBlockSequenceCounter',
    0x78: 'responsePending',
  };

  static final Map<int, int> _positiveToRequest = _buildPositiveMap();

  static Map<int, int> _buildPositiveMap() {
    final result = <int, int>{
      0x44: 0x04,
      0x49: 0x09,
      0x52: 0x12,
      0x58: 0x18,
      0x81: 0xA9,
    };
    for (final sid in _services.keys) {
      final positive = sid + 0x40;
      if (positive <= 0xFF) result.putIfAbsent(positive, () => sid);
    }
    return result;
  }

  static GmLiveDiagnosticSnapshot analyze(
    Iterable<CanFrame> input, {
    int maxEvents = 30,
  }) {
    final frames = input.toList()
      ..sort((a, b) => a.timestamp.compareTo(b.timestamp));
    final byId = <int, GmDiagnosticEndpoint>{};
    final streamById = <int, GmDiagnosticEndpoint>{};
    for (final endpoint in endpoints) {
      byId[endpoint.requestId] = endpoint;
      byId[endpoint.responseId] = endpoint;
      if (endpoint.streamId != null) streamById[endpoint.streamId!] = endpoint;
    }

    final isoTp = _IsoTpLiveReassembler();
    final pending = <String, _PendingRequest>{};
    final events = <GmLiveDiagnosticEvent>[];
    var endpointFrameCount = 0;
    var streamFrameCount = 0;

    for (final frame in frames) {
      final streamEndpoint = streamById[frame.id];
      if (streamEndpoint != null) {
        streamFrameCount++;
        events.add(GmLiveDiagnosticEvent(
          timestamp: frame.timestamp,
          channel: frame.channel,
          canId: frame.id,
          module: streamEndpoint.module,
          addressRole: 'stream',
          confidence: streamEndpoint.confidence,
          source: streamEndpoint.source,
          payloadHex: _hex(frame.data),
        ));
        continue;
      }

      final endpoint = byId[frame.id];
      if (endpoint == null) continue;
      endpointFrameCount++;
      final role = frame.id == endpoint.requestId ? 'request' : 'response';

      // 0x7Ex endpoints use classic ISO-TP. Legacy 0x2xx/0x6xx endpoints in
      // Simulation.txt are unframed GM diagnostic examples.
      final useIsoTp = endpoint.requestId >= 0x700;
      final payloads = useIsoTp
          ? isoTp.push(frame)
          : <_Payload>[_Payload(frame.timestamp, frame.channel, frame.id, List<int>.from(frame.data))];

      for (final payload in payloads) {
        if (payload.data.isEmpty) continue;
        final decoded = _decode(payload.data, role);
        if (decoded == null) continue;

        double? latencyMs;
        final key = '${payload.channel}:${endpoint.requestId}:${decoded.serviceId}:${decoded.did ?? -1}';
        if (role == 'request') {
          pending[key] = _PendingRequest(payload.timestamp, decoded.serviceId, decoded.did);
        } else {
          _PendingRequest? request = pending[key];
          request ??= _mostRecentCompatible(pending, payload.channel, endpoint, decoded);
          if (request != null) {
            latencyMs = payload.timestamp.difference(request.timestamp).inMicroseconds / 1000.0;
            if (decoded.negativeResponseCode != 0x78) {
              pending.removeWhere((_, value) => identical(value, request));
            }
          }
        }

        events.add(GmLiveDiagnosticEvent(
          timestamp: payload.timestamp,
          channel: payload.channel,
          canId: payload.canId,
          module: endpoint.module,
          addressRole: role,
          confidence: endpoint.confidence,
          source: endpoint.source,
          direction: role,
          service: decoded.service,
          serviceId: decoded.serviceId,
          did: decoded.did,
          negativeResponseCode: decoded.negativeResponseCode,
          negativeResponseName: decoded.negativeResponseName,
          latencyMs: latencyMs,
          payloadHex: _hex(payload.data),
        ));
      }
    }

    final recent = events.length <= maxEvents
        ? events.reversed.toList(growable: false)
        : events.sublist(events.length - maxEvents).reversed.toList(growable: false);
    return GmLiveDiagnosticSnapshot(
      events: recent,
      endpointFrameCount: endpointFrameCount,
      streamFrameCount: streamFrameCount,
    );
  }

  static _PendingRequest? _mostRecentCompatible(
    Map<String, _PendingRequest> pending,
    int channel,
    GmDiagnosticEndpoint endpoint,
    _DecodedDiagnostic decoded,
  ) {
    _PendingRequest? best;
    for (final entry in pending.entries) {
      if (!entry.key.startsWith('$channel:${endpoint.requestId}:')) continue;
      final candidate = entry.value;
      if (candidate.serviceId != decoded.serviceId) continue;
      if (decoded.did != null && candidate.did != null && decoded.did != candidate.did) continue;
      if (best == null || candidate.timestamp.isAfter(best.timestamp)) best = candidate;
    }
    return best;
  }

  static _DecodedDiagnostic? _decode(List<int> payload, String role) {
    if (payload.isEmpty) return null;
    final sid = payload[0];
    if (sid == 0x7F && payload.length >= 3) {
      final requested = payload[1];
      final nrc = payload[2];
      return _DecodedDiagnostic(
        serviceId: requested,
        service: _services[requested] ?? 'Service0x${requested.toRadixString(16).toUpperCase()}',
        negativeResponseCode: nrc,
        negativeResponseName: _nrcNames[nrc] ?? 'NRC 0x${nrc.toRadixString(16).toUpperCase()}',
      );
    }

    int serviceId;
    if (role == 'request' && _services.containsKey(sid)) {
      serviceId = sid;
    } else if (role == 'response' && _positiveToRequest.containsKey(sid)) {
      serviceId = _positiveToRequest[sid]!;
    } else {
      return null;
    }

    int? did;
    if ((serviceId == 0x22 || serviceId == 0x2E) && payload.length >= 3) {
      did = (payload[1] << 8) | payload[2];
    }
    return _DecodedDiagnostic(
      serviceId: serviceId,
      service: _services[serviceId]!,
      did: did,
    );
  }

  static String _hex(Iterable<int> bytes) => bytes
      .map((value) => value.toRadixString(16).toUpperCase().padLeft(2, '0'))
      .join(' ');
}

class _DecodedDiagnostic {
  const _DecodedDiagnostic({
    required this.serviceId,
    required this.service,
    this.did,
    this.negativeResponseCode,
    this.negativeResponseName,
  });

  final int serviceId;
  final String service;
  final int? did;
  final int? negativeResponseCode;
  final String? negativeResponseName;
}

class _PendingRequest {
  const _PendingRequest(this.timestamp, this.serviceId, this.did);

  final DateTime timestamp;
  final int serviceId;
  final int? did;
}

class _Payload {
  const _Payload(this.timestamp, this.channel, this.canId, this.data);

  final DateTime timestamp;
  final int channel;
  final int canId;
  final List<int> data;
}

class _IsoTpLiveReassembler {
  final Map<String, _IsoTpState> _active = <String, _IsoTpState>{};

  List<_Payload> push(CanFrame frame) {
    if (frame.data.isEmpty) return const <_Payload>[];
    final pciType = frame.data[0] >> 4;
    final key = '${frame.channel}:${frame.id}';

    if (pciType == 0) {
      final length = frame.data[0] & 0x0F;
      if (length <= 0 || length > frame.data.length - 1) return const <_Payload>[];
      return <_Payload>[
        _Payload(
          frame.timestamp,
          frame.channel,
          frame.id,
          frame.data.sublist(1, 1 + length),
        ),
      ];
    }

    if (pciType == 1 && frame.data.length >= 2) {
      final length = ((frame.data[0] & 0x0F) << 8) | frame.data[1];
      if (length <= 6) return const <_Payload>[];
      final state = _IsoTpState(
        timestamp: frame.timestamp,
        channel: frame.channel,
        canId: frame.id,
        length: length,
        nextSequence: 1,
        data: <int>[...frame.data.skip(2)],
      );
      _active[key] = state;
      if (state.data.length >= length) {
        _active.remove(key);
        return <_Payload>[
          _Payload(state.timestamp, state.channel, state.canId, state.data.sublist(0, length)),
        ];
      }
      return const <_Payload>[];
    }

    if (pciType == 2) {
      final state = _active[key];
      if (state == null) return const <_Payload>[];
      final sequence = frame.data[0] & 0x0F;
      if (sequence != state.nextSequence) {
        _active.remove(key);
        return const <_Payload>[];
      }
      state.data.addAll(frame.data.skip(1));
      state.nextSequence = (state.nextSequence + 1) & 0x0F;
      if (state.data.length >= state.length) {
        _active.remove(key);
        return <_Payload>[
          _Payload(
            state.timestamp,
            state.channel,
            state.canId,
            state.data.sublist(0, state.length),
          ),
        ];
      }
    }

    // Flow-control and ordinary broadcast frames are not diagnostic payloads.
    return const <_Payload>[];
  }
}

class _IsoTpState {
  _IsoTpState({
    required this.timestamp,
    required this.channel,
    required this.canId,
    required this.length,
    required this.nextSequence,
    required this.data,
  });

  final DateTime timestamp;
  final int channel;
  final int canId;
  final int length;
  int nextSequence;
  final List<int> data;
}
