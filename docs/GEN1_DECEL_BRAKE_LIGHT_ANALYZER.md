# Gen-1 Volt Deceleration Brake-Light Capture Analyzer

`tool/analyze_gen1_decel_brake_light.py` is the offline analysis step for the controlled road test in `GEN1_DECEL_BRAKE_LIGHT_ROAD_TEST.md`.

It is passive. It reads a saved Atlas candump-compatible log and does not transmit CAN traffic or command any vehicle lamp.

## What it does

The analyzer:

- reads Atlas `# ATLAS_EVENT` markers directly from the capture;
- creates windows for D steady, D accelerator lift, L accelerator lift, light braking, and medium braking;
- decodes the current `0x3E9` vehicle-speed candidate and derives longitudinal deceleration from the speed slope;
- aligns the confirmed `0x0F1` brake-pedal state;
- aligns `0x1F5` gear position and the `0x1C3` accelerator-position candidate;
- aligns the `0x2C7` and `0x210` pack-current candidates;
- compares candidate pack-current behavior between D steady, D lift, and L lift without silently treating either current signal as validated regen;
- ranks every changing CAN byte against derived deceleration and against the L-lift versus D-lift contrast to help locate longitudinal-acceleration and regen-related messages;
- can replay the software-only `regen_brake_light_request` hysteresis after a candidate regen-current source and polarity are explicitly selected.

## First pass after tomorrow's capture

Run without a regen source first:

```bash
python3 tool/analyze_gen1_decel_brake_light.py \
  atlas_capture_YYYYMMDD_HHMMSS.log \
  --json-out gen1_decel_report.json \
  --csv-out gen1_decel_timeline.csv
```

This deliberately leaves `regenBrakeLightRequest` unasserted because regen has not yet been independently validated. The report still contains the deceleration timeline, event summaries, pack-current correlations, and ranked candidate bytes.

## Speed decode

Two closely related community interpretations of `0x3E9` are retained:

- `kph64`: unsigned big-endian first two bytes, `1/64 km/h` per count;
- `mph01`: unsigned big-endian first two bytes, `0.01 mph` per count.

`--speed-decode auto` uses the road-test `DBL_10_D_STEADY` 25-30 mph protocol window only to choose the closer analysis scaling. That is a convenience for this experiment, not independent validation. Use `--speed-decode kph64` or `--speed-decode mph01` to force either interpretation.

## Shadow replay after current polarity is understood

The analyzer will not infer a candidate current signal into the shadow controller automatically. After the capture demonstrates which current candidate and sign track regen, replay can be requested explicitly, for example:

```bash
python3 tool/analyze_gen1_decel_brake_light.py \
  atlas_capture_YYYYMMDD_HHMMSS.log \
  --regen-source 210-negative \
  --regen-threshold-a 1.0 \
  --json-out gen1_decel_shadow_report.json \
  --csv-out gen1_decel_shadow_timeline.csv
```

Available research inputs are `2c7-positive`, `2c7-negative`, `210-positive`, and `210-negative`.

Selecting one only tells the offline analyzer how to replay the candidate. It does **not** promote that current decode or polarity to a confirmed Gen-1 signal.

## Important report fields

`eventSummary` gives per-window speed, deceleration, brake usage, current candidates, and observed gear states.

`regenCurrentCorrelation` shows how each pack-current candidate changes during L lift relative to D steady and D lift. It remains explicitly tagged `candidateOnly`.

`candidateBytes` ranks raw byte positions using two independent clues: correlation with speed-derived deceleration and raw separation between L lift and D lift. A high score is a discovery lead, not proof of signal meaning.

`timeline` is the aligned sample-by-sample dataset used for CSV export and later plotting.

## Promotion rule

No candidate from this analyzer should be added to the confirmed Gen-1 signal catalog solely because it ranks highly. Promotion still requires a controlled repeatable relationship, correct scaling/sign determination, and preferably an independent source such as GM diagnostic data, a second measurement path, or repeated captures under deliberately different conditions.
