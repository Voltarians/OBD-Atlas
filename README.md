# OBD Atlas

Universal passive-first OBD-II vehicle research by Voltarians.

## Current foundation

OBD Atlas imports timestamped multi-interface SocketCAN captures into SQLite.
The importer preserves the original interface name, arbitration ID width,
payload, bus mapping, source-file checksums, zero-frame diagnostic channels,
and synchronized voice-file metadata.

It uses only Python's standard library.

## Import a capture

Keep the `.session.json`, candump `.log`, voice `.flac`, and metadata `.txt`
files together, then run:

```bash
python3 atlas.py ingest volt_capture_20260830_211652.session.json \
  --database obd_atlas.sqlite3
```

The importer verifies file sizes and SHA-256 hashes before writing anything.
It rejects malformed candump records and mismatched frame counts. Re-importing
an existing session requires the explicit `--replace` option.

## Inspect Atlas

```bash
python3 atlas.py summary --database obd_atlas.sqlite3
```

## Discover changing signals

After import, rank arbitration IDs by payload transitions, changing byte
positions, and observed value diversity:

```bash
python3 atlas.py discover volt_capture_20260830_211652 \
  --database obd_atlas.sqlite3 --limit 25
```

Discovery writes reproducible per-ID and per-byte metrics into `id_metrics`
and `byte_metrics`. These are candidates, not decoded signal claims. They are
intended for comparison against action windows and synchronized voice notes.

## Session manifest

Schema identifier: `voltec-atlas.capture-session.v1`

The manifest binds physical adapters and DLC pins to logged SocketCAN
interfaces. Original interface names remain authoritative so one capture can
contain several vehicle networks without merging their arbitration-ID spaces.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
