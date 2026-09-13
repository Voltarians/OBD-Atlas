# GM Tool Evidence Bundle

## Purpose

`tool/build_gm_tool_evidence_bundle.py` is the Phase C correlation stage for Atlas GM-tool research. It combines evidence that already exists; it does not open a J2534 provider, control an adapter, or transmit vehicle traffic.

The primary use case is a Windows GDS2 session where Atlas has both an independent raw candump capture and an Atlas J2534 proxy trace. The same format can also preserve SPS2/DPS sessions and optional synchronized voice-marker reports.

## Inputs

The builder accepts:

- `--capture` — Atlas/candump capture. Embedded `# ATLAS_EVENT (...)` click/discovery markers are imported automatically.
- `--j2534-trace` — `obd-atlas.j2534-trace.v1` JSONL from the Windows forwarding proxy.
- `--voice-correlation` — optional `obd-atlas.voice-event-correlation.v1` report; repeat the option for multiple reports.
- `--source-application` — optional source override such as `gds2`, `sps2`, or `dps`. When omitted, the J2534 session identity is used when available.

Every source file is recorded with path, byte size, and SHA-256 so the derived report can be tied back to the exact evidence used.

## Derived layers

When a candump capture is supplied, the builder runs the existing read-only GM extraction logic in-process and includes:

- generic GM/UDS diagnostic events;
- matched request/response transactions and latency;
- endpoint traffic using provenance-preserving address catalogs;
- Gen-1 HPCM2 physical `0x22` DID transactions;
- GM `0x2C` / `0xAA` dynamic packet definitions, controls, and samples;
- Atlas operator markers embedded in the raw capture.

When a J2534 trace is supplied, the bundle also includes the validated trace records and summary plus normalized application-side message events from `PassThruWriteMsgs`, `PassThruReadMsgs`, and `PassThruStartPeriodicMsg`.

## Correlation

The J2534-to-bus correlator uses direction, time, diagnostic service, and payload when the payload is available. A typical ISO15765 J2534 provider places a four-byte CAN identifier before the diagnostic payload; the correlator tests both the full logged payload and the suffix after those four bytes without assuming that every provider uses that layout.

Correlation status is deliberately descriptive:

- `exactPayloadAndTimeMatch` — application-side and raw-bus payloads agree inside the time window;
- `serviceAndTimeCandidate` — service and timing agree but a byte-for-byte comparison is unavailable or does not agree;
- `timeOnlyCandidate` — only timing/direction provide a lead;
- `noBusCandidateInWindow` — no raw diagnostic event met the configured window.

These statuses describe evidence alignment only. They do **not** promote a module identity, DID meaning, signal definition, or vehicle behavior to confirmed.

Operator markers are correlated to nearby decoded diagnostic events. Voice markers retain `voiceSupportingEvidenceOnly`; uncalibrated microphone latency remains visible in the imported marker metadata.

## Sensitive payloads

The J2534 proxy's existing redaction policy remains authoritative. SecurityAccess (`0x27`) and TransferData (`0x36`) messages that were recorded as redacted are never reconstructed by the bundle builder. Raw source files remain separately hash-verifiable evidence.

## Example

```bash
python3 tool/build_gm_tool_evidence_bundle.py \
  --capture atlas_gds2_capture.log \
  --j2534-trace gds2_j2534.jsonl \
  --source-application gds2 \
  --output gds2_evidence_bundle.json
```

With an optional synchronized voice report:

```bash
python3 tool/build_gm_tool_evidence_bundle.py \
  --capture atlas_gds2_capture.log \
  --j2534-trace gds2_j2534.jsonl \
  --voice-correlation atlas_gds2_capture.voice.correlation.json \
  --output gds2_evidence_bundle.json
```

## Safety and evidence boundary

The output schema is `obd-atlas.gm-tool-evidence-bundle.v1` and explicitly records that the builder:

- does not load a J2534 provider;
- does not open a vehicle adapter;
- does not transmit vehicle traffic; and
- does not authorize signal promotion.

The bundle is derived evidence. Raw CAN, J2534 traces, audio, manifests, and other source artifacts remain the authoritative preserved evidence and should be retained unchanged.
