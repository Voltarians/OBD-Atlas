# Atlas GDS2 isolated bench simulator

OBD Atlas includes an isolated Chevrolet Volt Gen-1 ECU bench simulator for learning the exact request sequence GDS2 sends through a real J2534/VCX interface without connecting the simulator to a vehicle.

The simulator is now registry-driven. Atlas keeps module addressing and confidence in `assets/diagnostics/chevrolet_volt_gen1_bench_modules.json`; only entries explicitly marked `simulationStatus: implemented` may transmit. Observed but unconfirmed modules stay discovery-only and fail closed.

## Bench topology

```text
Windows GDS2
  -> VXDIAG / VCX J2534 provider
  -> VCX hardware
  -> isolated DLC bench pins 6/14, 500 kbit/s
  -> UC2 device 0 CAN1
  -> PCG-1 / OBD Atlas gds2_bench_simulator.py
```

The vehicle side of the harness must remain disconnected while simulator mode is active.

## Safety boundary

The simulator opens the UC2 controller in active CAN mode because a two-node VCX/UC2 bench requires an ACK. Active simulation is gated by `--confirm-isolated-bench`.

The simulator implements only identification and read-only diagnostic behavior. It refuses SecurityAccess, writes, programming/download/upload/transfer services, RoutineControl, communication changes, DTC clearing, and DTC setting changes. Unknown services are logged and fail closed.

Discovery-only registry entries are never answered. In particular, request ID `0x259` is recorded with observed GDS2 requests `3E`, `27 01`, and `A2`, but Atlas does not infer a response ID or SecurityAccess behavior for it.

Two September 13, 2026 isolated-bench experiments transmitted candidate responses on `0x659`, using both an all-zero and a `0x1234` seed response. GDS2 continued cycling `A2` and `27 01` in both experiments, so neither candidate is treated as accepted behavior. The preserved experimental record is `assets/diagnostics/chevrolet_volt_gen1_observed_0x259_experiments.json`; production simulation remains fail-closed.

This simulator is not for connection to a live vehicle network.

## Module registry

List the current registry:

```bash
python3 tool/gds2_bench_simulator.py --list-modules
```

Current implemented module:

- key: `hpcm2`
- module: K114B Hybrid Powertrain Control Module 2
- request CAN ID: `0x7E4`
- normal/USDT response CAN ID: `0x7EC`
- UUDT/data/DTC response CAN ID: `0x5EC`
- bitrate: 500 kbit/s
- confidence: `confirmedBench`

The registry also records GDS2-observed request IDs as `discoveryOnly` until a module identity and response addressing are confirmed. Legacy GM address references are stored separately from controlled Volt evidence and do not by themselves authorize simulation.

## HPCM2 behavior validated with GDS2

The HPCM2 profile includes behavior that was accepted by GDS2 on the isolated bench:

- legacy one-byte `3E` TesterPresent -> `7E`
- `A9 81 1A` legacy GM DTC query -> no-DTC completion on `0x5EC`
- legacy `1A` identification requests:
  - `1A 90` VIN
  - `1A B4` Manufacturer's Traceability Number
  - `1A CB` End Model Part Number
  - `1A CC` Base Model Part Number
  - `1A C1` Software Module 1 Identifier
  - `1A C2` Software Module 2 Identifier
- `0x10` DiagnosticSessionControl
- `0x19` ReadDTCInformation for retained UDS bench exploration
- `0x22` ReadDataByIdentifier for synthetic VIN DID `F190` and Atlas HPCM2 candidate DIDs

GDS2 successfully displayed the synthetic HPCM2 identity and reported `No DTCs Stored` with this behavior.

Synthetic bench identity values are intentionally obvious and are not intended to represent a real vehicle or controller.

## Run on PCG-1

Update the current development tree, then set the UC2 native library path:

```bash
cd "$HOME/OBD-Atlas-current"
git pull --ff-only
export OBD_ATLAS_USBCAN_LIB="$HOME/promethean/rust-can-zlg-lib/library/linux/aarch64/libusbcan.so"
```

Run the self-check without opening hardware:

```bash
python3 tool/gds2_bench_simulator.py --check
```

Inspect available modules:

```bash
python3 tool/gds2_bench_simulator.py --list-modules
```

With the vehicle disconnected from the bench harness, start the confirmed HPCM2 profile:

```bash
python3 tool/gds2_bench_simulator.py --module hpcm2 --confirm-isolated-bench
```

Then start GDS2 on the Windows laptop with the real VXDIAG/VCX J2534 provider selected.

## Learning output

Every received CAN frame, simulator decision, and transmitted response is appended to a JSONL file under:

```text
~/Documents/OBD Atlas/gds2_bench_YYYYMMDD_HHMMSS.jsonl
```

Unknown or unsupported diagnostic requests are summarized when the simulator stops. Use those logs to promote registry entries only after the addressing and semantics are supported by controlled evidence.

## Development rule

Do not guess missing GDS2 behavior merely to advance the UI. Capture the request first, identify the service/module semantics, then add a tested response. Keep programming/security/actuator paths fail-closed unless a separate explicitly scoped isolated-bench experiment requires them.
