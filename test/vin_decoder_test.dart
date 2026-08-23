import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/src/research_models.dart';
import 'package:obd_atlas/src/vin_decoder.dart';

void main() {
  test('local decoder creates a detected make/model/year identity', () {
    final result = LocalVinDecoder.parseResult(
      vin: '1G1RA6E40DU100001',
      result: const {
        'make': 'CHEVROLET',
        'model': 'Volt',
        'modelYear': 2013,
        'generation': 'Gen 1',
        'powertrain': 'LUU / 1.4 L',
        'marketConfiguration': 'United States',
      },
    );
    expect(result.status, VehicleIdentityStatus.detected);
    expect(result.make, 'CHEVROLET');
    expect(result.model, 'Volt');
    expect(result.modelYear, 2013);
    expect(result.powertrain, contains('1.4 L'));
    expect(result.classified, isFalse);
  });
}
