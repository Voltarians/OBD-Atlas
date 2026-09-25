# Gen-1 Volt / Ampera CAN research IDs

Status: **research metadata; confidence is per entry**

Scope: Chevrolet Volt / Opel Ampera **Gen-1 only**. These IDs must not be copied into Gen-2 definitions without independent validation.

## Internal BECM↔BICM network — 125 kbit/s

| CAN ID / family | Direction / role | Confidence | Atlas handling |
| --- | --- | --- | --- |
| `0x460..0x47F` | BICM cell-voltage response family | source-backed, experimental | Passive decode; 12-bit values at 0.00125 V/count |
| `0x7E0..0x7EF` | BICM temperature-family traffic | source-backed, experimental | Passive decode; temperature conversion remains unresolved between sources |
| `0x200` | BECM/master query candidate | executable-source confirmed | Identify/log only; **do not transmit** in passive Atlas |
| `0x300` | BECM/master traffic | capture-observed, semantics unknown | Identify/log as unknown master traffic |
| `0x310` | BECM/master traffic | capture-observed, semantics unknown | Identify/log as unknown master traffic |

The Yasko reference sends `0x200 [3] 02 00 00` periodically before collecting BICM data. Atlas records that as research metadata only; this does not establish that the command is safe or sufficient on an installed vehicle.

## HPCM2 diagnostic addressing — vehicle CAN

| CAN ID | Role | Confidence | Atlas handling |
| --- | --- | --- | --- |
| `0x7E4` | HPCM2 diagnostic request address | source-backed | Diagnostic-address metadata |
| `0x7EC` | HPCM2 diagnostic response address | source-backed | Diagnostic-address metadata |
| `0x5E8` | Dynamically defined data response used by published Volt/Ampera research | community research | Research metadata; service/context dependent |

Published Volt/Ampera CAN notes describe diagnostic use of `0x2C` to define data and `0xAA` to request the resulting packet. Keep this separate from ordinary broadcast-signal definitions.

## Confidence rules

- **source-backed** means an executable implementation or documented Volt/Ampera diagnostic procedure exists.
- **capture-observed** means the ID is present in community Gen-1 battery captures, but its semantics are not established.
- No ID in this file becomes a verified Atlas signal until reproduced on Atlas-controlled Gen-1 captures.
- IDs from Chevrolet Bolt or Gen-2 Volt research must not be imported into this Gen-1 table by numeric similarity.

## Sources

- `yasko-pv/gw-ev`, `gw-ev.c` — direct Gen-1 BICM communication and `0x200` query behavior.
- `Tom-evnut/AmperaBattery` — Gen-1 internal 125-kbit/s network, DBC/captures, including observed `0x300` and `0x310` master traffic.
- `openvehicles/Open-Vehicle-Monitoring-System`, Volt/Ampera CAN bus notes — HPCM2 diagnostic addressing and dynamically defined data research.
