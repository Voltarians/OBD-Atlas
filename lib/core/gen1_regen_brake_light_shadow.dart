/// Software-only Gen-1 Chevrolet Volt regenerative deceleration brake-light
/// decision logic.
///
/// This controller MUST NOT directly actuate vehicle lamps. It exists to
/// generate and log a shadow `regen_brake_light_request` while the required
/// vehicle signals and thresholds are validated.
///
/// Deceleration is supplied as a positive magnitude in m/s^2. The caller is
/// responsible for converting the vehicle's longitudinal-acceleration signal
/// into that convention.
class Gen1RegenBrakeLightConfig {
  const Gen1RegenBrakeLightConfig({
    this.engageDecelerationMps2 = 1.3,
    this.releaseDecelerationMps2 = 0.7,
    this.minimumVehicleSpeedMps = 1.4,
  }) : assert(engageDecelerationMps2 > releaseDecelerationMps2),
       assert(releaseDecelerationMps2 >= 0),
       assert(minimumVehicleSpeedMps >= 0);

  /// Request the supplemental brake-light state at or above this deceleration.
  final double engageDecelerationMps2;

  /// Once active, remain active until deceleration falls below this value.
  final double releaseDecelerationMps2;

  /// Approximately 5 km/h by default. Below this, the shadow request is off.
  final double minimumVehicleSpeedMps;
}

enum Gen1RegenBrakeLightReason {
  belowThreshold,
  hysteresisHold,
  regenDeceleration,
  regenNotConfirmed,
  factoryBrakeApplied,
  belowMinimumSpeed,
  invalidInput,
}

class Gen1RegenBrakeLightDecision {
  const Gen1RegenBrakeLightDecision({
    required this.requested,
    required this.reason,
    required this.decelerationMps2,
    required this.vehicleSpeedMps,
  });

  /// Shadow-only request. No physical output is permitted from this class.
  final bool requested;
  final Gen1RegenBrakeLightReason reason;
  final double decelerationMps2;
  final double vehicleSpeedMps;
}

class Gen1RegenBrakeLightShadowController {
  Gen1RegenBrakeLightShadowController({
    this.config = const Gen1RegenBrakeLightConfig(),
  });

  final Gen1RegenBrakeLightConfig config;
  bool _requested = false;

  bool get requested => _requested;

  void reset() {
    _requested = false;
  }

  Gen1RegenBrakeLightDecision update({
    required double vehicleSpeedMps,
    required double decelerationMps2,
    required bool regenConfirmed,
    required bool factoryBrakeApplied,
    bool inputValid = true,
  }) {
    if (!inputValid ||
        !vehicleSpeedMps.isFinite ||
        !decelerationMps2.isFinite ||
        vehicleSpeedMps < 0 ||
        decelerationMps2 < 0) {
      _requested = false;
      return _decision(
        Gen1RegenBrakeLightReason.invalidInput,
        vehicleSpeedMps,
        decelerationMps2,
      );
    }

    // The stock brake-pedal/BCM path remains authoritative. This shadow logic
    // only studies supplemental activation when the pedal is not requesting the
    // factory stop lamps.
    if (factoryBrakeApplied) {
      _requested = false;
      return _decision(
        Gen1RegenBrakeLightReason.factoryBrakeApplied,
        vehicleSpeedMps,
        decelerationMps2,
      );
    }

    if (vehicleSpeedMps < config.minimumVehicleSpeedMps) {
      _requested = false;
      return _decision(
        Gen1RegenBrakeLightReason.belowMinimumSpeed,
        vehicleSpeedMps,
        decelerationMps2,
      );
    }

    // Never infer intentional braking from acceleration data alone. Regen must
    // be independently confirmed by a validated torque/current/state signal.
    if (!regenConfirmed) {
      _requested = false;
      return _decision(
        Gen1RegenBrakeLightReason.regenNotConfirmed,
        vehicleSpeedMps,
        decelerationMps2,
      );
    }

    if (_requested) {
      if (decelerationMps2 < config.releaseDecelerationMps2) {
        _requested = false;
        return _decision(
          Gen1RegenBrakeLightReason.belowThreshold,
          vehicleSpeedMps,
          decelerationMps2,
        );
      }
      return _decision(
        Gen1RegenBrakeLightReason.hysteresisHold,
        vehicleSpeedMps,
        decelerationMps2,
      );
    }

    if (decelerationMps2 >= config.engageDecelerationMps2) {
      _requested = true;
      return _decision(
        Gen1RegenBrakeLightReason.regenDeceleration,
        vehicleSpeedMps,
        decelerationMps2,
      );
    }

    return _decision(
      Gen1RegenBrakeLightReason.belowThreshold,
      vehicleSpeedMps,
      decelerationMps2,
    );
  }

  Gen1RegenBrakeLightDecision _decision(
    Gen1RegenBrakeLightReason reason,
    double speed,
    double deceleration,
  ) {
    return Gen1RegenBrakeLightDecision(
      requested: _requested,
      reason: reason,
      decelerationMps2: deceleration,
      vehicleSpeedMps: speed,
    );
  }
}
