# ELM/STN Capability Envelopes

Status: **Active engineering policy**
Date: 2026-09-26

OBD Atlas and Voltarian should extract the maximum useful information each ELM327/STN-family adapter can reliably deliver. Capability is transport-specific: a limit observed on Windows serial or Android Bluetooth must not be applied automatically to Linux RFCOMM, and vice versa.

## Product principle

Use the adapter for **all supported passive and diagnostic functions inside its measured transport envelope**.

Do not disable useful features merely because another transport or adapter performs differently. Full-bus monitoring is allowed when it has been verified on that adapter/transport combination.

## Current Voltarian/Atlas support envelopes

| Adapter / transport | Verified passive capability | Exact 11-bit IDs | Product role |
| --- | ---: | ---: | --- |
| vLinker MS / STN2120 | 1,500 frames/s filtered production profile; higher unrestricted rates observed in engineering tests | 32 | High-rate passive capture + active diagnostics |
| OBDLink MX+ / STN2256 • Linux RFCOMM | **~2,900 frames/s sustained HS-CAN full-pass verified** | 16 in filtered fallback | **FULL BUS default on Linux HS-CAN** + filtered fallback + SWCAN |
| OBDLink MX+ / STN2256 • other transports | Transport-specific; do not inherit Linux capability without testing | 16 | Customer live data, filtered/event capture, diagnostics, SWCAN |
| OBDLink EX / STN2232 | 100 frames/s filtered production profile on current Android/USB path | 16 | USB diagnostic/live-data path; filtered HS-CAN |
| Generic/unknown ELM327 | 50 frames/s conservative profile | 8 | Basic diagnostics and selected live data |

These are project software capability envelopes derived from observed behavior, not manufacturer maximum specifications.

## Verified Linux MX+ full-pass result

On 2026-09-26, OBDLink MX+ / STN2256 on PCG-1 Linux RFCOMM was verified in unrestricted HS-CAN monitoring using:

- `STP 31`
- `STCMM 0`
- `STFAC`
- `STFPA 000,000`
- `STM`

Observed capture:

- 1,988,662 CAN frames;
- 682.8 seconds (>11 minutes);
- 2,912.5 frames/s average;
- 105 unique 11-bit CAN IDs;
- zero malformed CAN lines;
- zero observed `BUFFER FULL`, UART overflow, disconnect, or transport collapse;
- no inter-frame gap greater than 50 ms.

Historical native PCG-1 HS-CAN captures from 2026-09-09 were also compared against the MX+ full-pass run. Across 12 native `can3` captures, the weighted HS-CAN rate was approximately 2,840.7 frames/s with 106 unique IDs. Of 103 IDs common to both datasets, 100 matched periodic frame rates within 1%, including the major 100 Hz and 80 Hz traffic families.

This verifies that Linux MX+ full-pass is viable at the observed Gen-1 Volt HS-CAN load. It does **not** claim a hardware maximum, and it does not replace a simultaneous native-reference test for formal frame-for-frame loss measurement.

## Linux MX+ runtime policy

### 1. HS-CAN default: full pass

On Linux RFCOMM, Atlas should default OBDLink MX+ HS-CAN to unrestricted full-pass monitoring.

The expected setup is `STFPA 000,000` with no filter-bank rotation.

Every capture must stamp the active MX+ transport, bus, mode, bank state, and filter IDs at capture start so the evidence is self-describing.

### 2. Filtered rotating fallback

Exact-filter mode remains supported for:

- troubleshooting transport-specific problems;
- intentionally reducing traffic;
- comparison testing;
- deployments where unrestricted monitoring is not stable.

Filtered mode may use persistent priority IDs plus rotating discovery banks, with no more than 16 exact 11-bit filters active at one time.

### 3. Active diagnostic collection

Passive CAN bandwidth limits do not prohibit request/response diagnostics.

Use supported OBD/UDS/GMLAN requests for:

- module identification;
- DTC inventory and details;
- live parameter/DID reads;
- battery/BECM/BICM data;
- VIN/calibration/software metadata;
- service information available only on request.

Rate-limit requests so replies do not interfere with passive capture.

### 4. Event-focused capture

For brake, accelerator, shifter, steering, door, charge, thermal, and other discovery work:

1. use full-pass monitoring when the verified transport can sustain it;
2. mark the event;
3. compare changed bytes/bits across the complete observed ID population;
4. use filtered banks only when the transport requires them or when a deliberately narrow capture is useful.

### 5. SWCAN

MX+ SWCAN remains independently valuable.

Atlas should continue GM SWCAN monitoring on protocol 61. If SWCAN bus load or a transport-specific path produces overflow, apply selected-ID filtering rather than dropping SWCAN capability.

### 6. Native CAN interfaces

CANable/gs_usb, SocketCAN, UC2/CANalyst/J2534 and similar native interfaces remain the preferred path for:

- simultaneous multi-bus capture;
- formal forensic loss measurement;
- adapter-vs-native reference comparison;
- high-rate protocol research requiring hardware timestamps or native bus access.

The verified Linux MX+ full-pass result makes the MX+ a practical unrestricted single-bus HS-CAN capture option on PCG-1; it does not make native interfaces unnecessary.

## Runtime health

A passive ELM/STN capture is healthy when:

- the adapter reports no `BUFFER FULL` / UART overflow;
- transport and file writes remain error-free;
- the frame stream remains stable without unexplained monitor stalls;
- observed traffic remains inside the adapter/transport combination's verified envelope.

If unrestricted monitoring proves unstable on a specific transport, Atlas should fall back to exact filtering or rotating banks rather than disabling the adapter.

## Data provenance

Each capture/session should record:

- adapter identity and firmware when available;
- transport type;
- vehicle bus;
- monitor mode (`full-pass` or `exact-filter`);
- exact filter IDs/masks;
- active filter-bank number;
- observed frames/s and bytes/s;
- overflow/error count;
- active diagnostic requests made during the session.

## Decision

**ELM/STN adapters remain first-class Voltarian and OBD Atlas interfaces for every function they can reliably support. OBDLink MX+ on Linux RFCOMM is now verified for sustained Gen-1 HS-CAN full-pass monitoring at approximately 2.9k frames/s and should default to FULL BUS on that platform.**
