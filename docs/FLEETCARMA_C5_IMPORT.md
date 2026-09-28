# FleetCarma C5 Chevrolet Volt import

OBD Atlas can now decode FleetCarma C5 binary CAN logger files recovered from
an early Chevrolet Volt deployment.

## Recovered record format

The C5 `.BIN` files use one-byte type, one-byte payload length, then payload.

| Type | Length | Meaning |
|---|---:|---|
| `0x01` | 5 | configured CAN ID / logger filter |
| `0x05` | 16 | CAN frame |
| `0x24` | variable | GPS/NMEA record |

For `0x05` the payload layout is:

- byte 0: bus number
- bytes 1-2: 11-bit CAN ID, little-endian
- byte 3: DLC
- bytes 4-7: logger timestamp in milliseconds, little-endian
- bytes 8-15: CAN payload, padded to eight bytes

The Dart importer is in `lib/core/fleetcarma_c5_importer.dart`.
The bulk conversion tool is `tool/import_fleetcarma_c5.py`.

## Bulk import

```bash
python tool/import_fleetcarma_c5.py CANLOG.zip --output fleetcarma_import
```

Input may be a single `.BIN`, a directory tree, or a ZIP archive.

Outputs:

- `fleetcarma_can.csv`
- `fleetcarma_candump.log`
- `fleetcarma_gps.csv`
- `fleetcarma_sessions.csv`
- `fleetcarma_summary.json`

The importer preserves valid records before malformed or truncated file tails
and flags those sessions rather than silently discarding them.

## Historical Volt corpus recovered 2026-09-27

The analyzed FleetCarma card contains 22,663 binary files. The recovered CAN
inventory is narrowly filtered and contains these observed bus/ID pairs:

| Bus | CAN ID | Frames |
|---:|---:|---:|
| 1 | 0x120 | 8,395 |
| 1 | 0x1ED | 2,334,540 |
| 1 | 0x1EF | 2,334,216 |
| 1 | 0x206 | 237,089 |
| 1 | 0x3E9 | 2,323,530 |
| 1 | 0x3F1 | 462,286 |
| 1 | 0x4E1 | 4,951 |
| 1 | 0x514 | 4,967 |
| 2 | 0x210 | 5,293,807 |
| 2 | 0x30A | 1,063,153 |

These counts describe this specific historical logger configuration. They do
not imply that other Volt CAN IDs were absent from the vehicle; the FleetCarma
logger was configured to capture a selected subset.

## Timestamp handling

The on-file CAN timestamp is a logger-relative millisecond counter. Atlas does
not silently reinterpret it as Unix epoch time. Call
`FleetCarmaCanRecord.toCanFrame()` only after providing an explicit wall-clock
anchor and the corresponding logger timestamp.

GPS GGA time and surviving C5 text logs can be used to construct such anchors
for historical datasets.
