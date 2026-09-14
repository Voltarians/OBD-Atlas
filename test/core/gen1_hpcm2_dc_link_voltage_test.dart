import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/core/gen1_hpcm2_dc_link_voltage.dart';

void main() {
  group('Gen1Hpcm2DcLinkVoltageDecoder', () {
    test('decodes the controlled startup ramp samples', () {
      expect(
        Gen1Hpcm2DcLinkVoltageDecoder.decode(
          frameCanId: 0x228,
          data: const [0x00, 0x4F, 0x01, 0x49],
        ),
        closeTo(4.1125, 0.0001),
      );
      expect(
        Gen1Hpcm2DcLinkVoltageDecoder.decode(
          frameCanId: 0x228,
          data: const [0x00, 0x4F, 0x15, 0x49],
        ),
        closeTo(68.1125, 0.0001),
      );
      expect(
        Gen1Hpcm2DcLinkVoltageDecoder.decode(
          frameCanId: 0x228,
          data: const [0x00, 0x4F, 0x5E, 0x49],
        ),
        closeTo(301.7125, 0.0001),
      );
      expect(
        Gen1Hpcm2DcLinkVoltageDecoder.decode(
          frameCanId: 0x228,
          data: const [0x00, 0x4F, 0x60, 0x49],
        ),
        closeTo(308.1125, 0.0001),
      );
    });

    test('rejects the wrong CAN id or short payload', () {
      expect(
        Gen1Hpcm2DcLinkVoltageDecoder.decode(
          frameCanId: 0x229,
          data: const [0x00, 0x4F, 0x60, 0x49],
        ),
        isNull,
      );
      expect(
        Gen1Hpcm2DcLinkVoltageDecoder.decode(
          frameCanId: 0x228,
          data: const [0x00, 0x4F, 0x60],
        ),
        isNull,
      );
    });
  });
}
