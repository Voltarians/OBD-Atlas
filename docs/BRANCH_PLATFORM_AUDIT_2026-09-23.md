# OBD Atlas branch/platform audit — 2026-09-23

Current main: a191b4c55f39534ed9a862a8f9bf38af9b904055 (Alpha 5 merge).

## Executive result

Atlas is not yet branch-clean or platform-parity clean. There are 39 non-main branches. Several old foundation branches are fully behind main and can be treated as incorporated history, while a number of Linux/ARM64/MX+ branches still contain commits not present on main.

## Platform branch audit

### Incorporated / no unique commits versus main

- build/linux-pcg1-foundation — 0 ahead, 266 behind
- build/offline-frontend-foundation — 0 ahead, 319 behind

These have no unique commits remaining relative to main.

### Unique work still outside main

- feature/linux-event-discovery — 4 ahead / 280 behind
- feature/linux-mxplus — 11 ahead / 275 behind
- feature/mxplus-fast-monitor — 1 ahead / 273 behind
- feature/mxplus-swcan — 2 ahead / 269 behind
- fix/arm64-flutter-source-install — 1 ahead / 276 behind
- fix/arm64-release-toolchain — 1 ahead / 277 behind
- fix/linux-mxplus-rfcomm-crash — 5 ahead / 274 behind
- fix/mxplus-linux-autoconnect — 7 ahead / 267 behind
- fix/mxplus-raw-stm-monitor — 4 ahead / 271 behind
- release/alpha4-mxplus-fast — 1 ahead / 272 behind

Do not merge these stale branches wholesale. Audit/cherry-pick or reimplement the still-relevant deltas on current main.

## Open PRs at audit time

- #16 Add external app observation correlator
- #28 Add provenance-labelled OVMS Gen-1 CAN candidates
- #29 Port vehicle identity and private intake foundation
- #37 Define PCG-1 passive multi-bus discovery gate

## Platform parity gate

Before declaring Android, Linux/ARM64, and Windows current:

1. inventory platform entrypoints and CI workflows on current main;
2. port only still-relevant unique deltas from stale branches;
3. run shared unit tests once against the consolidated code;
4. build Linux/ARM64, Windows x64, and Android from the same commit;
5. record artifact commit SHA and acceptance result for each platform;
6. retire branches only after their unique work is either incorporated or explicitly superseded.

## Immediate consolidation order

1. PCG-1 passive discovery (#37) and Linux event-discovery delta.
2. MX+ Linux adapter/autoconnect/raw monitor/SWCAN deltas as one current-main integration.
3. ARM64 release-toolchain fixes.
4. Vehicle identity (#29), observation correlator (#16), and research candidates (#28) after conflict review.
5. Build all three target platforms from one resulting commit.

No branch should be deleted merely because it is old; first prove it has zero unique useful work or record what supersedes it.
