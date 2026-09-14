/// Capture-derived Gen-1 Chevrolet Volt HPCM2 DC-link/output-voltage candidate.
///
/// A controlled 2026-09-14 startup capture correlated CAN 0x228 bytes 2-3
/// (big-endian) with the vehicle-confirmed HPCM2 precharge sequence:
///
///   hvOff / first-main: ~4.1 V
///   early precharge:    ~68.1 V
///   late precharge:     ~301.7 V
///   HV established:     ~308.1 V
///
/// The scaling below (0.0125 V/count) is capture-derived and remains a
/// high-confidence candidate until independently validated against a service
/// parameter or controlled external voltage measurement.
class Gen1Hpcm2DcLinkVoltageDecoder {
  static const int canId = 0x228;
  static const int minimumPayloadLength = 4;
  static const double voltsPerCount = 0.0125;

  static double? decode({
    required int frameCanId,
    required List<int> data,
  }) {
    if (frameCanId != canId || data.length < minimumPayloadLength) {
      return null;
    }

    final raw = ((data[2] & 0xFF) << 8) | (data[3] & 0xFF);
    return raw * voltsPerCount;
  }
}
