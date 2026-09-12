# Gen-1 Volt passive high-voltage findings

This note records what Atlas can already establish from saved passive captures of the Gen-1 Volt High Voltage Energy Management network. It intentionally separates **observed structure** from **fully mapped GM signal identity**.

The machine-readable evidence is `assets/evidence/chevrolet_volt_gen1_hv_passive_observations.json`, and `tool/decode_gen1_hv_capture.py` reproduces the decodes from candump-compatible logs.

## Network provenance

The manifest for `volt_capture_20260831_102900.log` identifies `vcan0` as the auxiliary High Voltage Energy Management network, captured with a LYS USBCAN at 500 kbit/s on X84B pins 3/11. Later Atlas captures place the same traffic on `can0`; interface names are therefore session-local and must not be treated as a permanent network identity.

## 96 multiplexed battery-voltage measurements

CAN IDs `0x200`, `0x202`, `0x204`, and `0x206` each carry three 12-bit Motorola voltage fields at 0.00125 V/count and a 3-bit bank selector. Saved captures exercise the bank selector and decode to normal lithium-ion cell-level values, generally around 3.7-3.8 V in the inspected samples.

The protocol structure is significant:

- 4 message IDs
- 8 multiplex banks per ID
- 3 voltage measurements per bank
- **4 x 8 x 3 = 96 voltage measurement slots**

That exactly matches the 96 battery-voltage values exposed by the Gen-1 BECM service-data inventory. Atlas therefore treats the multiplex structure and voltage scaling as strong passive evidence.

**Boundary:** measurement slot 1-96 is not yet asserted to equal GM GDS2 `Hybrid/EV Battery 1-96` numbering or physical pack position. Controlled GDS2 comparison is still required for the exact ordering.

## Nine multiplexed battery temperatures

`0x302` alternates two temperature groups using byte 0 bit 2 as a mux. The community definition uses 0.5 °C/count with a -40 °C offset:

- mux 0: six values, community labels A-F
- mux 1: three values, community labels G-I

Real saved examples decode as:

- `302#038BA18B898C8A1E` -> 29.5, 40.5, 29.5, 28.5, 30.0, 29.0 °C
- `302#1F8C8B9300000030` -> 30.0, 29.5, 33.5 °C
- `302#1F7F7E8900000030` -> 23.5, 23.0, 28.5 °C

The two mux groups produce nine temperature channels, matching the Gen-1 battery thermal-data target. The exact A-I to GM scan-tool sensor/module mapping remains a GDS2 cross-validation task.

## Battery coolant temperature pair

`0x460` contains two stable temperature-like values using the OpenDBC 10-bit Motorola, 0.125 °C/count, -40 °C definition. Representative saved payloads decode as:

- `460#0A3C0A3C` -> 31.5 / 31.5 °C
- `460#0A400A3C` -> 32.0 / 31.5 °C
- `460#0A3C0A34` -> 31.5 / 30.5 °C
- `460#0A200A1C` -> 28.0 / 27.5 °C

These are retained as Atlas-observed candidates. The community `inlet`/`outlet` labels should be checked against GDS2 coolant Sensor 1/2 before role names are promoted to confirmed.

## Charger observations

The existing community-corroborated `0x212` decode receives additional plausibility support from saved vehicle captures. With HV output at zero, examples decode the LV rail at 12.6-13.7 V:

- `212#000000011200` -> 13.7 V LV
- `212#000000010E00` -> 13.5 V LV
- `212#00000000FC00` -> 12.6 V LV

For `0x304`, independent charger implementations confirm byte 1 as requested current at 0.05 A/count and bytes 2-3 as requested voltage at 0.5 V/count. However, saved `304#00007C00` occurs while `0x30E` byte 0 says the charger is disabled. The stored voltage bytes are therefore not meaningful as an active setpoint in that state. Atlas must gate presentation of `0x304` setpoints on the companion `0x30E` mode.

`0x308` and `0x30A` remain deliberately raw. Community sources disagree on their material interpretation, and Battery-Emulator explicitly treats `0x308` content as unknown. Atlas will not promote either field without controlled charging evidence or stronger independent corroboration.

## Evidence boundaries

This work does **not** identify individual positive, negative, precharge, or multifunction contactor broadcast states. Pack-current sign/scale also remains candidate pending a controlled load/charge event. Physical network identity must come from each capture manifest or verified harness mapping, never from a `can0`/`vcan0` name alone.
