# OBD Atlas J2534 message-forwarding proxy

This directory contains the **off-vehicle connection, filter, read, and write message** foundation for the planned Windows J2534 observer/forwarder.

## Current exported API

Only these functions are implemented and forwarded:

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

The proxy does **not** currently export or forward IOCTLs, programming-voltage control, periodic-message APIs, or the remaining J2534 surface.

This DLL is still **not authorized for GDS2/SPS2/DPS vehicle use**. `PassThruWriteMsgs` forwards only messages the calling application supplied; Atlas never creates an extra request. The current gate proves forwarding against an off-vehicle fake provider, not a real vehicle or programming session.

## Configuration

The proxy is configured with environment variables before it is loaded:

- `OBD_ATLAS_J2534_REAL_DLL` — exact real/fake provider DLL path; required.
- `OBD_ATLAS_J2534_TRACE_PATH` — new JSONL trace path; required. The proxy uses create-new semantics and refuses to append to an existing trace.
- `OBD_ATLAS_J2534_SOURCE_APP` — source application identity, for example `gds2`; optional for the test harness.
- `OBD_ATLAS_J2534_SOURCE_APP_VERSION` — source application version; optional.
- `OBD_ATLAS_J2534_PROVIDER_NAME` — provider name selected by Atlas inventory.
- `OBD_ATLAS_J2534_PROVIDER_VENDOR` — provider vendor.
- `OBD_ATLAS_J2534_PROVIDER_REGISTRY_PATH` — exact PassThru registry path.
- `OBD_ATLAS_J2534_PROVIDER_REGISTRY_SUBKEY` — exact provider subkey.
- `OBD_ATLAS_J2534_PROVIDER_FINGERPRINT` — 64-character lowercase SHA-256 provider fingerprint from `tool/windows_j2534_inventory.py`.

The proxy fails closed if the required provider fingerprint is absent/invalid and rejects a configuration where `OBD_ATLAS_J2534_REAL_DLL` resolves to the proxy DLL itself.

## Trace behavior

The DLL emits `obd-atlas.j2534-trace.v1` JSONL records compatible with `tool/j2534_trace.py`:

1. one session record;
2. `callBegin` immediately before each forwarded API call;
3. matching `callEnd` immediately after the provider returns.

Each record has UTC and monotonic timing. Connect records the exact `ProtocolID`, `Flags`, and `BaudRate`; its returned `ChannelID` is recorded without modification. Disconnect records the supplied channel ID.

`PassThruStartMsgFilter` records the filter type plus the exact J2534 metadata and payload bytes supplied in the mask, pattern, and flow-control `PASSTHRU_MSG` structures. Atlas does not alter those structures before forwarding. A provider-assigned filter ID is recorded only after a successful call. `PassThruStopMsgFilter` records the supplied filter ID and channel ID.

`PassThruReadMsgs` records the caller's requested message count and timeout before forwarding. After the provider returns, Atlas records the provider's returned message count and snapshots at most the caller's original requested capacity. Each captured message records `ProtocolID`, `RxStatus`, `TxFlags`, provider timestamp, `DataSize`, `ExtraDataIndex`, and payload bytes. If a provider reports more returned messages than the caller allocated, Atlas marks the trace as truncated rather than reading beyond the caller's buffer. The caller's message array and count pointer are passed directly to the real provider and are never rewritten by Atlas.

`PassThruWriteMsgs` snapshots the caller's requested messages for evidence and then passes the **same original message array and count pointer** directly to the provider. Ordinary diagnostic payloads are retained in the trace. When the ISO15765 message can be explicitly decoded as service `0x27` SecurityAccess or `0x36` TransferData, Atlas redacts the payload by default and stores the message length, service label, and SHA-256 digest instead. Redaction changes only the trace representation; it never changes the bytes forwarded to the provider.

Sensitive-service classification is deliberately narrow: Atlas recognizes the J2534 ISO15765 form after the four-byte arbitration ID, including direct service bytes and ISO-TP single-frame/first-frame PCI. It does not search arbitrary data for `0x27` or `0x36`.

Trace record numbering/writes are serialized so concurrent J2534 calls retain contiguous JSONL sequence order; provider calls themselves are not serialized by Atlas. Trace write failures after initialization are observational failures only and do not alter the provider return value.

## Off-vehicle transparency tests

The CMake tests build a fake J2534 provider and compare direct-provider behavior with proxied behavior.

The lifecycle test requires exact equality of:

- `PassThruOpen` return value and device ID;
- `PassThruReadVersion` return value and all three version strings;
- `PassThruGetLastError` return value and text;
- `PassThruClose` return value.

The connection test additionally requires exact equality of:

- `PassThruConnect` return value;
- assigned channel ID;
- ISO15765 protocol selection;
- flags and 500 kbit/s baud rate;
- `PassThruDisconnect` return value;
- a deliberately rejected 250 kbit/s connection attempt; and
- the caller's channel-output buffer remaining unchanged when that connection fails.

The filter test additionally requires exact equality of:

- `PassThruStartMsgFilter` return value;
- provider-assigned filter ID;
- flow-control filter type;
- mask `FFFFFFFF`;
- response pattern `000007E8`;
- flow-control arbitration ID `000007E0`;
- all three input `PASSTHRU_MSG` structures remaining byte-for-byte unchanged;
- a deliberately rejected filter type preserving the provider error and caller filter-ID buffer; and
- `PassThruStopMsgFilter` return value.

The read test additionally requires exact equality of:

- `PassThruReadMsgs` return code;
- returned message count;
- message ordering;
- every returned `PASSTHRU_MSG` metadata field;
- exact payload bytes;
- a successful two-message read from a caller capacity of four;
- an `ERR_TIMEOUT` read returning zero messages; and
- the timeout read leaving a sentinel-filled caller message buffer unchanged.

The write test additionally requires exact equality of:

- `PassThruWriteMsgs` return code and returned message count;
- the original caller message buffers before/after forwarding;
- two ordinary ISO15765 DID-request messages accepted byte-for-byte by the fake provider;
- SecurityAccess and TransferData messages accepted byte-for-byte by the fake provider while their trace payloads remain redacted;
- SHA-256 redaction evidence for both sensitive services; and
- an `ERR_TIMEOUT` write returning zero messages.

Additional tests verify fail-closed invalid provider identity and multithreaded trace sequence ordering.

Windows CI builds and runs these native tests before the Flutter Windows build.

## Acceptance boundary

Passing the device/channel/filter/read/write tests does **not** authorize vehicle or programming use. Before Atlas can sit between a GM application and a real J2534 device, later stages must independently add and test:

- IOCTL forwarding;
- programming-voltage forwarding;
- remaining J2534 APIs required by the selected GM tool/provider;
- ordering and timeout equivalence under sustained load;
- bounded trace overhead;
- provider-specific behavior against real vendor DLLs; and
- fail-safe behavior on a bench interface before any in-vehicle session.

Until those gates pass, use Windows Atlas's independent passive CAN/SWCAN adapters for vehicle observation.
