# Gen-1 Volt Deceleration Brake-Light Feature

This branch (`feat/gen1-decel-brake-light`) is for research and development of a supplemental brake-light activation feature for the first-generation Chevrolet Volt.

## Goal

Activate the brake lamps during sufficiently strong vehicle deceleration caused by regenerative braking, even when the driver is not pressing the brake pedal, while leaving the factory brake-pedal and stop-lamp system intact.

## Planned signal inputs

- Longitudinal acceleration / deceleration
- Regenerative braking torque, current, or independently validated regen-active state
- Vehicle speed
- Existing brake-pedal / stop-lamp state

## Current branch status

A software-only shadow controller now exists at:

- `lib/core/gen1_regen_brake_light_shadow.dart`

Unit tests are at:

- `test/core/gen1_regen_brake_light_shadow_test.dart`

The controller does **not** contain or expose a physical lamp-output path. It only calculates an internal `regen_brake_light_request` state for logging and validation.

The first research calibration uses hysteresis:

- engage at or above `1.3 m/s^2` deceleration,
- release below `0.7 m/s^2`,
- suppress below `1.4 m/s` vehicle speed (about 5 km/h).

The supplemental request also fails OFF if input is invalid, regen is not independently confirmed, or the factory brake pedal is applied.

These values are provisional research defaults and must be validated against vehicle data before any production decision.

## Next vehicle test

Follow:

- `docs/GEN1_DECEL_BRAKE_LIGHT_ROAD_TEST.md`

That protocol uses marked D-coast, L-regen, light-brake, and moderate-brake events to identify and validate vehicle speed, longitudinal deceleration, regenerative braking, and factory brake-state inputs.

## Development approach

1. Identify and validate the required Gen-1 Volt CAN or diagnostic signals in Atlas.
2. Feed those validated signals into the software-only `regen_brake_light_request` shadow controller.
3. Log and test the request during real driving without controlling any lamps.
4. Tune filtering, hysteresis, stale-data handling, and any dwell timing needed to prevent flicker or nuisance activation.
5. Repeat controlled road captures until the behavior is reproducible.
6. Only after validation, investigate an electrically isolated method to request the brake lamps without spoofing the brake-pedal-position sensor or disturbing ABS/ESC/BCM operation.

## Safety boundary

This branch is experimental. No code in this branch should directly command production vehicle brake lamps until the signal identification, thresholds, failure behavior, and electrical interface have been independently validated.

The factory brake-light system must remain fully functional and authoritative at all times.
