# Gen-1 Volt Deceleration Brake-Light Road Test

Purpose: collect one controlled multi-channel Atlas capture that separates ordinary D coasting, strong L-mode regenerative deceleration, and friction-brake deceleration so the Gen-1 Volt signals needed by `regen_brake_light_request` can be identified and validated.

This is a signal-identification test only. No brake lamps are commanded by Atlas.

## Before driving

- Use the Gen-1 Volt test vehicle with the normal factory braking system unchanged.
- Use the verified Atlas multi-channel configuration and start one continuous capture before the first marker.
- Confirm the capture is receiving frames on the expected active channels.
- Use a safe, legal, low-traffic route with enough straight road and visibility for repeated 25-30 mph deceleration events.
- Do not attempt a marker or software interaction when traffic conditions require attention. Safety and normal vehicle control take priority over the test sequence.

## Marker sequence

Use Atlas event markers when available. If voice annotation is being used, speak the same marker text. Exact timing is less important than marking the transition itself.

1. `DBL_00_BASELINE`
   - Vehicle stationary or steady and safe.
   - Hold approximately 10 seconds.

2. `DBL_10_D_STEADY`
   - Drive in D at approximately 25-30 mph.
   - Hold reasonably steady speed for approximately 10 seconds.

3. `DBL_20_D_LIFT_START`
   - In D, completely release the accelerator without pressing the brake.
   - Allow normal D-mode coast/regen deceleration.

4. `DBL_21_D_LIFT_END`
   - Mark when the D lift event is complete and normal acceleration/steady driving resumes.

5. `DBL_30_L_LIFT_START`
   - Return to approximately 25-30 mph.
   - Select L under normal operating conditions.
   - Completely release the accelerator without pressing the brake and allow the vehicle's stronger regenerative deceleration.

6. `DBL_31_L_LIFT_END`
   - Mark when the L-mode lift event is complete.

7. `DBL_40_LIGHT_BRAKE_START`
   - Return to approximately 25-30 mph in D.
   - Apply a light, normal brake-pedal input and perform a controlled deceleration.

8. `DBL_41_LIGHT_BRAKE_END`
   - Mark when the light-brake event is complete.

9. `DBL_50_MEDIUM_BRAKE_START`
   - Return to approximately 25-30 mph in D.
   - Apply a moderate, normal brake-pedal input and perform a controlled deceleration. This is not an emergency-stop test.

10. `DBL_51_MEDIUM_BRAKE_END`
    - Mark when the moderate-brake event is complete.

11. `DBL_90_TEST_END`
    - Park safely, leave the capture running for approximately 10 additional seconds, then stop recording.

## Signals to correlate

### Already confirmed in Atlas

- `0x0F1` channel 2: brake-pedal pressed bit and raw brake-pedal position.
- `0x0C9` channel 2: ECM brake-pressed state.
- `0x1E9` channel 2: EBCM vehicle-dynamics brake-pedal-pressed bit. This message is a priority target for additional motion fields.
- `0x0D1` channel 2: normalized brake-pedal raw value.
- `0x214` channel 2: user brake-pressure raw candidate/validated event correlation.
- `0x1F5` channel 4: gear selector, useful for separating D and L events.

### Priority candidates to validate

- `0x3E9`: vehicle speed. Community sources disagree on exact engineering-unit scaling, so derive the Gen-1 Volt scaling from the test vehicle before promotion.
- `0x1E9`: inspect all changing fields for longitudinal/lateral acceleration and yaw-related motion data. Do not assume a community decode is correct until vehicle-correlated.
- `0x2C7` channel 2: HV battery current candidate.
- `0x210` channel 3: pack-current candidate.
- `0x1C3` channel 4: accelerator-position candidate, useful for confirming accelerator lift.
- Any other high-rate EBCM/HPCM/propulsion field that tracks measured deceleration or regenerative torque.

## What constitutes a useful capture

The capture should make these states clearly distinguishable in time:

- steady-speed D driving,
- accelerator lift in D,
- accelerator lift in L,
- light brake-pedal deceleration,
- moderate brake-pedal deceleration.

The most important comparison is D lift versus L lift with the factory brake pedal released. A useful regen-confirmation signal should increase or change consistently during L-mode regenerative deceleration and should not falsely indicate regenerative braking during simple road-grade/aerodynamic slowing.

## Shadow-controller inputs

The initial controller in `lib/core/gen1_regen_brake_light_shadow.dart` expects normalized inputs rather than unvalidated CAN IDs:

- vehicle speed in m/s,
- positive deceleration magnitude in m/s^2,
- independently confirmed `regenConfirmed` state,
- confirmed factory brake-pedal state,
- input-validity state.

Initial research thresholds are:

- engage: `1.3 m/s^2` deceleration,
- release: below `0.7 m/s^2`,
- minimum speed: `1.4 m/s` (about 5 km/h).

These are research defaults, not production calibration. The road data will determine whether filtering, dwell time, different thresholds, or a different regen-confirmation strategy is needed.

## Acceptance criteria before any physical lamp work

1. Vehicle speed decode validated against the car.
2. Longitudinal deceleration independently validated and sign convention established.
3. Regen activity confirmed by a signal independent of longitudinal acceleration.
4. D and L lift events correctly distinguished.
5. Factory brake-pedal state correctly suppresses the supplemental shadow request.
6. Shadow output does not chatter around the threshold.
7. Missing/stale/invalid input forces the shadow request OFF.
8. Multiple road captures show repeatable behavior before any electrical output interface is considered.
