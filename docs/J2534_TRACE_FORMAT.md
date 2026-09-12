# OBD Atlas J2534 trace format v1

`obd-atlas.j2534-trace.v1` is the application-side evidence format for the planned Windows J2534 PassThru observer/forwarder.

The format is **JSON Lines**: one complete JSON object per line. It is append-only so a partially completed or interrupted diagnostic session still leaves useful evidence.

## Safety boundary

The standalone Python trace writer/parser does not load a J2534 DLL, open an interface, transmit CAN, change filters, set programming voltage, or synthesize vehicle messages.

The native Windows proxy now uses the same trace semantics while forwarding the currently accepted device, channel, filter, read, and write-message APIs to a selected provider. Atlas must never generate an extra request merely because tracing is enabled. `PassThruWriteMsgs` forwards only the message array supplied by the calling application and is still restricted to off-vehicle acceptance testing until the remaining J2534 and bench-safety gates pass.

## Record ordering

Every record contains:

- `schema`: `obd-atlas.j2534-trace.v1`
- `recordType`: `session`, `callBegin`, or `callEnd`
- `sequence`: contiguous integer beginning at 0
- `utc`: wall-clock UTC timestamp
- `monotonicNs`: monotonic timestamp used for latency/order correlation

The first record is always `session`.

Each PassThru invocation produces a `callBegin` before forwarding the call and a matching `callEnd` after the vendor DLL returns. Both share one `callId`.

This two-record model is intentional: if a provider call blocks, crashes, or the process terminates, the unmatched `callBegin` remains visible in the evidence.

## Session record

The session record identifies the application and selected provider:

- `sourceApplication`, such as `gds2`, `sps2`, or `dps`
- `sourceApplicationVersion` when known
- provider registry path/subkey, vendor, name, and function-library metadata
- `providerFingerprintSha256`, computed from the normalized provider identity
- `sensitivePayloadPolicy`
- `observerMode: transparent-forwarder`
- `proxyMayTransmitIndependently: false`

The fingerprint is intended to make it obvious when two traces were produced against different J2534 registrations or DLL builds.

## Call begin

A `callBegin` may contain:

- `callId`
- `api`, for example `PassThruOpen`, `PassThruConnect`, `PassThruStartMsgFilter`, `PassThruReadMsgs`, or `PassThruWriteMsgs`
- `threadId`
- `deviceId` and `channelId` when applicable
- `arguments`
- optional normalized `messages`

The trace writer never changes the caller's message object.

`PassThruConnect` records the exact `ProtocolID`, `Flags`, and `BaudRate` supplied by the caller. `PassThruDisconnect` records the supplied channel ID.

`PassThruStartMsgFilter` records the supplied filter type plus the mask, pattern, and flow-control `PASSTHRU_MSG` metadata and payload bytes. The native proxy caps observation at the fixed J2534 message-buffer capacity if a malformed `DataSize` exceeds that capacity; it does not change the caller's structure. `PassThruStopMsgFilter` records the supplied filter ID.

`PassThruReadMsgs` records the caller's requested message count, message/count pointer presence, and timeout before forwarding the call unchanged to the provider.

`PassThruWriteMsgs` records the caller's requested message count and timeout plus a normalized snapshot of the exact input message array **before** forwarding. Atlas passes the original `pMsg` and `pNumMsgs` pointers directly to the selected provider; tracing does not create a replacement transmit buffer.

## Call end

A matching `callEnd` contains:

- the same `callId` and `api`
- `returnCode`
- `durationNs`
- `outputs`
- optional returned/read `messages`
- optional `errorText`

Return codes and output buffers must reflect the real vendor DLL result. For Connect, Atlas records a returned channel ID only when the provider reports success. For StartMsgFilter, Atlas records a returned filter ID only when the provider reports success. Failed calls do not cause Atlas to read or modify undefined caller output buffers.

For `PassThruReadMsgs`, the native proxy records the provider-returned message count and snapshots at most the caller's original requested capacity. If a malformed provider reports more messages than the caller allocated, the trace marks the capture as truncated rather than reading beyond the caller buffer. Atlas does not rewrite the caller's `pMsg` array or `pNumMsgs` value after the provider returns.

For `PassThruWriteMsgs`, Atlas records the provider-returned message count after forwarding. The acceptance harness compares the caller's message structures before and after both direct and proxied writes to ensure the proxy does not alter them.

## Message representation

Normalized J2534 messages can retain fields such as:

- protocol ID
- receive status
- transmit flags
- provider/J2534 timestamp
- diagnostic service when Atlas has explicitly decoded it
- data size / extra-data index
- either `payloadHex` or a redacted digest

Filter-definition messages are configuration metadata rather than diagnostic request payloads, so their exact bytes are retained for equivalence testing.

Read-message tracing currently retains the exact provider-returned payload bytes during the off-vehicle acceptance stage so direct-vs-proxy equivalence can be proven.

Write-message tracing applies the sensitive-payload policy before anything is written to disk. Ordinary request payloads remain visible for equivalence and DID/service mapping. SecurityAccess and TransferData requests are represented by length, service identity, and digest instead of their original bytes.

## Sensitive payload policy

By default:

- service `0x27` SecurityAccess write payloads are redacted
- service `0x36` TransferData write payloads are redacted

A redacted message preserves:

- byte length
- SHA-256 of the original J2534 message bytes
- service identity
- non-payload J2534 metadata

The native proxy uses Windows CNG SHA-256 for this digest. Redaction affects only the trace snapshot; the application-supplied buffer is forwarded unchanged to the provider.

Sensitive-service detection is intentionally transport-aware rather than a raw-byte scan. For ISO15765 messages Atlas examines the diagnostic portion after the four-byte arbitration ID and recognizes direct service bytes plus valid ISO-TP single-frame and first-frame forms. It does not label an arbitrary occurrence of `0x27` or `0x36` elsewhere in the message as a sensitive service.

This allows traces to be compared without placing security values or programming transfer blocks into ordinary logs.

Explicit inclusion is supported by the platform-independent Python library for controlled bench/research cases, but sensitive inclusion is not enabled in the native Windows proxy at this stage.

## Current implementation

- Schema: `assets/schemas/j2534_trace_v1.schema.json`
- Writer/parser: `tool/j2534_trace.py`
- Python tests: `tests/test_j2534_trace.py`
- Native Windows proxy: `native/j2534_proxy/`

The native proxy currently forwards and traces:

- `PassThruOpen`
- `PassThruClose`
- `PassThruConnect`
- `PassThruDisconnect`
- `PassThruStartMsgFilter`
- `PassThruStopMsgFilter`
- `PassThruReadMsgs`
- `PassThruWriteMsgs`
- `PassThruReadVersion`
- `PassThruGetLastError`

Windows CI compares direct fake-provider behavior with proxied behavior for device lifecycle, channel lifecycle, ISO15765 flow-control filter setup/teardown, successful/timeout reads, and successful/timeout writes. The write test also proves ordinary payload visibility and default SecurityAccess/TransferData trace redaction. CI additionally verifies fail-closed provider identity and stress-tests concurrent trace ordering.

IOCTL, programming-voltage, periodic-message, and other remaining J2534 APIs are not enabled yet.

## Proxy acceptance gate

Before any J2534 proxy is used with SPS/SPS2 or DPS programming, off-vehicle and bench tests must demonstrate that enabling the proxy does not materially change:

1. exported API behavior;
2. argument values passed to the real provider;
3. returned status codes;
4. input/output message count, order, metadata, and content;
5. filter definitions;
6. IOCTL buffers;
7. programming-voltage requests;
8. call ordering; and
9. timing beyond a documented bounded tracing overhead.

Device Open/Close, Connect/Disconnect, Start/StopMsgFilter, ReadMsgs, and WriteMsgs are now staged behind direct-vs-proxy tests, but the overall vehicle/programming gate remains closed until the remaining IOCTL/programming-voltage/provider-specific and bench-safety stages pass independently.

Until that gate passes, Windows Atlas raw-bus capture through independent passive adapters remains the approved vehicle-observation method.
