# Linux event-discovery port audit

Source branch: `feature/linux-event-discovery`
Target: current-main-based `feature/pcg1-passive-discovery`

The source branch is 4 commits ahead and 280 commits behind current main.

## Result

The two core event-discovery artifacts are already present byte-for-byte on the current target:

- `lib/core/signal_discovery.dart`
- `test/core/signal_discovery_test.dart`

Therefore the discovery algorithm and its unit test do **not** need to be cherry-picked.

The source branch also modifies:

- `lib/core/atlas_runtime.dart`
- `lib/main_linux.dart`

Those files have materially evolved on current main (including the current five-channel PCG-1 and OBDLink/Linux integration). The stale versions must not replace the current files wholesale.

## Consolidation decision

Treat the old event-discovery branch's standalone discovery engine as already incorporated. Preserve current `atlas_runtime.dart` and `main_linux.dart`, and integrate any missing event-discovery UI/runtime hooks directly against their current implementations as part of PCG-1 passive discovery.

This avoids reintroducing 280 commits of stale history or overwriting newer PCG-1/MX+ functionality.

## Gate

The old branch can be considered superseded only after current-main CI confirms the existing signal-discovery test and the PCG-1 discovery workflow exposes the current engine.
