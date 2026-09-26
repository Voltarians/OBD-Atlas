# ELM/STN Capability Envelopes

Status: **Active engineering policy**
Date: 2026-09-26

OBD Atlas and Voltarian should extract the maximum useful information an ELM327/STN-family adapter can deliver without pretending that the adapter is a native unrestricted CAN recorder.

## Product principle

Use the adapter for **all supported diagnostic and filtered-observation functions** inside its measured transport envelope.

Do not disable useful features merely because unrestricted bus mirroring is unavailable.

## Current Voltarian/Atlas support envelopes

| Adapter | Filtered production ceiling | Exact 11-bit IDs | Product role |
| --- | ---: | ---: | --- |
| vLinker MS / STN2120 | 1,500 frames/s | 32 | High-rate filtered passive capture + active diagnostics |
| OBDLink MX+ / STN2256 | 150 frames/s | 16 | Customer live data, filtered event capture, active diagnostics, SWCAN |
| OBDLink EX / STN2232 | 100 frames/s | 16 | USB diagnostic/live-data path; filtered HS-CAN |
| Generic/unknown ELM327 | 50 frames/s | 8 | Conservative basic diagnostics and selected live data |

These are project software limits, not manufacturer specifications.

## Capability strategy

### 1. Continuous priority set

Keep the highest-value CAN IDs continuously enabled for:
- battery and propulsion state;
- vehicle speed / driver controls;
- charging and contactor state;
- thermal state;
- fault and warning state;
- event markers used by signal discovery.

The continuous set must stay below the adapter's frame-rate ceiling.

### 2. Rotating discovery banks

Secondary IDs should be divided into banks sized for the adapter.

Atlas may stop the monitor, reprogram hardware pass filters, and resume on the next bank. Across time this allows broad network discovery without requiring all IDs to cross the serial/Bluetooth transport simultaneously.

Every capture must record which bank/filter set was active.

### 3. Active diagnostic collection

Passive CAN bandwidth limits do not prohibit request/response diagnostics.

Use supported OBD/UDS/GMLAN requests for:
- module identification;
- DTC inventory and details;
- live parameter/DID reads;
- battery/BECM/BICM data;
- VIN/calibration/software metadata;
- service information that is only available on request.

Rate-limit requests so replies do not collide with the passive filtered stream.

### 4. Event-focused capture

For brake, accelerator, shifter, steering, door, charge, thermal, and other discovery work:
1. capture a stable filtered baseline;
2. mark the event;
3. compare changed bytes/bits within the enabled ID bank;
4. rotate to the next bank and repeat when broader coverage is required.

This preserves Atlas signal-discovery capability on bandwidth-limited adapters.

### 5. SWCAN

MX+ SWCAN remains valuable independently of HS-CAN performance.

Atlas should continue to support GM SWCAN observation and discovery on protocol 61. If bus load or transport produces overflow, apply the same selected-ID policy rather than dropping SWCAN capability.

### 6. Native CAN interfaces

CANable/gs_usb, SocketCAN, UC2/CANalyst/J2534 and similar native interfaces remain the preferred path for:
- unrestricted full-bus recording;
- simultaneous multi-bus capture;
- forensic loss measurements;
- high-rate protocol research.

Their existence does not reduce the supported functionality of ELM/STN adapters.

## Runtime behavior

A filtered ELM/STN capture is healthy when:
- the adapter reports no `BUFFER FULL` / UART overflow;
- transport and file writes remain error-free;
- observed filtered traffic remains at or below the configured product ceiling.

When a ceiling is exceeded, Atlas should reduce or rotate the filter set instead of failing the entire adapter.

## Data provenance

Each capture/session manifest should eventually record:
- adapter identity and firmware;
- transport type;
- vehicle bus;
- exact filter IDs/masks;
- active filter-bank number;
- observed frames/s and bytes/s;
- overflow/error count;
- active diagnostic requests made during the session.

This makes filtered evidence reproducible and usable by OBD Atlas.

## Decision

**ELM/STN adapters remain first-class Voltarian and OBD Atlas interfaces for every function they can reliably support. Only unrestricted raw-bus mirroring is excluded from their production requirement.**
