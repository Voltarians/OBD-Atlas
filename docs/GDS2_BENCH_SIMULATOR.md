# GDS2 isolated bench simulator

OBD Atlas includes a first-stage Chevrolet Volt Gen-1 HPCM2 simulator for learning the exact request sequence GDS2 sends through a real J2534/VCX interface without connecting the simulator to a vehicle.

## Bench topology

```text
Windows GDS2
  -> VXDIAG / VCX J2534 provider
  -> VCX hardware
  -> isolated DLC bench pins 6/14, 500 kbit/s
  -> UC2 device 0 CAN1
  -> PCG-1 / OBD Atlas gds2_bench_simulator.py
```

The vehicle side of the harness must remain disconnected while this simulator is active.

## Safety boundary

The simulator opens the UC2 controller in active CAN mode because a two-node VCX/UC2 bench requires an ACK. Active mode is gated by `--confirm-isolated-bench`.

The simulator implements only identification and read-only diagnostic behavior. It explicitly refuses SecurityAccess, writes, programming/download/upload/transfer services, RoutineControl, communication changes, DTC clearing, and DTC setting changes. Unknown services receive a negative response and are recorded for analysis.

This simulator is not for connection to a live vehicle network.

## Current emulated module

Initial target: K114B Hybrid/EV Powertrain Control Module 2 (HPCM2).

- request CAN ID: `0x7E4`
- response CAN ID: `0x7EC`
- bitrate: 500 kbit/s
- UC2 default: device 0, CAN1
- synthetic VIN: `1G1RA6E40DU100001`

The VIN is a simulator identity and is not intended to represent a real vehicle.

## Supported diagnostic behavior

Current safe services:

- `0x10` DiagnosticSessionControl: default and extended diagnostic sessions
- `0x19` ReadDTCInformation: reports no DTCs for the initial supported subfunctions
- `0x22` ReadDataByIdentifier: synthetic VIN DID `F190` and a small set of Atlas HPCM2 candidate DIDs
- `0x3E` TesterPresent

Read-only HPCM2 candidate DIDs currently include pack voltage, pack current, SOC, min/max module voltage, module index, charger input values, and temperature fixtures. The DID meanings remain subject to the confidence/evidence limits recorded in `assets/diagnostics/chevrolet_volt_gen1_hpcm2_did_candidates.json`.

VIN responses use ISO-TP multi-frame transmission and honor the VCX flow-control frame.

## Run on PCG-1

Update the current development tree first, then set the UC2 native library path:

```bash
cd "$HOME/OBD-Atlas-current"
git pull --ff-only
export OBD_ATLAS_USBCAN_LIB="$HOME/promethean/rust-can-zlg-lib/library/linux/aarch64/libusbcan.so"
```

Run the self-check without opening hardware:

```bash
python3 tool/gds2_bench_simulator.py --check
```

With the vehicle disconnected from the bench harness, start the simulator:

```bash
python3 tool/gds2_bench_simulator.py --confirm-isolated-bench
```

Then start GDS2 on the Windows laptop with the real VXDIAG/VCX J2534 provider selected.

## Learning output

Every received CAN frame, simulator decision, and transmitted response is appended to a JSONL file under:

```text
~/Documents/OBD Atlas/gds2_bench_YYYYMMDD_HHMMSS.jsonl
```

Unknown or unsupported diagnostic requests are summarized when the simulator stops. That log is the evidence source for the next simulator revision: add only requests actually observed from GDS2, with the narrowest safe response needed to advance the session.

## Development rule

Do not guess missing GDS2 behavior merely to advance the UI. Capture the request first, identify the service/module semantics, then add a tested response. Keep programming/security/actuator paths fail-closed unless a separate explicitly scoped isolated-bench experiment requires them.
