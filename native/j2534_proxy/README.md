# OBD Atlas J2534 read-observer proxy

This directory contains the **off-vehicle connection, filter, and read-only message** foundation for the planned Windows J2534 observer/forwarder.

## Current exported API

Only these functions are implemented and forwarded:

- `PassThruOpen`
- `PassThruClose`
- `PassThruConnect`
- `PassThruDisconnect`
- `PassThruStartMsgFilter`
- `PassThruStopMsgFilter`
- `PassThruReadMsgs`
- `PassThruReadVersion`
- `PassThruGetLastError`

The proxy does **not** currently export or forward `PassThruWriteMsgs`, IOCTLs, programming-voltage control, or any other transmit/vehicle-control API.

Therefore this DLL is **not suitable for GDS2/SPS2/DPS vehicle use yet**. It exists only to prove DLL loading, exact device/channel/filter/read forwarding, and trace generation against an off-vehicle/fake provider.

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

Additional tests verify fail-closed invalid provider identity and multithreaded trace sequence ordering.

Windows CI builds and runs these native tests before the Flutter Windows build.

## Acceptance boundary

Passing the device/channel/filter/read tests does **not** authorize vehicle use. Before Atlas can sit between a GM application and a real J2534 device, later stages must independently add and test:

- `PassThruWriteMsgs` forwarding;
- IOCTL forwarding;
- programming-voltage forwarding;
- byte-for-byte transmit-buffer equivalence;
- ordering and timeout equivalence under sustained load;
- bounded trace overhead; and
- fail-safe behavior with real vendor DLLs on a bench interface.

Until those gates pass, use Windows Atlas's independent passive CAN/SWCAN adapters for vehicle observation.
