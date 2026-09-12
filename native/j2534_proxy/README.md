# OBD Atlas J2534 connection-lifecycle proxy

This directory contains the **off-vehicle connection-lifecycle** foundation for the planned Windows J2534 observer/forwarder.

## Current exported API

Only these functions are implemented and forwarded:

- `PassThruOpen`
- `PassThruClose`
- `PassThruConnect`
- `PassThruDisconnect`
- `PassThruReadVersion`
- `PassThruGetLastError`

The proxy does **not** currently export or forward `PassThruReadMsgs`, `PassThruWriteMsgs`, message filters, IOCTLs, programming-voltage control, or any other message/vehicle-control API.

Therefore this DLL is **not suitable for GDS2/SPS2/DPS vehicle use yet**. It exists only to prove DLL loading, exact device/channel lifecycle forwarding, and trace generation against an off-vehicle/fake provider.

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

Each record has UTC and monotonic timing. Connect records the exact `ProtocolID`, `Flags`, and `BaudRate`; its returned `ChannelID` is recorded without modification. Disconnect records the supplied channel ID. Trace write failures after initialization are observational failures only and do not alter the provider return value.

Trace record numbering/writes are serialized so concurrent J2534 calls retain contiguous JSONL sequence order; provider calls themselves are not serialized by Atlas.

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

Additional tests verify fail-closed invalid provider identity and multithreaded trace sequence ordering.

Windows CI builds and runs these native tests before the Flutter Windows build.

## Acceptance boundary

Passing the device/channel lifecycle tests does **not** authorize vehicle use. Before Atlas can sit between a GM application and a real J2534 device, later stages must independently add and test:

- message-filter forwarding;
- `PassThruReadMsgs` forwarding;
- `PassThruWriteMsgs` forwarding;
- IOCTL forwarding;
- programming-voltage forwarding;
- byte-for-byte message/buffer equivalence;
- ordering and timeout equivalence;
- bounded trace overhead; and
- fail-safe behavior with real vendor DLLs on a bench interface.

Until those gates pass, use Windows Atlas's independent passive CAN/SWCAN adapters for vehicle observation.
