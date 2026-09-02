# DBC import and export

OBD Atlas stores DBC definitions as normalized SQLite records while retaining
the source filename and SHA-256 hash. DBC data is reference evidence; importing
a definition does not prove that its signals apply to an observed vehicle.

## Import

```bash
python3 atlas.py dbc-import vehicle.dbc \
  --database obd_atlas.sqlite3 --name volt-gen1-research
```

An existing source name is protected from accidental replacement. Use
`--replace` only when intentionally superseding that source.

## List sources

```bash
python3 atlas.py dbc-list --database obd_atlas.sqlite3
```

## Export

```bash
python3 atlas.py dbc-export volt-gen1-research exported.dbc \
  --database obd_atlas.sqlite3
```

Atlas constructs the DBC from normalized records, reparses it, compares the
semantic model, writes it, then reparses the bytes from disk. A failed semantic
comparison removes the output rather than distributing an invalid database.

## Supported core constructs

- Standard 11-bit and extended 29-bit CAN identifiers
- CAN/CAN FD payload lengths from 0 through 64 bytes
- Nodes, messages, transmitters and receivers
- Signal start bit, length, byte order and signedness
- Scaling, offset, range, unit and multiplex indicators
- Message and signal comments
- Signal value descriptions
- Preservation of unmodeled attribute and vendor-extension statements

## Evidence policy

DBC definitions remain attributed to their source file and hash. Atlas does not
automatically convert byte-activity candidates into named signals. Those require
repeatable captures or an authoritative definition.

DBC describes CAN-family frames. LIN belongs in an LDF-compatible subsystem;
diagnostic requests, DIDs and services require their own schema.

