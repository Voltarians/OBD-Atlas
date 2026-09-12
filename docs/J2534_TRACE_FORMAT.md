# OBD Atlas J2534 trace format v1

`obd-atlas.j2534-trace.v1` is the application-side evidence format for the planned Windows J2534 PassThru observer/forwarder.

The format is **JSON Lines**: one complete JSON object per line. It is append-only so a partially completed or interrupted diagnostic session still leaves useful evidence.

## Safety boundary

The standalone Python trace writer/parser does not load a J2534 DLL, open an interface, transmit CAN, change filters, set programming voltage, or synthesize vehicle messages.

The native Windows proxy uses the same trace semantics while forwarding the currently accepted device, channel, filter, message, and IOCTL APIs to a selected provider. Atlas never generates an extra request or IOCTL merely because tracing is enabled.

`PassThruSetProgrammingVoltage` remains unimplemented and unexported. The native proxy is still restricted to off-vehicle acceptance testing until the remaining API and bench-safety gates pass.

## Record ordering

Every record contains:

- `schema`: `obd-atlas.j2534-trace.v1`
- `recordType`: `session`, `callBegin`, or `callEnd`
- `sequence`: contiguous integer beginning at 0
- `utc`: wall-clock UTC timestamp
- `monotonicNs`: monotonic timestamp used for latency/order correlation

The first record is always `session`. Each PassThru invocation produces a `callBegin` before forwarding and a matching `callEnd` after the vendor DLL returns. Both share one `callId`.

## Session record

The session record identifies the source application and selected provider, including registry identity, DLL path metadata, a stable SHA-256 provider fingerprint, the sensitive-payload policy, `observerMode: transparent-forwarder`, and `proxyMayTransmitIndependently: false`.

## Call begin / end

A `callBegin` can record:

- API name and `callId`
- thread, device, and channel IDs
- structured arguments
- normalized message snapshots when applicable

A matching `callEnd` records the provider return code, duration, and structured outputs.

Return codes and caller buffers always remain the vendor DLL's results. Tracing is observational.

## Message representation

Filter messages retain exact metadata and bytes. ReadMsgs records returned count/order/metadata/payloads while bounding observation to the caller's original requested capacity. WriteMsgs snapshots the caller's input messages before forwarding and passes the original `pMsg` and `pNumMsgs` pointers directly to the provider.

SecurityAccess (`0x27`) and TransferData (`0x36`) write payloads are redacted by default. The trace retains message length, service identity, J2534 metadata, and SHA-256 instead of the original sensitive bytes. Redaction never changes what is forwarded to the provider.

## IOCTL representation

`PassThruIoctl(ChannelID, IoctlID, pInput, pOutput)` is forwarded with the caller's **original pointers unchanged**.

Atlas structurally observes only IOCTL buffers with a known J2534 04.04 shape:

- `GET_CONFIG` (`0x01`) — `pInput` is an `SCONFIG_LIST`; Atlas can snapshot the requested parameters before the call and provider-returned values afterward.
- `SET_CONFIG` (`0x02`) — `pInput` is an `SCONFIG_LIST`; Atlas snapshots the exact requested parameter/value pairs and the same memory after return.
- `READ_VBATT` (`0x03`) — `pOutput` is an unsigned long; Atlas records the returned value.
- `READ_PROG_VOLTAGE` (`0x0E`) — also an unsigned-long read result if the source application invokes it.

For all other IOCTL IDs, Atlas records only the IOCTL ID and whether input/output pointers were present. It does **not** interpret or dereference unknown opaque buffers.

Known snapshots are read using `ReadProcessMemory(GetCurrentProcess(), ...)` rather than ordinary pointer dereferences. This keeps evidence collection from adding a normal invalid-pointer access before the vendor DLL sees the original pointer.

`READ_PROG_VOLTAGE` is distinct from the voltage-setting API. `PassThruSetProgrammingVoltage` is still absent.

## Current native API surface

The native proxy currently forwards and traces:

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

## Acceptance tests

Windows CI compares direct fake-provider behavior with proxied behavior for:

- device and channel lifecycle;
- ISO15765 flow-control filters;
- successful and timeout ReadMsgs;
- successful and timeout WriteMsgs;
- SecurityAccess/TransferData redaction while forwarding the original bytes;
- IOCTL `SET_CONFIG`, `GET_CONFIG`, `READ_VBATT`, and an invalid opaque IOCTL;
- fail-closed provider identity; and
- concurrent trace sequence ordering.

The IOCTL test requires identical return codes, `SCONFIG` memory, battery-voltage output, and untouched sentinel buffers on the rejected IOCTL path.

## Proxy acceptance gate

Before use with SPS/SPS2, DPS, or other real vehicle/programming sessions, remaining gates include:

1. `PassThruSetProgrammingVoltage` behavior and safety policy;
2. periodic-message APIs and any remaining calls required by the chosen GM tool/provider;
3. sustained-load ordering and timeout equivalence;
4. bounded trace overhead;
5. provider-specific behavior against real vendor DLLs; and
6. fail-safe bench-interface validation before any in-vehicle session.

Until those gates pass, Windows Atlas raw-bus capture through independent passive adapters remains the approved vehicle-observation method.
