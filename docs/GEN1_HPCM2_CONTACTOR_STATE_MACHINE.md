# Gen-1 HPCM2 Contactor State Machine

Status: **vehicle-confirmed state sequence; individual positive-vs-negative bit assignment still unresolved**

On 2026-09-14 a 2013 Chevrolet Volt was observed with Windows GDS2 while PCG-1 / OBD Atlas passively recorded all five configured CAN channels.

## Diagnostic mapping

GDS2 defined dynamic packet `0xFE` from HPCM2 parameter `0x430E`:

- request: `0x7E4  04 2C FE 43 0E ...`
- positive response: `0x7EC  02 6C FE ...`
- schedule/sample request: `0x7E4  03 AA 03 FE ...`
- dynamic response: `0x5EC  FE xx ...`

The real-car dynamic response cadence in the controlled startup and shutdown captures was approximately **200 ms**. The earlier **300 ms** cadence remains simulator-fixture behavior only.

## Vehicle-observed state machine

| Raw | Binary | Atlas phase |
| --- | --- | --- |
| `0x68` | `01101000` | `hvOff` |
| `0x6A` | `01101010` | `firstMainContactorEngaged` |
| `0x6F` | `01101111` | `prechargeActive` |
| `0x6B` | `01101011` | `hvBusEstablished` |

Successful startup:

```text
0x68 -> 0x6A -> 0x6F -> 0x6B
```

Normal shutdown:

```text
0x6B -> 0x6A -> 0x68
```

The observed transitions show bit 2 only during the transient `0x6F` precharge state. Bits 0 and 1 are the two changing main-contactor bits. Atlas deliberately does **not** name bit 0 vs bit 1 as positive/negative until a controlled test independently separates those commands. Bits 3, 5, and 6 stay set across the four observed states and are not mapped by this evidence.

## Decoder

Offline raw-capture decoder:

```bash
python3 tool/decode_gen1_hpcm2_contactor_state.py atlas_capture.log
```

Optional JSON output:

```bash
python3 tool/decode_gen1_hpcm2_contactor_state.py atlas_capture.log \
  --json-out hpcm2_contactor_state.json
```

The Flutter core decoder is `lib/core/gen1_hpcm2_contactor_state.dart`. It requires explicit DID context `0x430E` before decoding `0xFE` payloads so that a reused dynamic packet ID cannot be misinterpreted.

## Canonical evidence

See:

- `assets/evidence/chevrolet_volt_gen1_hpcm2_contactor_20260914.json`
- `assets/diagnostics/chevrolet_volt_gen1_hpcm2_vehicle_confirmed.json`

The evidence manifest contains SHA-256 hashes for the three raw source captures, exact event-marker times, state counts, transition timestamps, and the real-car cadence measurements. The large raw logs remain external to the repository and are identified cryptographically by those hashes.
