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

## Transcribe synchronized voice notes

Install `faster-whisper` in a virtual environment, then generate a timestamped
TSV transcript:

```bash
python3 tools/transcribe_audio.py capture.flac --model base.en
```

The first run downloads the selected model. `base.en` is the default balance
for CPU transcription. Output timestamps are relative to the beginning of the
audio file and remain separate from the original evidence files.

## Correlate voice annotations with CAN changes

After correcting only the transcript text (never its timestamp columns), run:

```bash
python3 atlas.py correlate SESSION_ID capture.transcript.tsv \
  --database obd_atlas.sqlite3 --limit 8
```

Atlas converts audio-relative timestamps to the capture's CAN epoch, compares
each annotation window with the preceding baseline, and stores ranked byte
candidates in `annotations` and `correlations`. High scores are research leads;
rolling counters and multi-action speech segments can also score highly and
must not be treated as decoded signals without repeat captures.

## Session manifest

Schema identifier: `voltec-atlas.capture-session.v1`

The manifest binds physical adapters and DLC pins to logged SocketCAN
interfaces. Original interface names remain authoritative so one capture can
contain several vehicle networks without merging their arbitration-ID spaces.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
