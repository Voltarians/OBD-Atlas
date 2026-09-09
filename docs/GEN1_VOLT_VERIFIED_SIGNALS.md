# Chevrolet Volt Gen-1 verified CAN signals

These definitions were derived from controlled event captures on one Gen-1 Chevrolet Volt using the verified PCG-1 five-channel configuration. Byte and bit indexes are zero-based. Confirmed means the state repeated cleanly in the test vehicle; it does not yet imply validation across every Gen-1 model year.

The machine-readable source of truth is `assets/signals/chevrolet_volt_gen1.json`. Runtime code must preserve the `confirmed` versus `candidate` distinction.

## Confirmed signals

| Signal | Channel | CAN ID | Decode |
| --- | ---: | --- | --- |
| Brake switch | 4 / can3 | `0x17D` | byte 2 bit 5: 0 released, 1 applied |
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
