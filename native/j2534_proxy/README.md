# OBD Atlas J2534 message-forwarding proxy

This directory contains the **off-vehicle connection, filter, message, and IOCTL** foundation for the planned Windows J2534 observer/forwarder.

## Current exported API

The proxy currently forwards:

- `PassThruOpen`
- `PassThruClose`
- `PassThruConnect`
- `PassThruDisconnect`
- `PassThruStartMsgFilter`
- `PassThruStopMsgFilter`
- `PassThruReadMsgs`
- `PassThruWriteMsgs`
- `PassThruIoctl`
- `PassThruReadVersion`
- `PassThruGetLastError`

It does **not** currently export `PassThruSetProgrammingVoltage`, periodic-message APIs, or the remaining J2534 surface.

This DLL is still **not authorized for GDS2/SPS2/DPS vehicle use**. It only forwards calls made by the source application; Atlas never synthesizes an extra diagnostic request or IOCTL. The current gates prove forwarding against an off-vehicle fake provider.

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

The proxy fails closed if the required provider fingerprint is missing/invalid and rejects a configuration where the real-provider DLL resolves to the proxy itself.

## Trace behavior

The DLL emits `obd-atlas.j2534-trace.v1` JSONL records with one session record and paired `callBegin` / `callEnd` records.

`PassThruConnect`, filters, ReadMsgs, and WriteMsgs retain the transparency behavior documented in `docs/J2534_TRACE_FORMAT.md`. SecurityAccess (`0x27`) and TransferData (`0x36`) write payloads are redacted in the trace by default while their original bytes are still forwarded unchanged to the provider.

`PassThruIoctl` passes the caller's **original `pInput` and `pOutput` pointers unchanged** to the provider. Atlas only interprets structures whose J2534 shape is known:

- `GET_CONFIG` / `SET_CONFIG` — observes `SCONFIG_LIST` values before and/or after the provider call;
- `READ_VBATT` — observes the returned unsigned-long voltage;
- `READ_PROG_VOLTAGE` — may observe the returned unsigned-long voltage if a caller uses that read-only IOCTL.

For all other IOCTL IDs, Atlas records only the IOCTL ID and pointer presence. It does **not** dereference unknown opaque buffers. Known-buffer snapshots use `ReadProcessMemory` against the current process so tracing does not add an ordinary invalid-pointer dereference before provider forwarding.

Important distinction: `READ_PROG_VOLTAGE` is an IOCTL read. The voltage-setting API `PassThruSetProgrammingVoltage` remains unimplemented and unexported.

## Off-vehicle transparency tests

Windows CTest compares direct-provider and proxied behavior for:

- device lifecycle and version/error text;
- Connect/Disconnect;
- ISO15765 flow-control filters;
- ReadMsgs success and timeout paths;
- WriteMsgs ordinary DID requests, sensitive payload redaction, and timeout behavior;
- IOCTL `SET_CONFIG`, `GET_CONFIG`, `READ_VBATT`, and an invalid opaque IOCTL;
- fail-closed invalid provider identity; and
- concurrent trace sequence ordering.

The IOCTL test specifically requires identical return codes, configuration arrays, returned battery voltage, and untouched sentinel input/output buffers on the rejected IOCTL path.

## Acceptance boundary

Passing these off-vehicle tests does **not** authorize vehicle or programming use. Remaining gates include:

- `PassThruSetProgrammingVoltage` forwarding and an explicit safety policy;
- periodic-message APIs and any additional J2534 calls required by the selected GM tool/provider;
- sustained-load ordering/timeout equivalence;
- bounded trace overhead;
- provider-specific testing against real vendor DLLs; and
- fail-safe bench-interface validation before any in-vehicle session.

Until those gates pass, Windows Atlas's independent passive CAN/SWCAN adapters remain the approved vehicle-observation method.
