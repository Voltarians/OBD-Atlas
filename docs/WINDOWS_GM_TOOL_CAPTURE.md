# Windows GM Tool Capture Architecture

## Goal

Run OBD Atlas on the same Windows computer as GDS2, SPS/SPS2 or DPS and capture the session directly rather than requiring a separate Raspberry Pi recorder.

The architecture deliberately separates two evidence layers:

1. **Raw vehicle-network evidence** captured by Atlas through independent passive CAN/SWCAN adapters.
2. **J2534 application evidence** captured at the Windows PassThru API boundary between the GM application and the VCX/J2534 device.

The two layers are timestamp-correlated after capture. Either layer may be useful independently; together they provide the strongest diagnostic mapping evidence.

## Phase A: Windows Atlas raw-bus capture

The existing Windows Atlas frontend already supports the capture hardware needed for a five-channel recorder:

- CH1: candleLight / gs_usb / CANable
- CH2 + CH3: CANalyst-II dual channel
- CH4 + CH5: LYS USBCAN-II dual channel

The CANalyst-II and LYS paths use direct WinUSB transports. They do not require Atlas to borrow the VCX device that GDS2 is using.

For Gen-1 Volt research the preferred mapping is:

- Primary HS GMLAN, 500 kbit/s
- Chassis HS GMLAN, 500 kbit/s
- Powertrain Expansion HS GMLAN, 500 kbit/s
- High Voltage Energy Management HS GMLAN, 500 kbit/s
- SWCAN, 33.333 kbit/s

This lets one Windows laptop run GDS2 while Atlas independently records every populated CAN-family vehicle network available through the X84/X84B breakout harness.

### Why Atlas should not initially share the VCX device

A J2534 interface and its vendor driver may not support two independent applications opening and controlling the same physical device at the same time. Even when multiple channels are technically supported, competing applications can alter filters, protocol settings, bus selection, programming voltage or connection state.

For research capture, GDS2/SPS2/DPS should own the VCX interface. Atlas should observe the raw buses through separate listen-only adapters. This minimizes the chance that the recorder changes the diagnostic session.

## Phase B: Windows Atlas J2534 tap

Raw CAN alone tells Atlas what appeared on the vehicle network but does not always reveal the application's intent. A Windows J2534 tap adds the missing application-side evidence.

The preferred implementation is a transparent PassThru proxy/shim that exposes the normal J2534 ABI to the GM application and forwards every call to the selected real vendor J2534 DLL while recording metadata.

Initial calls to observe:

- `PassThruOpen`
- `PassThruClose`
- `PassThruConnect`
- `PassThruDisconnect`
- `PassThruReadMsgs`
- `PassThruWriteMsgs`
- `PassThruStartMsgFilter`
- `PassThruStopMsgFilter`
- `PassThruSetProgrammingVoltage`
- `PassThruReadVersion`
- `PassThruGetLastError`
- `PassThruIoctl`

The proxy must preserve return codes, timing and message contents exactly. Capture code must never synthesize extra diagnostic messages.

### Safety boundary

The J2534 tap is an observer/forwarder. Atlas must not change GDS2/SPS2/DPS requests, security values, transfer blocks, filter definitions or programming-voltage commands.

Before the proxy is used during an SPS/DPS programming event, it must pass an off-vehicle replay/loopback acceptance test proving that forwarded calls, return codes and message buffers are byte-for-byte equivalent to direct vendor-DLL operation. Until then, raw-bus capture remains the production-safe method.

## Phase C: correlated GM-tool evidence bundle

A completed GM-tool capture should contain:

- Atlas raw candump capture
- session manifest
- adapter/channel/network map
- operator event markers
- source application (`gds2`, `sps2`, `dps`)
- application version when known
- VCX/J2534 product and DLL/version identity
- J2534 call log when the proxy is enabled
- extracted ISO-TP/UDS/GM diagnostic session JSON
- GDS2 DID/dynamic-packet extraction when applicable
- SHA-256 hashes of every raw evidence file

The offline pipeline can then answer three separate questions:

1. What action did the operator perform in GDS2/SPS2/DPS?
2. What did the Windows diagnostic application request through J2534?
3. What traffic actually appeared on each vehicle network?

## GDS2 mapping workflow on one Windows computer

1. Connect VCX to GDS2 normally.
2. Connect Atlas passive adapters to the X84/X84B breakout harness.
3. Open Windows Atlas and verify all expected channels are receiving.
4. Start Atlas capture before opening the target GDS2 Data Display group.
5. Record a marker for the exact module/page/group or parameter being displayed.
6. Leave the selected parameter/group active for several seconds.
7. Change only one small group at a time when practical.
8. Stop Atlas capture only after leaving the Data Display page.
9. Run `extract_gds2_dids.py` and `extract_gm_tool_session.py` offline.
10. Promote a DID/signal mapping only when repeated traffic and displayed values agree.

## First Gen-1 Volt targets

Priority HPCM2 mappings:

- Positive contactor command
- Negative contactor command
- Precharge transistor command
- Multifunction contactor command
- Precharge current too high
- Precharge time short
- Precharge time too long
- Contactor open reasons
- HV interlock
- Isolation resistance

Priority BECM mappings:

- all 96 cell voltages
- high-resolution pack current
- low-resolution pack current
- pack terminal voltage
- minimum/maximum/average cell voltage
- minimum/maximum sensor index
- pack SOC and SOC limits
- pack resistance
- pack/battery temperatures

## Development order

1. Treat the current Windows five-channel Atlas frontend as the raw-bus recorder rather than creating another application.
2. Restore/add timestamped free-text capture markers to the cross-platform capture session.
3. Add Windows J2534 installation discovery and vendor-DLL inventory.
4. Define the J2534 trace file schema and tests.
5. Build the forwarding proxy and prove transparent behavior off-vehicle.
6. Add a `GM Tool Capture` mode that correlates raw buses, markers and J2534 trace events on a common monotonic timeline.
