# Gen-1 Volt GDS2 DID mapping workflow

## Goal

Map GM service-tool parameter names to the actual diagnostic transport used on the Gen-1 Chevrolet Volt without inventing addresses or scales.

Atlas stores three different facts independently:

1. **GM service documented** — GM names the parameter, expected state/range and diagnostic role.
2. **Community candidate/corroborated** — outside sources identify a transport/DID or decode.
3. **Atlas confirmed** — a controlled GDS2/VCX session or equivalent direct evidence reproduces the request and response on the test vehicle.

`assets/service/chevrolet_volt_gen1_gm_scan_parameters.json` is the GM-name inventory. `assets/diagnostics/chevrolet_volt_gen1_hpcm2_did_candidates.json` contains provisional HPCM2 DID mappings.

## Known HPCM2 diagnostic path

Current evidence identifies the Gen-1 HPCM2 diagnostic path as:

- ISO 15765 at 500 kbit/s
- request CAN ID `0x7E4`
- response CAN ID `0x7EC`
- ReadDataByIdentifier / ReadDataByParameterIdentifier service `0x22`
- positive response service `0x62`

Atlas must still record the exact vehicle/model-year/calibration used for every confirmation.

## Passive capture procedure

This mapping run is observation-only. Do **not** use GDS2 output controls, contactor commands, security access, resets or programming while performing the initial DID map.

1. Connect GDS2 through the VCX interface normally.
2. Independently start an Atlas/candump capture on PCG-1 before entering the GDS2 data-display screen.
3. Keep the vehicle stationary in the service state required by GM for the selected data list.
4. Navigate to `K114B Hybrid/EV Powertrain Control Module 2 -> Data Display`.
5. Select one small data group at a time. Prefer a single parameter when GDS2 permits it.
6. Record a capture marker and the exact GDS2 parameter/group name whenever the displayed group changes.
7. Leave each group displayed for several seconds so repeated requests can be distinguished from navigation/setup traffic.
8. Stop the capture normally and preserve the raw log plus session manifest.

The same process should later be repeated for K16 BECM data displays, particularly the 96 battery voltages and battery-current sensors.

## Offline extraction

Run:

```bash
python3 tool/extract_gds2_dids.py atlas_capture.log --json-out dids.json
```

The extractor reassembles classic ISO-TP on `0x7E4/0x7EC` and reports `0x22 -> 0x62` DID transactions with request/response timestamps, latency and raw returned data.

A typical result is conceptually:

```text
123.456789 can1 0x4356 -> FFFA (12.0 ms)
```

The capture marker and GDS2 screen name are then used to associate that DID with the displayed GM parameter.

## Promotion rule

A DID mapping becomes `confirmed` when all of the following are true:

- the GDS2 screen name is known;
- a repeatable diagnostic request is isolated while that screen/group is active;
- the ECU request/response CAN IDs are known;
- the service and DID are identified;
- returned data changes consistently with the displayed value or state;
- scaling/enum interpretation reproduces the GDS2 value across multiple samples;
- no competing DID in the same group explains the displayed value better.

If three independent source families agree before direct capture, the mapping may be stored as `communityCorroborated`, but it remains distinct from `confirmed`.

## Priority mapping order

### Startup / contactor diagnostics

1. Hybrid/EV Battery Pack Positive Contactor Command
2. Hybrid/EV Battery Pack Negative Contactor Command
3. Hybrid/EV Battery Pack Precharge Transistor Command
4. Hybrid/EV Battery Pack Multifunction Contactor Command
5. Hybrid/EV Battery System Precharge Current Too High
6. Hybrid/EV Battery System Precharge Time Short
7. Hybrid/EV Battery System Precharge Time Too Long
8. Hybrid Battery Pack Contactor Open Reasons
9. High Voltage Interlock Circuit
10. Isolation Test Resistance

### Battery health

1. Hybrid/EV Battery 1-96
2. Hybrid/EV Battery Pack Voltage
3. Minimum/maximum/average battery voltage
4. Sensor number with minimum/maximum voltage
5. High-resolution pack current
6. Low-resolution pack current
7. Battery pack resistance
8. State of charge and SOC limits
9. Maximum/minimum/average battery temperature
10. Coolant inlet/outlet temperature

### Charging

1. Charging request/allowed/status
2. Charger HV voltage/current
3. Charger LV voltage/current
4. Charger temperature
5. Proximity-detection circuit
6. Charging-system contactor commands

## Evidence preservation

For every confirmed mapping Atlas should retain:

- raw capture SHA-256
- session manifest SHA-256
- vehicle identity without exporting the VIN
- model year
- module calibration/software identity when available
- GDS2 parameter name and navigation path
- request CAN ID and response CAN ID
- service byte and DID
- raw response bytes
- decoded value and formula/enum
- repeated sample count
- capture timestamp range

This makes a future DBC/DID export auditable and prevents a community guess from silently becoming an OEM claim.
