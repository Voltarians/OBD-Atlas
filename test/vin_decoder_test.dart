import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/src/research_models.dart';
import 'package:obd_atlas/src/vin_decoder.dart';

void main() {
  test('vPIC response creates a detected make/model/year identity', () {
    const body = '''
{"Results":[{"Make":"CHEVROLET","Model":"Volt","ModelYear":"2013",
"EngineModel":"LUU","DisplacementL":"1.4","Trim":"Base",
"BodyClass":"Hatchback/Liftback/Notchback","VehicleType":"PASSENGER CAR",
"PlantCountry":"UNITED STATES (USA)"}]}
''';
    final result = NhtsaVpicDecoder.parseResponse(
      vin: '1G1RA6E40DU100001',
      body: body,
    );
    expect(result.status, VehicleIdentityStatus.detected);
    expect(result.make, 'CHEVROLET');
    expect(result.model, 'Volt');
    expect(result.modelYear, 2013);
    expect(result.powertrain, contains('1.4 L'));
    expect(result.classified, isFalse);
  });
}
