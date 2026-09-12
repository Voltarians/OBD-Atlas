# OBD Atlas J2534 trace format v1

`obd-atlas.j2534-trace.v1` is the application-side evidence format for the planned Windows J2534 PassThru observer/forwarder.

The format is **JSON Lines**: one complete JSON object per line. It is append-only so a partially completed or interrupted diagnostic session still leaves useful evidence.

## Safety boundary

The standalone Python trace writer/parser does not load a J2534 DLL, open an interface, transmit CAN, change filters, set programming voltage, or synthesize vehicle messages.

The native Windows proxy now uses the same trace semantics while forwarding only the currently accepted device, channel, and filter APIs to a selected provider. Atlas must never generate an extra request merely because tracing is enabled.

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
- `api`, for example `PassThruOpen`, `PassThruConnect`, `PassThruStartMsgFilter`, or later `PassThruWriteMsgs`
- `threadId`
- `deviceId` and `channelId` when applicable
- `arguments`
- optional normalized `messages`

The trace writer never changes the caller's message object.

`PassThruConnect` records the exact `ProtocolID`, `Flags`, and `BaudRate` supplied by the caller. `PassThruDisconnect` records the supplied channel ID.

`PassThruStartMsgFilter` records the supplied filter type plus the mask, pattern, and flow-control `PASSTHRU_MSG` metadata and payload bytes. The native proxy caps observation at the fixed J2534 message-buffer capacity if a malformed `DataSize` exceeds that capacity; it does not change the caller's structure. `PassThruStopMsgFilter` records the supplied filter ID.

## Call end

A matching `callEnd` contains:

- the same `callId` and `api`
- `returnCode`
- `durationNs`
- `outputs`
- optional returned/read `messages`
- optional `errorText`

Return codes and output buffers must reflect the real vendor DLL result. For Connect, Atlas records a returned channel ID only when the provider reports success. For StartMsgFilter, Atlas records a returned filter ID only when the provider reports success. Failed calls do not cause Atlas to read or modify undefined caller output buffers.

## Message representation

Normalized J2534 messages can retain fields such as:

- protocol ID
- receive status
- transmit flags
- provider/J2534 timestamp
- diagnostic service when Atlas has decoded it
- data size / extra-data index
- either `payloadHex` or a redacted digest

Filter-definition messages are configuration metadata rather than diagnostic request payloads, so their exact bytes are retained for equivalence testing.

Atlas does not guess a diagnostic service from arbitrary transport bytes inside the trace writer. The future message proxy/decoder must explicitly provide the decoded service when known.

## Sensitive payload policy

By default:

- service `0x27` SecurityAccess payloads are redacted
- service `0x36` TransferData payloads are redacted

A redacted message preserves:

- byte length
- SHA-256 of the original bytes
- service identity

This allows traces to be compared without putting security values or programming transfer blocks into ordinary logs.

Explicit inclusion is supported by the Python library for controlled bench/research cases, but it is not the default Atlas policy.

## Current implementation

- Schema: `assets/schemas/j2534_trace_v1.schema.json`
- Writer/parser: `tool/j2534_trace.py`
- Python tests: `tests/test_j2534_trace.py`
- Native Windows proxy: `native/j2534_proxy/`

The native proxy currently forwards and traces only:

- `PassThruOpen`
- `PassThruClose`
- `PassThruConnect`
- `PassThruDisconnect`
- `PassThruStartMsgFilter`
- `PassThruStopMsgFilter`
- `PassThruReadVersion`
- `PassThruGetLastError`

Windows CI compares direct fake-provider behavior with proxied behavior for device lifecycle, channel lifecycle, and ISO15765 flow-control filter setup/teardown, verifies fail-closed provider identity, and stress-tests concurrent trace ordering. No message read/write, IOCTL, or programming-voltage API is enabled yet.

## Proxy acceptance gate

Before any J2534 proxy is used with SPS/SPS2 or DPS programming, off-vehicle and bench tests must demonstrate that enabling the proxy does not materially change:

1. exported API behavior;
2. argument values passed to the real provider;
3. returned status codes;
4. output message count/order/content;
5. filter definitions;
6. IOCTL buffers;
7. programming-voltage requests;
8. call ordering; and
9. timing beyond a documented bounded tracing overhead.

Device Open/Close, Connect/Disconnect, and Start/StopMsgFilter are now staged behind direct-vs-proxy tests, but the overall vehicle/programming gate remains closed until the remaining message/IOCTL/programming-voltage stages pass independently.

Until that gate passes, Windows Atlas raw-bus capture through independent passive adapters remains the approved vehicle-observation method.
