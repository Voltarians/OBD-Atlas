# OBD Atlas J2534 message-forwarding proxy

This directory contains the **off-vehicle connection, periodic-message, filter, message, IOCTL, and guarded programming-voltage** foundation for the planned Windows J2534 observer/forwarder.

## Current exported API

The proxy currently forwards:

- `PassThruOpen`
- `PassThruClose`
- `PassThruConnect`
- `PassThruDisconnect`
- `PassThruStartPeriodicMsg`
- `PassThruStopPeriodicMsg`
- `PassThruStartMsgFilter`
- `PassThruStopMsgFilter`
- `PassThruReadMsgs`
- `PassThruWriteMsgs`
- `PassThruIoctl`
- `PassThruSetProgrammingVoltage` — exported but blocked by default
- `PassThruReadVersion`
- `PassThruGetLastError`

The remaining J2534 surface is not implemented yet.

This DLL is still **not authorized for GDS2/SPS2/DPS vehicle use**. It only forwards calls made by the source application; Atlas never synthesizes an extra diagnostic request, periodic message, IOCTL, or programming-voltage request. The current gates prove forwarding against an off-vehicle fake provider.

## Configuration

The proxy is configured with environment variables before it is loaded:

- `OBD_ATLAS_J2534_REAL_DLL` — exact real/fake provider DLL path; required.
- `OBD_ATLAS_J2534_TRACE_PATH` — new JSONL trace path; required. The proxy uses create-new semantics.
- `OBD_ATLAS_J2534_SOURCE_APP` — source application identity, for example `gds2`.
- `OBD_ATLAS_J2534_SOURCE_APP_VERSION` — source application version.
- `OBD_ATLAS_J2534_PROVIDER_NAME` — provider name selected by Atlas inventory.
- `OBD_ATLAS_J2534_PROVIDER_VENDOR` — provider vendor.
- `OBD_ATLAS_J2534_PROVIDER_REGISTRY_PATH` — exact PassThru registry path.
- `OBD_ATLAS_J2534_PROVIDER_REGISTRY_SUBKEY` — exact provider subkey.
- `OBD_ATLAS_J2534_PROVIDER_FINGERPRINT` — 64-character lowercase SHA-256 provider fingerprint.
- `OBD_ATLAS_J2534_ALLOW_PROGRAMMING_VOLTAGE=1` — explicit opt-in required before programming-voltage calls can reach the provider.

The proxy fails closed if the required provider fingerprint is missing/invalid and rejects a configuration where the real-provider DLL resolves to the proxy itself.

Programming-voltage forwarding is separately fail-closed. Only the exact value `1` enables it; unset, empty, `0`, `true`, `yes`, `01`, and similar values remain blocked.

## Trace behavior

The DLL emits `obd-atlas.j2534-trace.v1` JSONL records with one session record and paired `callBegin` / `callEnd` records.

`PassThruConnect`, periodic messages, filters, ReadMsgs, and WriteMsgs retain the transparency behavior documented in `docs/J2534_TRACE_FORMAT.md`. SecurityAccess (`0x27`) and TransferData (`0x36`) write payloads are redacted in the trace by default while their original bytes are still forwarded unchanged to the provider.

`PassThruStartPeriodicMsg` records the exact caller-supplied message snapshot and interval before forwarding. A provider-assigned message ID is recorded only on successful return. `PassThruStopPeriodicMsg` records the exact caller-supplied periodic message ID. Atlas does not create, alter, reschedule, or stop any periodic message on its own.

`PassThruIoctl` passes the caller's **original `pInput` and `pOutput` pointers unchanged** to the provider. Atlas only interprets structures whose J2534 shape is known:

- `GET_CONFIG` / `SET_CONFIG` — observes `SCONFIG_LIST` values before and/or after the provider call;
- `READ_VBATT` — observes the returned unsigned-long voltage;
- `READ_PROG_VOLTAGE` — may observe the returned unsigned-long voltage if a caller uses that read-only IOCTL.

For all other IOCTL IDs, Atlas records only the IOCTL ID and pointer presence. It does **not** dereference unknown opaque buffers. Known-buffer snapshots use `ReadProcessMemory` against the current process so tracing does not add an ordinary invalid-pointer dereference before provider forwarding.

`PassThruSetProgrammingVoltage` records the requested pin, raw voltage value, whether the explicit safety policy was enabled, whether the selected provider exposes the function, and whether the provider was actually called. When policy is disabled, Atlas returns `ERR_NOT_SUPPORTED` without invoking the provider. When explicitly enabled, Atlas forwards the exact caller-supplied device ID, pin number, and voltage unchanged and returns the provider result unchanged.

Important distinction: `READ_PROG_VOLTAGE` is a read-only IOCTL. `PassThruSetProgrammingVoltage` can request a provider to drive voltage and is therefore guarded by the additional opt-in policy documented in `docs/J2534_PROGRAMMING_VOLTAGE_POLICY.md`.

## Off-vehicle transparency tests

Windows CTest compares direct-provider and proxied behavior for:

- device lifecycle and version/error text;
- Connect/Disconnect;
- StartPeriodicMsg/StopPeriodicMsg, including exact message/interval forwarding and rejected-interval output preservation;
- ISO15765 flow-control filters;
- ReadMsgs success and timeout paths;
- WriteMsgs ordinary DID requests, sensitive payload redaction, and timeout behavior;
- IOCTL `SET_CONFIG`, `GET_CONFIG`, `READ_VBATT`, and an invalid opaque IOCTL;
- programming-voltage policy behavior and end-to-end guarded forwarding;
- fail-closed invalid provider identity; and
- concurrent trace sequence ordering.

The programming-voltage integration test proves that a default-blocked call never reaches the fake provider, an explicitly enabled call reaches it with exact device/pin/voltage arguments, provider errors are preserved, and both policy decisions are visible in the trace.

## Acceptance boundary

Passing these off-vehicle tests does **not** authorize vehicle or programming use. Remaining gates include:

- any additional J2534 calls required by the selected GM tool/provider;
- sustained-load ordering/timeout equivalence;
- bounded trace overhead;
- provider-specific testing against real vendor DLLs; and
- fail-safe bench-interface validation before any in-vehicle session.

Programming voltage must remain disabled during ordinary diagnostic observation. Enabling it is reserved for a later, explicitly approved bench or programming workflow.

Until those gates pass, Windows Atlas's independent passive CAN/SWCAN adapters remain the approved vehicle-observation method.
