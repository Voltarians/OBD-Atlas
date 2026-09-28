import 'dart:typed_data';

import 'can_frame.dart';

class FleetCarmaConfiguredId {
  const FleetCarmaConfiguredId({
    required this.bus,
    required this.canId,
    required this.configValue,
    required this.offset,
  });

  final int bus;
  final int canId;
  final int configValue;
  final int offset;
}

class FleetCarmaGpsRecord {
  const FleetCarmaGpsRecord({
    required this.loggerTimestampMs,
    required this.sentence,
    required this.offset,
  });

  final int loggerTimestampMs;
  final String sentence;
  final int offset;
}

class FleetCarmaCanRecord {
  const FleetCarmaCanRecord({
    required this.loggerTimestampMs,
    required this.bus,
    required this.canId,
    required this.data,
    required this.offset,
  });

  final int loggerTimestampMs;
  final int bus;
  final int canId;
  final List<int> data;
  final int offset;

  CanFrame toCanFrame({
    required DateTime anchorTime,
    required int anchorLoggerTimestampMs,
  }) {
    final timestamp = anchorTime.add(
      Duration(milliseconds: loggerTimestampMs - anchorLoggerTimestampMs),
    );
    return CanFrame(
      timestamp: timestamp,
      id: canId,
      data: data,
      channel: bus,
      bus: 'can${bus - 1}',
    );
  }

  String toRelativeCandump() {
    final seconds = loggerTimestampMs / 1000.0;
    final idHex = canId.toRadixString(16).toUpperCase().padLeft(3, '0');
    final payload = data
        .map((byte) => byte.toRadixString(16).toUpperCase().padLeft(2, '0'))
        .join();
    return '(${seconds.toStringAsFixed(6)}) can${bus - 1} $idHex#$payload';
  }
}

class FleetCarmaImportResult {
  const FleetCarmaImportResult({
    required this.canRecords,
    required this.gpsRecords,
    required this.configuredIds,
    required this.malformedTail,
    required this.bytesConsumed,
  });

  final List<FleetCarmaCanRecord> canRecords;
  final List<FleetCarmaGpsRecord> gpsRecords;
  final List<FleetCarmaConfiguredId> configuredIds;
  final bool malformedTail;
  final int bytesConsumed;

  int get frameCount => canRecords.length;
}

class FleetCarmaC5Importer {
  const FleetCarmaC5Importer();

  static const int configuredIdType = 0x01;
  static const int canFrameType = 0x05;
  static const int gpsType = 0x24;

  FleetCarmaImportResult decode(Uint8List bytes) {
    final canRecords = <FleetCarmaCanRecord>[];
    final gpsRecords = <FleetCarmaGpsRecord>[];
    final configuredIds = <FleetCarmaConfiguredId>[];

    var offset = 0;
    var malformedTail = false;

    while (offset + 2 <= bytes.length) {
      final type = bytes[offset];
      final length = bytes[offset + 1];
      final payloadStart = offset + 2;
      final end = payloadStart + length;

      if (end > bytes.length) {
        malformedTail = true;
        break;
      }

      if (type == configuredIdType && length == 5) {
        final p = ByteData.sublistView(bytes, payloadStart, end);
        configuredIds.add(
          FleetCarmaConfiguredId(
            bus: p.getUint8(0),
            canId: p.getUint16(1, Endian.little),
            configValue: p.getInt16(3, Endian.little),
            offset: offset,
          ),
        );
      } else if (type == canFrameType && length == 16) {
        final p = ByteData.sublistView(bytes, payloadStart, end);
        final bus = p.getUint8(0);
        final canId = p.getUint16(1, Endian.little);
        final dlc = p.getUint8(3);

        if (bus >= 1 && bus <= 5 && canId <= 0x7FF && dlc <= 8) {
          canRecords.add(
            FleetCarmaCanRecord(
              loggerTimestampMs: p.getUint32(4, Endian.little),
              bus: bus,
              canId: canId,
              data: bytes.sublist(payloadStart + 8, payloadStart + 8 + dlc),
              offset: offset,
            ),
          );
        }
      } else if (type == gpsType && length >= 4) {
        final p = ByteData.sublistView(bytes, payloadStart, end);
        final textBytes = bytes.sublist(payloadStart + 4, end);
        final sentence = String.fromCharCodes(textBytes)
            .replaceAll('\u0000', '')
            .trim();
        if (sentence.isNotEmpty) {
          gpsRecords.add(
            FleetCarmaGpsRecord(
              loggerTimestampMs: p.getUint32(0, Endian.little),
              sentence: sentence,
              offset: offset,
            ),
          );
        }
      }

      offset = end;
    }

    if (offset != bytes.length && !malformedTail) {
      malformedTail = true;
    }

    return FleetCarmaImportResult(
      canRecords: canRecords,
      gpsRecords: gpsRecords,
      configuredIds: configuredIds,
      malformedTail: malformedTail,
      bytesConsumed: offset,
    );
  }
}
