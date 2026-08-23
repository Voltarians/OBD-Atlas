import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/src/research_models.dart';

void main() {
  test('VIN validation rejects ambiguous characters and verifies check digit', () {
    expect(VinCodec.formatValid('1M8GDM9AXKP042788'), isTrue);
    expect(VinCodec.checkDigitValid('1M8GDM9AXKP042788'), isTrue);
    expect(VinCodec.formatValid('1M8GDM9AOKP042788'), isFalse);
  });

  test('VIN privacy hash is stable only with the same installation secret', () {
    final first = VinCodec.privacyHash(vin: '1M8GDM9AXKP042788', secret: 'shop-a');
    final repeated = VinCodec.privacyHash(vin: '1m8gdm9axkp042788', secret: 'shop-a');
    final otherShop = VinCodec.privacyHash(vin: '1M8GDM9AXKP042788', secret: 'shop-b');
    expect(first, repeated);
    expect(first, isNot(otherShop));
  });

  test('capture remains UNCLASSIFIED until operator confirmation', () {
    const uncertain = VehicleIdentity(
      vinHash: 'hash',
      make: 'Chevrolet',
      model: 'Volt',
      modelYear: 2013,
      status: VehicleIdentityStatus.detected,
    );
    final manifest = CaptureManifest(
      sessionId: 'test',
      startedUtc: DateTime.utc(2026),
      adapterIdentity: 'OBDLink MX+',
      protocol: ObdProtocol.iso15765,
      vehicleIdentity: uncertain,
      validFrames: 3000,
      malformedFrames: 0,
      bufferOverflows: 0,
      writeErrors: 0,
      operatorApprovedUpload: false,
    );
    expect(manifest.integrityPassed, isTrue);
    expect(manifest.storagePartition, 'UNCLASSIFIED');
  });

  test('confirmed identity receives a make/model/year partition', () {
    final confirmed = VehicleIdentity(
      vinHash: 'hash',
      make: 'Chevrolet',
      model: 'Volt',
      modelYear: 2013,
      generation: 'Gen 1',
      status: VehicleIdentityStatus.operatorConfirmed,
      operatorConfirmedUtc: DateTime.utc(2026),
    );
    expect(confirmed.classified, isTrue);
    expect(confirmed.classificationKey, 'chevrolet/volt/2013');
  });
}
