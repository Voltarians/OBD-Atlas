# Gen-1 Volt controlled brake-signal evidence

This note records the brake-signal definitions promoted from two controlled 2026-09-12 startup captures on the test vehicle. The machine-readable record is `assets/evidence/chevrolet_volt_gen1_brake_20260912_030630.json`.

## Confirmed additions

| Signal | CAN ID | DBC field | Evidence |
| --- | --- | --- | --- |
| ECM brake pressed | `0x0C9` | `40|1@0+` | asserts during controlled brake application and clears on release; assertion replicated in second startup capture |
| EBCM vehicle-dynamic brake pedal pressed | `0x1E9` | `6|1@0+` | independent brake-pressed flag; assertion replicated in second startup capture |
| BrakeNormalized1 | `0x0D1` | `39|8@0+` | raw field tracks confirmed `0x0F1` pedal position with ~0.9997 correlation in the primary capture and ~0.9953 in the replication capture |
| UserBrakePressure raw | `0x214` | `0|9@0+` | rises from zero during the controlled brake event; observed primary range 0..22 |
| UserBrakePressure2 raw | `0x2F9` | `47|9@0+` | decoded value equals `0x214` on every nearest-time paired sample in both startup captures |

The source field names and layouts are independently present in the GM Global-A OpenDBC work. Atlas promotion is based on the controlled vehicle captures, not solely on the community labels.

## Timing in the primary startup capture

The brake sequence in `atlas_capture_20260912_030630.log` is internally consistent:

- `0x0F1` raw pedal movement begins at +16.364849 s.
- `0x0D1` normalized brake becomes non-zero at +16.507523 s.
- `0x1E9` BrakePedalPressed asserts at +16.529852 s.
- `0x0C9` BrakePressed asserts at +16.640092 s.
- `0x214` / `0x2F9` user-brake-pressure fields begin rising at approximately +16.776 s.
- On release, the raw/normalized fields ramp down and the boolean flags clear.

The different assertion times are expected because these fields represent different processed views of the same physical brake application rather than one duplicated bit.

## Evidence boundary

Atlas does **not** claim:

- a hydraulic pressure unit for `0x214` or `0x2F9`;
- a physical-pressure calibration;
- a percent conversion for `0x0D1`;
- that every Gen-1 model year uses these fields identically.

The catalog therefore stores the proportional fields as raw counts while preserving the DBC bit layout and the controlled-event evidence.

## Diagnostic-session scan

The two startup captures and the saved Sep. 6/7/9 passive captures were checked for the currently cataloged GM diagnostic endpoint families, including HPCM2 `0x7E4/0x7EC/0x5EC`, ECM `0x7E0/0x7E8`, TCM `0x7E2/0x7EA`, and BCM `0x244/0x644/0x544`. No matching endpoint traffic was found in those passive captures. They should therefore be treated as broadcast-network evidence, not as latent GDS2/SPS/DPS sessions.
