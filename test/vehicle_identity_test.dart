import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/core/local_store.dart';
import 'package:obd_atlas/core/vehicle_identity.dart';

void main() {
  test('model year determines Volt generation', () {
    expect(VehicleIdentity.selected(make: 'Chevy', model: 'Volt', modelYear: 2015).vehicleType, 'chevrolet-volt-gen1');
    expect(VehicleIdentity.selected(make: 'Chevrolet', model: 'Volt', modelYear: 2016).vehicleType, 'chevrolet-volt-gen2');
    expect(VehicleIdentity.selected(make: 'Cadillac', model: 'ELR', modelYear: 2016).generation, 1);
    expect(() => VehicleIdentity.selected(make: 'Chevrolet', model: 'Volt', modelYear: 2016, generation: 1), throwsFormatException);
  });

  test('unrelated vehicles remain separate and VIN is not exported', () {
    final vehicle = VehicleIdentity.selected(make: 'Toyota', model: 'Prius', modelYear: 2015, vin: '1G1RA6E43DU100001');
    expect(vehicle.vehicleType, 'toyota-prius');
    expect(vehicle.toJson().containsKey('vin'), isFalse);
    expect(const VehicleRoutingPolicy().allowsPublicType(vehicle), isFalse);
  });

  test('capture identity is frozen and a final manifest hashes raw bytes', () async {
    final temp = await Directory.systemTemp.createTemp('atlas-identity-');
    addTearDown(() => temp.delete(recursive: true));
    final store = AtlasLocalStore.forDirectory(temp);
    await store.selectVehicle(VehicleIdentity.selected(make: 'Chevrolet', model: 'Volt', modelYear: 2013));
    final file = await store.createCaptureFile();
    final raw = '(1780000000.000001) can0 7E4#0210010000000000\n(1780000000.000002) can1 123#AABB\n';
    await file.writeAsString(raw, flush: true);
    await store.selectVehicle(VehicleIdentity.selected(make: 'Toyota', model: 'Prius', modelYear: 2015));
    await store.completeCapture(file, 2, null);
    final manifest = jsonDecode(await store.manifestFor(file).readAsString()) as Map<String, dynamic>;
    expect((manifest['vehicle'] as Map)['vehicle_type'], 'chevrolet-volt-gen1');
    expect((manifest['vehicle'] as Map)['model_year'], 2013);
    expect((manifest['capture_status'] as Map)['total_frames'], 2);
    expect((manifest['capture_status'] as Map)['complete_shutdown'], isTrue);
    expect((manifest['buses'] as List).length, 2);
    expect(((manifest['files'] as List).first as Map)['sha256'], sha256.convert(utf8.encode(raw)).toString());
    expect(await file.readAsString(), raw);
    expect(file.path, contains('chevrolet-volt-gen1'));
  });
}
