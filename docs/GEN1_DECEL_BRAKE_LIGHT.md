# Gen-1 Volt Deceleration Brake-Light Feature

This branch (`feat/gen1-decel-brake-light`) is for research and development of a supplemental brake-light activation feature for the first-generation Chevrolet Volt.

## Goal

Activate the brake lamps during sufficiently strong vehicle deceleration caused by regenerative braking, even when the driver is not pressing the brake pedal, while leaving the factory brake-pedal and stop-lamp system intact.

## Planned signal inputs

- Longitudinal acceleration / deceleration
- Regenerative braking torque or regen-active state
- Vehicle speed
- Existing brake-pedal / stop-lamp state

## Development approach

1. Identify and validate the required Gen-1 Volt CAN or diagnostic signals in Atlas.
2. Implement a software-only `regen_brake_light_request` shadow signal.
3. Log and test the request during real driving without controlling any lamps.
4. Add filtering and hysteresis to prevent flicker or nuisance activation.
5. Only after validation, investigate an electrically isolated method to request the brake lamps without spoofing the brake-pedal-position sensor or disturbing ABS/ESC/BCM operation.

## Safety boundary

This branch is experimental. No code in this branch should directly command production vehicle brake lamps until the signal identification, thresholds, failure behavior, and electrical interface have been independently validated.

The factory brake-light system must remain fully functional and authoritative at all times.
