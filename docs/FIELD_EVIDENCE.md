# Atlas field evidence register

This register records observations that should influence Atlas design or future
tests. It separates captured evidence from operator reports and planned work so
that an adapter or network is not promoted to "working" without a reproducible
capture.

## Evidence levels

- **Captured**: preserved session files and manifest support the observation.
- **Bench verified**: controlled hardware test succeeded, but no vehicle traffic
  was captured.
- **Field reported**: repeatable operator observation; supporting session files
  may live outside this repository.
- **Unverified**: implementation or live-vehicle validation remains open.

## Captured multi-network session

Source: `examples/volt_capture_20260830_211652.session.json`

| Item | Observation |
| --- | --- |
| Vehicle | Chevrolet Volt, generation 1, GM Voltec |
| Capture type | Passive multi-bus CAN with synchronized voice |
| Preserved frames | 551,152 |
| CAN time span | 277.388381 seconds |
| Productive interfaces | 3 of 5 |
| Productive ID spaces | 161, 26, and 27 unique arbitration IDs |
| Termination | Incomplete shutdown after the RH02 USB connection dropped |
| Evidence integrity | File sizes and SHA-256 hashes recorded in the manifest |

The session proves that an Atlas session cannot assume one vehicle equals one
CAN interface. Arbitration IDs must remain scoped by logged interface/Atlas bus,
and timestamps must be comparable across interfaces.

The RH02 SWCAN channel on DLC pin 1 preserved 34,858 frames at 33,333 bit/s. Two
LYS USBCAN channels on auxiliary 500 kbit/s networks preserved 209,941 and
306,353 frames. The two CANalyst-II channels recorded zero frames in this
session. Zero-frame channels are diagnostic evidence and must remain in the
session record, but must be excluded from signal statistics.

The capture ended on an adapter disconnect while already-written evidence was
preserved. Atlas therefore needs per-interface health, explicit termination
reason, periodic durable writes, and a distinction between a complete session
and a usable partial session.

Synchronized audio is useful supporting evidence, but the manifest explicitly
notes that microphone onset latency was not independently measured. Correlation
scores are research leads, not decoded-signal claims.

## Adapter status matrix

| Adapter/path | Status | Current conclusion |
| --- | --- | --- |
| RH02 CANable, candleLight/gs_usb, SWCAN | Captured | Vehicle traffic captured on the 33.333 kbit/s single-wire channel; USB disconnect handling remains a risk. |
| LYS USBCAN passive bridge | Captured | Two 500 kbit/s auxiliary networks captured successfully in the preserved session. |
| CANalyst-II | Bench verified | Two-channel loopback succeeded; both vehicle channels in the preserved session produced zero frames. Do not mark vehicle acquisition proven. |
| OBDLink MX+ filtered capture | Field reported | This is the currently reported dependable Voltarian capture route. Preserve adapter command/filter configuration in future manifests. |
| RH02 classical CAN via gs_usb/SLCAN | Unverified | Earlier live-vehicle attempts produced zero frames; wiring, bus selection, wake state, and bitrate remain test variables. |
| J2534/VCX | Unverified | Retain as a future Windows inventory/read-only discovery transport. |

## Data and schema requirements derived from evidence

1. Identify the vehicle early and keep make, model, year/generation, platform,
   and privacy-safe VIN handling in the session profile.
2. Use a stable session ID and preserve original interface names.
3. Namespace every frame and arbitration-ID statistic by interface/bus.
4. Record adapter model, channel, transport/firmware, bitrate, listen-only state,
   DLC pins, and wiring notes.
5. Record captured and zero-frame channels, including unique-ID and frame counts.
6. Preserve raw CSV/candump and a session manifest before derived analysis.
7. Hash every evidence file and reject size/hash mismatches before ingestion.
8. Record first/last frame times, clock source, synchronization method,
   termination reason, and completeness.
9. Support optional synchronized annotations without modifying raw evidence.
10. Keep VIN and precise location collection disabled by default.
11. Operate offline on Windows and Android; synchronization is optional.
12. Support synchronized multi-channel acquisition instead of a single-adapter,
    single-bus data model.

## Product boundaries

- **OBD Atlas** owns universal acquisition, normalization, evidence, discovery,
  vehicle profiles, and searchable knowledge.
- **Voltec Atlas** owns deep GM Voltec/Global A definitions and research.
- **Voltarian** is the Volt/ELR vehicle application and a capture producer.
- **Promethean Core / PCG-1** is a future in-vehicle acquisition and compute
  appliance.

Vehicle-specific knowledge may flow into an Atlas profile only with provenance.
Passive observations and correlations must not silently become active-control
definitions.

## Next validation gates

- Import the preserved five-interface session and verify all 551,152 frames,
  all five channel records, hashes, and the partial-session status.
- Produce a fresh MX+ filtered session manifest that records commands, filters,
  timing, frame count, malformed records, pauses, and overflow indicators.
- Repeat CANalyst-II and RH02 classical-CAN vehicle tests with verified connector
  orientation, known-awake bus state, bitrate, and receive-only configuration.
- Add automated tests proving identical arbitration IDs on different interfaces
  remain separate.
- Add a partial-capture test proving an adapter disconnect does not invalidate
  already-preserved evidence.
