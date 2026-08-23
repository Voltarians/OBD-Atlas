import 'dart:convert';

import 'package:crypto/crypto.dart';

enum ObdProtocol { iso15765, iso14230, iso9141, j1850Vpw, j1850Pwm, unknown }
enum VehicleIdentityStatus { unclassified, detected, operatorConfirmed }

final class VinCodec {
  const VinCodec._();

  static final _format = RegExp(r'^[A-HJ-NPR-Z0-9]{17}$');
  static const _weights = <int>[8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2];
  static const _values = <String, int>{
    'A': 1, 'B': 2, 'C': 3, 'D': 4, 'E': 5, 'F': 6, 'G': 7, 'H': 8,
    'J': 1, 'K': 2, 'L': 3, 'M': 4, 'N': 5, 'P': 7, 'R': 9,
    'S': 2, 'T': 3, 'U': 4, 'V': 5, 'W': 6, 'X': 7, 'Y': 8, 'Z': 9,
    '0': 0, '1': 1, '2': 2, '3': 3, '4': 4,
    '5': 5, '6': 6, '7': 7, '8': 8, '9': 9,
  };

  static String normalize(String vin) => vin.trim().toUpperCase();
  static bool formatValid(String vin) => _format.hasMatch(normalize(vin));

  static bool checkDigitValid(String vin) {
    final normalized = normalize(vin);
    if (!formatValid(normalized)) return false;
    var total = 0;
    for (var index = 0; index < normalized.length; index++) {
      total += _values[normalized[index]]! * _weights[index];
    }
    final expected = total % 11 == 10 ? 'X' : (total % 11).toString();
    return normalized[8] == expected;
  }

  static String privacyHash({required String vin, required String secret}) {
    if (secret.isEmpty) throw ArgumentError.value(secret, 'secret', 'must not be empty');
    final normalized = normalize(vin);
    if (!formatValid(normalized)) throw FormatException('VIN must contain 17 valid characters');
    return Hmac(sha256, utf8.encode(secret)).convert(utf8.encode(normalized)).toString();
  }
}

final class VehicleIdentity {
  const VehicleIdentity({
    this.vin,
    this.make,
    this.model,
    this.modelYear,
    this.generation,
    this.powertrain,
    this.marketConfiguration,
    this.vinHash,
    this.status = VehicleIdentityStatus.unclassified,
    this.operatorConfirmedUtc,
  });

  final String? vin;
  final String? make;
  final String? model;
  final int? modelYear;
  final String? generation;
  final String? powertrain;
  final String? marketConfiguration;
  final String? vinHash;
  final VehicleIdentityStatus status;
  final DateTime? operatorConfirmedUtc;

  bool get hasClassification =>
      (make?.trim().isNotEmpty ?? false) &&
      (model?.trim().isNotEmpty ?? false) &&
      modelYear != null;

  bool get classified =>
      status == VehicleIdentityStatus.operatorConfirmed &&
      operatorConfirmedUtc != null &&
      hasClassification &&
      (vinHash?.isNotEmpty ?? false);

  String get classificationKey {
    if (!classified) return 'UNCLASSIFIED';
    String slug(String value) => value
        .trim()
        .toLowerCase()
        .replaceAll(RegExp(r'[^a-z0-9]+'), '-')
        .replaceAll(RegExp(r'^-|-$'), '');
    return '${slug(make!)}/${slug(model!)}/$modelYear';
  }
}

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
    required this.vehicleIdentity,
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
  final VehicleIdentity vehicleIdentity;
  final int validFrames;
  final int malformedFrames;
  final int bufferOverflows;
  final int writeErrors;
  final bool operatorApprovedUpload;

  bool get integrityPassed =>
      validFrames > 0 && malformedFrames == 0 && bufferOverflows == 0 && writeErrors == 0;

  String get storagePartition =>
      vehicleIdentity.classified ? vehicleIdentity.classificationKey : 'UNCLASSIFIED';
}
