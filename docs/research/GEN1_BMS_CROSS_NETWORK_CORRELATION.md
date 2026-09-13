# Gen-1 BMS cross-network correlation

## Purpose

Atlas has two distinct views of Gen-1 Volt/Ampera battery measurements:

- `internal_becm_bicm` at **125 kbit/s**, where the imported community DBC names
  `Cell_01` through `Cell_96` and `Temp_01` through `Temp_16`;
- `hv_energy_management` at **500 kbit/s**, where Atlas directly observes the
  multiplexed `0x200`, `0x202`, `0x204`, and `0x206` voltage blocks as 96
  measurement slots.

The numbering of those two 96-value views is not assumed to match. This
workflow measures the relationship.

## Network identity is part of the key

CAN ID alone is not an identity. Atlas treats a message as at least:

`(network, bitrate_kbps, can_id)`

For example, `0x460` on `internal_becm_bicm` / 125 kbit/s contains community
cell-voltage signals, while `0x460` on the 500 kbit/s HV network is a different
message. The correlation tools preserve that boundary.

## Passive tool chain

`tool/decode_gen1_internal_bms.py`
decodes recorded 125 kbit/s candump/Atlas logs using the normalized community
registry. It never transmits and preserves `community_derived` confidence.

`tool/capture_gen1_bms_dual_socketcan.py`
records two already-configured SocketCAN interfaces with one monotonic clock.
It does not configure bitrate, bring interfaces up/down, or transmit. The output
is two candump-compatible logs plus a manifest.

`tool/correlate_gen1_bms_networks.py`
decodes the 125 kbit/s named cells and the 500 kbit/s HV measurement slots,
time-aligns samples, scores all 96x96 pairs by change correlation, absolute
voltage error, and overlap, then performs a one-to-one assignment. A single
session is always `candidateOnly`.

`tool/aggregate_gen1_bms_mapping_sessions.py`
combines independent correlation reports. A pairing becomes
`repeatableCrossSessionCandidate` only after at least three agreeing sessions
with strong scores and <=3 mV maximum RMSE. It is still not automatically
`confirmed`.

`tool/generate_gen1_bms_correlation_fixture.py`
creates deterministic synthetic 125 kbit/s and 500 kbit/s captures with a known
scrambled 96-cell permutation. The regression test requires Atlas to recover all
96 mappings.

## Recommended evidence sessions

Use independent operating conditions so similarly charged cells cannot match
only because their static voltages are close:

1. stable/rest period;
2. charging period;
3. READY/load or moderate discharge period.

The same pairing should survive all three. Additional sessions improve
confidence.

## Example offline workflow

Generate simulator data:

```bash
python3 tool/generate_gen1_bms_correlation_fixture.py --out-dir /tmp/gen1-bms-sim
```

Correlate one session:

```bash
python3 tool/correlate_gen1_bms_networks.py \
  /tmp/gen1-bms-sim/sim_internal_bms_125k.log \
  /tmp/gen1-bms-sim/sim_hv_energy_500k.log \
  --json-out /tmp/session1.json \
  --csv-out /tmp/session1.csv
```

After three independent real captures:

```bash
python3 tool/aggregate_gen1_bms_mapping_sessions.py \
  session-rest.json session-charge.json session-load.json \
  --json-out combined-map.json
```

## Evidence boundary and hardware safety

This work does not establish a vehicle access point for the internal 125 kbit/s
bus. The secondary DLC network observed by Atlas is 500 kbit/s and must not be
treated as the BECM/BICM bus. Physical connection work should use a separately
verified low-voltage service access point and should not be inferred from these
software definitions.
