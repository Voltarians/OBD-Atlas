import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/core/vehicle_signal_catalog.dart';

void main() {
  test('Gen-1 Volt catalog is valid and preserves confidence', () {
    final source =
        File('assets/signals/chevrolet_volt_gen1.json').readAsStringSync();
    final catalog = VehicleSignalCatalog.fromJson(source);

    expect(catalog.catalogId, 'chevrolet-volt-gen1');
    expect(catalog.signals, hasLength(31));
    expect(
      catalog.signals
          .where((signal) => signal['status'] == 'candidate')
          .map((signal) => signal['name']),
      containsAll(<String>[
        'brakePressureCandidate',
        'acceleratorPositionCandidate',
        'hazardFlashCandidate',
        'hvBatteryCurrentCandidate',
        'packCurrentCandidate',
      ]),
    );
    expect(
      catalog.signals
          .where((signal) => signal['status'] == 'communityCorroborated')
          .map((signal) => signal['name']),
      containsAll(<String>[
        'chargerHvCurrent',
        'chargerHvVoltage',
        'chargerLvCurrent',
        'chargerLvVoltage',
        'chargerRequestedCurrent',
        'chargerRequestedVoltage',
        'chargerMode',
      ]),
    );
    expect(
      catalog.signals
          .where((signal) => signal['status'] == 'confirmed')
          .map((signal) => signal['name']),
      containsAll(<String>[
        'brakePedalPressed',
        'brakePedalPosition',
        'systemPowerMode',
        'hvBatteryVoltage',
        'packVoltage',
      ]),
    );
  });
}
