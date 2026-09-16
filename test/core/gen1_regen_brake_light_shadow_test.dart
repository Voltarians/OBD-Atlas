import 'package:flutter_test/flutter_test.dart';
import 'package:obd_atlas/core/gen1_regen_brake_light_shadow.dart';

void main() {
  group('Gen1RegenBrakeLightShadowController', () {
    test('does not request from deceleration alone', () {
      final controller = Gen1RegenBrakeLightShadowController();

      final decision = controller.update(
        vehicleSpeedMps: 10,
        decelerationMps2: 2.0,
        regenConfirmed: false,
        factoryBrakeApplied: false,
      );

      expect(decision.requested, isFalse);
      expect(decision.reason, Gen1RegenBrakeLightReason.regenNotConfirmed);
    });

    test('engages at the configured regen deceleration threshold', () {
      final controller = Gen1RegenBrakeLightShadowController();

      final decision = controller.update(
        vehicleSpeedMps: 10,
        decelerationMps2: 1.3,
        regenConfirmed: true,
        factoryBrakeApplied: false,
      );

      expect(decision.requested, isTrue);
      expect(decision.reason, Gen1RegenBrakeLightReason.regenDeceleration);
    });

    test('uses hysteresis to prevent flicker', () {
      final controller = Gen1RegenBrakeLightShadowController();

      controller.update(
        vehicleSpeedMps: 10,
        decelerationMps2: 1.5,
        regenConfirmed: true,
        factoryBrakeApplied: false,
      );

      final hold = controller.update(
        vehicleSpeedMps: 10,
        decelerationMps2: 0.9,
        regenConfirmed: true,
        factoryBrakeApplied: false,
      );
      expect(hold.requested, isTrue);
      expect(hold.reason, Gen1RegenBrakeLightReason.hysteresisHold);

      final release = controller.update(
        vehicleSpeedMps: 10,
        decelerationMps2: 0.69,
        regenConfirmed: true,
        factoryBrakeApplied: false,
      );
      expect(release.requested, isFalse);
      expect(release.reason, Gen1RegenBrakeLightReason.belowThreshold);
    });

    test('factory brake path remains authoritative', () {
      final controller = Gen1RegenBrakeLightShadowController();

      final decision = controller.update(
        vehicleSpeedMps: 10,
        decelerationMps2: 2.0,
        regenConfirmed: true,
        factoryBrakeApplied: true,
      );

      expect(decision.requested, isFalse);
      expect(decision.reason, Gen1RegenBrakeLightReason.factoryBrakeApplied);
    });

    test('suppresses request below minimum speed', () {
      final controller = Gen1RegenBrakeLightShadowController();

      final decision = controller.update(
        vehicleSpeedMps: 1.0,
        decelerationMps2: 2.0,
        regenConfirmed: true,
        factoryBrakeApplied: false,
      );

      expect(decision.requested, isFalse);
      expect(decision.reason, Gen1RegenBrakeLightReason.belowMinimumSpeed);
    });

    test('fails off on invalid data', () {
      final controller = Gen1RegenBrakeLightShadowController();

      controller.update(
        vehicleSpeedMps: 10,
        decelerationMps2: 2.0,
        regenConfirmed: true,
        factoryBrakeApplied: false,
      );

      final decision = controller.update(
        vehicleSpeedMps: double.nan,
        decelerationMps2: 2.0,
        regenConfirmed: true,
        factoryBrakeApplied: false,
      );

      expect(decision.requested, isFalse);
      expect(decision.reason, Gen1RegenBrakeLightReason.invalidInput);
    });

    test('reset clears an active shadow request', () {
      final controller = Gen1RegenBrakeLightShadowController();

      controller.update(
        vehicleSpeedMps: 10,
        decelerationMps2: 2.0,
        regenConfirmed: true,
        factoryBrakeApplied: false,
      );
      expect(controller.requested, isTrue);

      controller.reset();
      expect(controller.requested, isFalse);
    });
  });
}
