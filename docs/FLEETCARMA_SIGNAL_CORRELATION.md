# FleetCarma historical signal correlation

This stage uses the recovered FleetCarma C5 Chevrolet Volt corpus as historical
evidence for Atlas signal discovery.

The analyzer deliberately stops at **candidate** status. It does not assign a
semantic name such as Vehicle Speed or Brake Pedal solely because a payload
tracks GPS.

## Run

```bash
python tool/analyze_fleetcarma_volt_ids.py CANLOG.zip \
  --json-out fleetcarma_signal_candidates.json
```

The input may also be a single C5 `.BIN` file or a directory tree of them.

## What is measured

For every observed bus/CAN ID:

- total frames
- DLC histogram
- approximate frame period
- per-byte min/max
- per-byte change rate
- byte-to-GPS-speed Pearson correlation
- adjacent 16-bit little-endian and big-endian correlation to GPS speed
- overlap/sample count

GPS speed comes from NMEA VTG sentences recorded by the C5 logger. CAN samples
are paired only with GPS speed observations from the same FleetCarma file and
within the configured maximum time separation.

## Evidence policy

The output schema is
`atlas.fleetcarma-signal-correlation.v1` and the mapping status is always
`candidateOnly`.

Suggested interpretation:

- `strongCandidate`: absolute speed correlation >= 0.95
- `candidate`: >= 0.80
- `weakCandidate`: >= 0.60
- `background`: below 0.60

These are prioritization labels, not confirmation labels.

A candidate should only be promoted into the Atlas vehicle signal catalog after
it is independently reproduced in a controlled live Volt capture. A useful
validation sequence is stationary -> low speed -> moderate speed -> stationary,
with an operator marker and a trusted external speed reference.
