# OBD Atlas J2534 lifecycle proxy

This directory contains the **off-vehicle lifecycle-only** foundation for the planned Windows J2534 observer/forwarder.

## Current exported API

Only these functions are implemented and forwarded:

- `PassThruOpen`
- `PassThruClose`
- `PassThruReadVersion`
- `PassThruGetLastError`

The proxy does **not** currently export or forward `PassThruConnect`, `PassThruReadMsgs`, `PassThruWriteMsgs`, filters, IOCTLs, programming-voltage control, or any other vehicle-communication API.

Therefore this DLL is **not suitable for GDS2/SPS2/DPS vehicle use yet**. It exists only to prove DLL loading, exact lifecycle forwarding, and trace generation against an off-vehicle/fake provider.

## Configuration

The lifecycle proxy is configured with environment variables before it is loaded:

- `OBD_ATLAS_J2534_REAL_DLL` — exact real/fake provider DLL path; required.
- `OBD_ATLAS_J2534_TRACE_PATH` — new JSONL trace path; required. The proxy uses create-new semantics and refuses to append to an existing trace.
- `OBD_ATLAS_J2534_SOURCE_APP` — source application identity, for example `gds2`; optional for the lifecycle harness.
- `OBD_ATLAS_J2534_SOURCE_APP_VERSION` — source application version; optional.
- `OBD_ATLAS_J2534_PROVIDER_NAME` — provider name selected by Atlas inventory.
- `OBD_ATLAS_J2534_PROVIDER_VENDOR` — provider vendor.
- `OBD_ATLAS_J2534_PROVIDER_REGISTRY_PATH` — exact PassThru registry path.
- `OBD_ATLAS_J2534_PROVIDER_REGISTRY_SUBKEY` — exact provider subkey.
- `OBD_ATLAS_J2534_PROVIDER_FINGERPRINT` — SHA-256 provider fingerprint from `tool/windows_j2534_inventory.py`.

The proxy rejects a configuration where `OBD_ATLAS_J2534_REAL_DLL` resolves to the proxy DLL itself.

## Trace behavior

The DLL emits `obd-atlas.j2534-trace.v1` JSONL records compatible with `tool/j2534_trace.py`:

1. one session record;
2. `callBegin` immediately before each forwarded lifecycle API call;
3. matching `callEnd` immediately after the provider returns.

Each record has UTC and monotonic timing. Return codes and provider output strings are recorded after forwarding. Trace write failures after initialization are observational failures only and do not alter the provider return value.

## Off-vehicle transparency test

The CMake test builds a fake J2534 provider and then executes the same lifecycle twice:

1. directly against the fake provider;
2. through `obd_atlas_j2534_proxy.dll`.

It requires exact equality of:

- `PassThruOpen` return value and device ID;
- `PassThruReadVersion` return value and all three version strings;
- `PassThruGetLastError` return value and text;
- `PassThruClose` return value.

It also verifies that the trace contains one session plus four matched begin/end pairs and the configured provider fingerprint.

Windows CI builds and runs this test before the Flutter Windows build.

## Acceptance boundary

Passing this lifecycle test does **not** authorize vehicle use. Before Atlas can sit between a GM application and a real J2534 device, later stages must independently add and test:

- `PassThruConnect` / `PassThruDisconnect`;
- message read/write forwarding;
- filter forwarding;
- IOCTL forwarding;
- programming-voltage forwarding;
- byte-for-byte buffer equivalence;
- ordering and timeout equivalence;
- bounded trace overhead;
- fail-safe behavior with real vendor DLLs on a bench interface.

Until those gates pass, use Windows Atlas's independent passive CAN/SWCAN adapters for vehicle observation.
