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

## Trace durability and group commit

Trace records are still written synchronously and in sequence, but the proxy no longer calls the physical `FlushFileBuffers()` operation for every individual JSONL record.

The bounded group-commit policy physically commits the file when any of these conditions is met:

- the session record is written;
- 256 records have accumulated since the previous physical commit;
- 100 ms has elapsed since the previous physical commit and another trace record is written;
- a `PassThruClose` call completes;
- a `PassThruDisconnect` call completes;
- a `PassThruStopPeriodicMsg` call completes; or
- a `PassThruSetProgrammingVoltage` call completes.

This preserves ordered append-only evidence while bounding the abnormal-termination exposure to the most recent uncommitted group. A normal Close/Disconnect path forces a final durable boundary. The policy does not alter J2534 buffers, provider calls, return codes, or call ordering.

The policy has its own Windows acceptance test proving immediate session/lifecycle commits, ordinary-record batching, the 256-record count boundary, and the 100 ms age boundary.

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
- fail-closed invalid provider identity;
- concurrent trace sequence ordering;
- bounded trace group-commit behavior; and
- a 100,000-operation, four-thread sustained-load transparency run.

The programming-voltage integration test proves that a default-blocked call never reaches the fake provider, an explicitly enabled call reaches it with exact device/pin/voltage arguments, provider errors are preserved, and both policy decisions are visible in the trace.

The 100,000-operation gate mixes successful reads/writes, read/write timeouts, `GetLastError`, `READ_VBATT`, SecurityAccess, TransferData, an active flow-control filter, and an active periodic message. It requires zero direct-vs-proxy result mismatches, contiguous trace sequence numbers, correctly paired begin/end records, and no sensitive payload leakage.

### CI performance result

With physical `FlushFileBuffers()` on every trace record, the Windows native CTest step took **944 seconds** on the measured GitHub Actions run. With bounded group commit, the same native suite including the same 100,000-operation gate took **12 seconds** on the next measured Windows run, about a **79x reduction in complete native-suite wall time**. Runner-to-runner timing varies, so this is evidence of the order-of-magnitude improvement rather than a permanent fixed latency guarantee.

## Acceptance boundary

Passing these off-vehicle tests does **not** authorize vehicle or programming use. Remaining gates include:

- any additional J2534 calls actually required by the selected GM tool/provider;
- provider-specific testing against real vendor DLLs;
- sustained-load and latency characterization with those real vendor DLLs;
- fail-safe bench-interface validation; and
- a deliberately staged first GDS2/SPS2/DPS session before any production/programming use.

Programming voltage must remain disabled during ordinary diagnostic observation. Enabling it is reserved for a later, explicitly approved bench or programming workflow.

Until those gates pass, Windows Atlas's independent passive CAN/SWCAN adapters remain the approved vehicle-observation method.
