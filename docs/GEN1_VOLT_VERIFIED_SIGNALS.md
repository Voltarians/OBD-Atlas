# Chevrolet Volt Gen-1 verified CAN signals

These definitions were derived from controlled event captures on one Gen-1 Chevrolet Volt using the verified PCG-1 five-channel configuration. Byte and bit indexes are zero-based. Confirmed means the state repeated cleanly in the test vehicle; it does not yet imply validation across every Gen-1 model year.

The machine-readable source of truth is `assets/signals/chevrolet_volt_gen1.json`. Runtime code must preserve the `confirmed` versus `candidate` distinction.

## Confirmed signals

| Signal | Channel | CAN ID | Decode |
| --- | ---: | --- | --- |
| Brake switch | 4 / can3 | `0x17D` | byte 2 bit 5: 0 released, 1 applied |
| Brake pedal pressed | 2 / can1 | `0x0F1` | byte 0 bit 1: 0 released, 1 pressed |
| Brake pedal position | 2 / can1 | `0x0F1` | DBC `15|8@0+`, raw pedal-position value |
| Steering angle | 4 / can3 | `0x1E5` | signed big-endian bytes 1–2, 1/16 degree/count, positive left |
| Gear selector | 4 / can3 | `0x1F5` | byte 3: 01 P, 02 R, 03 N, 04 D, 05 L |
| Turn stalk | 4 / can3 | `0x140` | byte 2: 01 off, 05 left, 09 right |
| Parking brake | 4 / can3 | `0x1E1` | byte 2 bit 2: 0 released, 1 applied |
| Driver door | 5 / can4 | `0x0C630040` ext | byte 0: 80 closed, 81 open |
| Passenger door | 5 / can4 | `0x0C2F6040` ext | byte 0 bit 0 |
| Left rear door | 5 / can4 | `0x0C2F8040` ext | byte 0 bit 0 |
| Right rear door | 5 / can4 | `0x0C2FA040` ext | byte 0 bit 0 |
| Hatch | 5 / can4 | `0x106AA040` ext | byte 0 bit 0 |
| Hood | 5 / can4 | `0x10728040` ext | byte 0: 00 closed, 02 open |
| Driver/front passenger belts | 5 / can4 | `0x10336058` ext | byte 0 bit 0 driver, bit 2 passenger |
| Exterior lights | 4 / can3 | `0x140` | full payload: `000A01` off, `001201` parking, `021A01` low, `821C01` high, `120201` auto |

## Candidates needing another controlled test

- Brake proportional candidate: channel 5, extended ID `0x10250040`, big-endian bytes 0–1. Observed 0 released, 1584 light, 1602 medium, 1620 hard.
- Accelerator candidate: channel 4, ID `0x1C3`, byte 6. Observed 0 released, 100 near 10%, 165 near 25%, 194–195 near 50%. This is nonlinear, so no percentage formula is claimed.
- Hazard-flash candidate: channel 2, ID `0x1E3`, byte 6. Normally `0x28`, usually alternating `0x2A`/`0x2B` during hazards. It is correlated but not yet proven as a steady hazard-enable field.

`0x1040A080` is intentionally not labeled as a driver-door signal: later testing did not prove it was driver-specific. The brief hatch-latch event at `0x0C6B4040` is also omitted from the confirmed catalog.

## Startup and high-voltage signals

The 2026-09-12 controlled startup capture adds the following evidence-backed definitions. These were checked against community GM Global-A/OpenDBC work and against Gen-1 Volt service information rather than being labeled from timing correlation alone.

| Signal | Channel | CAN ID | Decode | Confidence |
| --- | ---: | --- | --- | --- |
| Brake pedal pressed | 2 / can1 | `0x0F1` | byte 0 bit 1 | confirmed |
| Brake pedal position | 2 / can1 | `0x0F1` | DBC `15|8@0+`, raw count | confirmed |
| System power mode | 2 / can1 | `0x1F1` | byte 0 low 2 bits: 0 off, 1 accessory, 2 run, 3 crank/start request | confirmed |
| HV battery voltage | 2 / can1 | `0x2C7` | DBC `31|12@0+`, 0.125 V/count | confirmed |
| Pack voltage | 3 / can2 | `0x210` | DBC `7|12@0+`, 0.125 V/count | confirmed |
| HV battery current | 2 / can1 | `0x2C7` | DBC `12|13@0-`, 0.15 A/count | candidate |
| Pack current | 3 / can2 | `0x210` | DBC `23|8@0-`, 0.1 A/count, -0.1 A offset | candidate |

### Startup evidence

In `atlas_capture_20260912_030630.log`, `0x0F1` provides an independent brake reference. Its raw pedal-position field starts at zero, rises progressively when the brake is applied, and returns to zero when the pedal is released. The community-defined brake-pressed bit asserts after the position value rises above the initial low counts and clears again on release. This independently validates both `BrakePedalPosition` and `BrakePressed` without assigning a percentage calibration.

The same capture shows `0x1F1` transitioning from power mode 0 to 3 at the start request, then to 2 when the vehicle reaches RUN. This matches the GM Global-A `SystemPowerMode` definition and the Volt service description of the BCM as the power-mode master.

The capture also contains `0x210#BE44...`; `0xBE4 * 0.125 = 380.5 V`. The independently defined `0x2C7` battery-voltage field agrees at approximately the same pack voltage, which is why both voltage signals are promoted to confirmed. Current fields remain candidates until sign and scale are checked during a controlled charge or load event.

### Service-information anchor for future precharge diagnostics

Gen-1 Volt service information for P0C77/P0C78 states that HPCM2 controls the contactor/precharge sequence. For the diagnostic to run, the propulsion bus is below 40 V before precharge. A rise above 80% of battery voltage in under 50 ms is classified as too fast; failure to reach 95% within 700 ms is classified as too slow and opens the contactors.

These thresholds are diagnostic context, not CAN signal definitions. Atlas must not infer individual positive/negative/multifunction contactor state until a specific bus signal is independently identified.

References:

- GM Global-A community/OpenDBC powertrain definitions: `gm_global_a_powertrain_volt.dbc`
- GM Global-A community/OpenDBC high-voltage definitions: `gm_global_a_high_voltage_management.dbc`
- 2012 Chevrolet Volt service information, P0C77/P0C78 Battery System Precharge: https://charm.li/Chevrolet/2012/Volt%20L4-1.4L%20Elect/Repair%20and%20Diagnosis/A%20L%20L%20%20Diagnostic%20Trouble%20Codes%20%28%20DTC%20%29/Testing%20and%20Inspection/P%20Code%20Charts/P0C78/
- 2012 Chevrolet Volt service information, Body Control System Description and Operation / Power Mode Master.
