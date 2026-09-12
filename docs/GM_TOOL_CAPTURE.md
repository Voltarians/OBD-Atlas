# GM tool capture workflow

## Purpose

OBD Atlas treats GDS2, SPS/SPS2 and DPS traffic as auditable evidence. The goal is to observe what an authorized GM tool session actually does, preserve the raw transport, and promote definitions only when the evidence supports them.

The capture and extraction path is passive. Atlas does not need to transmit vehicle traffic to learn from a GM tool session.

## Tool roles

- **GDS2** — diagnostic module discovery, DTC operations and Data Display mapping.
- **SPS/SPS2** — production programming-session observation: session changes, security exchange, download/transfer phases, resets and post-programming operations.
- **DPS** — engineering/programming observation, ECU Configuration XML workflows, Service Programming Archives, Utility Files and specialized Type 4/VCAP procedures.

The DPS User Guide documents DPS as a J2534-based GM development programming system and states that its communication subsystem is the same as SPS from a communications perspective. Atlas therefore keeps the application source (`gds2`, `sps2`, `dps`) in provenance even when the underlying diagnostic transport is shared.

Type 4 / VCAP observations are retained as a separate provenance source because they may execute application-specific procedures rather than ordinary Data Display or programming flows.

## Passive extraction

Run the generic session extractor against an Atlas/candump capture:

```bash
python3 tool/extract_gm_tool_session.py capture.log --json-out gm-session.json
```

The generic extractor recognizes both classic ISO-TP diagnostic traffic and legacy unframed GM request/response families when they match a provenance-preserving address reference. By default it loads:

- `assets/diagnostics/gm_legacy_simulation_address_reference.json` as `legacyReference` evidence; and
- `assets/diagnostics/chevrolet_volt_gen1_hpcm2_did_candidates.json` for the Gen-1 HPCM2 `0x7E4 / 0x7EC / 0x5EC` family as `communityCandidate` evidence.

Additional reference catalogs can be supplied by repeating `--address-reference`. Use `--no-address-reference` to run service extraction without ECU/address-family matching.

The JSON output now separates three related layers:

- `events` — decoded request/response service events, including transport type and likely module when the address evidence is unique;
- `endpointTraffic` — raw counts for matched request, response and data-stream CAN IDs, including unframed `0x5xx` streams that Atlas does not falsely decode as UDS; and
- `transactions` — uniquely addressed request/response pairs with initial and final response latency. A `0x7F .. 0x78` response-pending event is retained as the initial response while pairing continues to the terminal response.

Address-family labels retain the confidence of their source catalog. A `legacyReference` match is not upgraded to a vehicle-confirmed ECU mapping merely because traffic appeared on that CAN ID.

The parser recognizes common GM/UDS services including:

- `0x04` legacy clear diagnostic information
- `0x09` vehicle information
- `0x10` diagnostic session control
- `0x11` ECU reset
- `0x12` GM failure record
- `0x18` legacy DTC information
- `0x22` read data by identifier / parameter identifier
- `0x27` security access
- `0x28` communication control
- `0x2C` dynamic data definition
- `0x2E` write data by identifier
- `0x31` routine control
- `0x34` request download
- `0x35` request upload
- `0x36` transfer data
- `0x37` request transfer exit
- `0x3E` tester present
- `0x85` control DTC setting
- `0xA9` GM DTC information
- `0xAA` GM dynamic packet control
- `0x7F` negative responses, including common NRC names

`TransferData` block bytes are redacted from the normal JSON output unless `--include-transfer-data` is explicitly requested. Counts, block sequence numbers and programming-phase evidence remain available without retaining firmware payload contents.

For HPCM2 Data Display work, `tool/extract_gds2_dids.py` remains the more specialized mapper for the known Gen-1 Volt `0x7E4 -> 0x7EC` physical path and GM dynamic `0x2C` / `0xAA` data on `0x5EC`. The generic session extractor now recognizes that same address family so its transaction timing and module attribution can be compared directly with the specialized DID output.

## Capture metadata

Each GM-tool evidence record should preserve, when available:

- source application and version: GDS2, SPS/SPS2 or DPS
- J2534/VCX interface and driver/API version
- vehicle model year and non-public vehicle identity
- module name and diagnostic address
- module software/calibration identifiers
- Atlas channel / physical network
- raw capture SHA-256
- session manifest SHA-256
- exact operator action or screen name
- capture marker timestamps
- request/response CAN IDs
- service, DID/PID/routine identifiers
- raw response bytes when appropriate
- decoded value, formula or enum only after validation

## Evidence levels

Atlas keeps these categories separate:

1. **confirmed** — reproduced with direct Atlas-controlled evidence.
2. **communityCorroborated** — at least three qualifying independent source families agree.
3. **candidate** — plausible or correlated but not yet proven.
4. **gmServiceDocumented** — GM documents the parameter name, role or expected range but Atlas has not yet mapped its transport identifier.
5. **legacyReference** — an older GM diagnostic transcript/reference provides useful addressing or protocol evidence, but Atlas has not established that the mapping belongs to this specific vehicle/module configuration.

A service-manual parameter name must not be turned into a DID by assumption. A captured DID must not be assigned a parameter name solely because they appeared in the same broad screen.

## Initial GDS2 mapping procedure

Initial Data Display mapping is observation-only. Do not invoke output controls, security access, resets or programming merely to discover traffic.

1. Start the independent Atlas capture before entering the GDS2 module Data Display page.
2. Select one small parameter group at a time; a single parameter is preferable when GDS2 permits it.
3. Add an exact capture marker containing the GDS2 module/page/group name.
4. Leave the group displayed for several seconds so setup traffic can be separated from repeated sampling.
5. Preserve the raw log and manifest before analysis.
6. Run the specialized GDS2 extractor and the generic GM-tool extractor offline.
7. Promote a mapping only when the request/response repeats and the decoded value/state follows the displayed GDS2 value across multiple samples.

## Gen-1 startup / contactor priority queue

The first HPCM2 Data Display mapping targets remain:

1. Hybrid/EV Battery Pack Positive Contactor Command
2. Hybrid/EV Battery Pack Negative Contactor Command
3. Hybrid/EV Battery Pack Precharge Transistor Command
4. Hybrid/EV Battery Pack Multifunction Contactor Command
5. Hybrid/EV Battery System Precharge Current Too High
6. Hybrid/EV Battery System Precharge Time Short
7. Hybrid/EV Battery System Precharge Time Too Long
8. Hybrid Battery Pack Contactor Open Reasons
9. High Voltage Interlock Circuit
10. Isolation Test Resistance

After HPCM2, K16 BECM mapping should prioritize all 96 battery voltages, pack voltage/current, minimum/maximum/average cell voltage, SOC limits, battery resistance and temperature data.

## SPS/SPS2 and DPS observation boundary

Programming captures should observe a programming event the operator already intends and is authorized to perform. Atlas records and decodes the transport; it does not synthesize security keys, invent programming archives, or replay a captured programming sequence automatically.

For SPS/SPS2/DPS research, the first offline deliverables are:

- ECU/session inventory
- request/response address map
- service timeline
- negative-response timeline
- security seed/key exchange metadata without claiming the algorithm
- routine identifiers
- RequestDownload / TransferData / RequestTransferExit phase boundaries
- transfer block counts and sequence continuity
- reset and post-programming operations
- correlation against the archive/utility/configuration metadata available to the operator

This gives Atlas a reusable, provenance-aware GM diagnostic/programming knowledge base without weakening the evidence standard used for vehicle CAN definitions.
