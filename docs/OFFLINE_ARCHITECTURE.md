# OBD Atlas offline-first architecture

## Non-negotiable requirement

OBD Atlas must remain fully useful at the vehicle with no Internet connection. Network access may enhance synchronization or updates later, but it may never be required to launch, select a vehicle, connect to an adapter, capture traffic, inspect live data, import/export logs, or search locally stored research data.

## Target platforms

- Windows 11 desktop/laptop
- Android phone/tablet

The initial frontend is Flutter so one UI and application-state layer can target both platforms while hardware transports remain isolated behind adapter interfaces.

## Application layers

1. **UI** — Vehicle, Connect, Capture, Live Data, Library, Settings.
2. **Session services** — vehicle identity, capture session metadata, timestamps, annotations.
3. **Transport adapters** — ELM/OBDLink, USB CAN/CANable, J2534/VCX on Windows, future PCG-1 transports.
4. **Decoder/analyzer** — CAN ID statistics, signal extraction, UDS/OBD decoding, Atlas knowledge lookups.
5. **Local store** — raw captures, session manifests, local vehicle profiles, decoder definitions, Atlas datasets.
6. **Optional sync** — future import/export or remote synchronization. This layer must never be on the critical path for local operation.

## Evidence rule

Raw captures are authoritative source evidence and are preserved before interpretation. Decoder output should reference its source capture and version of the decoder definition.

## First implementation milestones

- [x] Cross-platform application shell
- [x] Local application data directory
- [x] Local capture import/library
- [ ] Vehicle profile persistence
- [ ] Capture session manifest schema
- [ ] Adapter interface contract
- [ ] USB CAN/CANable transport
- [ ] ELM/OBDLink transport
- [ ] Live frame counter and CAN-ID inventory
- [ ] Atlas local searchable database
- [ ] J2534/VCX Windows transport
- [ ] Android USB/Bluetooth permissions and transport bindings
