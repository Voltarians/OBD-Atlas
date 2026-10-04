# Vehicle identity and capture routing

## Scope

OBD Atlas remains a universal, offline-first research tool. Its public contribution intake initially accepts Chevrolet Volt data only. Other makes/models can be researched locally and stored in their own private vehicle-type collections. Opel Ampera and Cadillac ELR are related to Gen-1 Voltec but have distinct vehicle identities and are not silently classified as Chevrolet Volt. Gen-1 Volt covers 2011–2015 and Gen-2 covers 2016–2019. Model year, not production date, determines the catalog generation. Never infer an exact vehicle from shared CAN arbitration IDs or a filename.

## Capture contract

The canonical raw stream remains ordinary candump `-L` data. No comments, VINs, or proprietary headers are inserted into `.log` files. A companion `<session-id>.session.json` uses the existing `voltec-atlas.capture-session.v1` schema and adds `identity_schema: obd-atlas.vehicle-identity.v1` and a structured vehicle record. Required identity fields for classified data are `make`, `model`, `model_year`, and `generation` when applicable. `vehicle_type` is a derived, normalized routing key. `identity_source` records `user_selected`, `vin_decoded`, `curator_verified`, or `unknown`; user selection is not verified evidence. The local profile may retain an optional VIN, but the capture manifest, filename and directory never contain the full VIN. A trusted VIN-decoder integration is future work; entering a VIN does not establish vehicle identity. A user can also capture into `unidentified` without guessing.

Every new session receives a unique random-suffixed ID and freezes its vehicle identity at creation. At the end of recording, the writer is flushed before the manifest is finalized with the raw file size, SHA-256, frame count, observed interfaces/IDs, timestamps and completion/error status. Incomplete or malformed captures remain available as evidence and are not represented as successful captures. Existing candump compatibility and raw bytes are preserved. No automatic network upload is introduced.

Local layout:

```text
OBD Atlas/logs/
  chevrolet-volt-gen1/2013/<session-id>/<session-id>.log
                                      <session-id>.session.json
  chevrolet-volt-gen2/2018/<session-id>/...
  toyota-prius/2015/<session-id>/...
  unidentified/unknown-year/<session-id>/...
  imports/unclassified/<legacy-file>
```

Old files remain untouched. A legacy import lacking reliable identity stays unclassified; a filename such as `volt_capture...` is not proof of model, year, or generation. Do not bulk relabel historical captures. Preserve the original, attach an independent evidence record, and promote only after review.

## Private intake and authoritative review

`tools/vehicle_ingest.py` is a local CLI and is not an internet-facing upload service. All received bundles are staged privately with content hashes and a server-owned receipt. Client claims such as `identity_status=verified` and `public_upload_authorized=true` never authorize admission. A known non-Volt submission is rejected from the public intake; the research scope accepts other makes. Unknown submissions are quarantined until independently identified. A trusted operator must review identity and privacy before promotion. Conflicts are rejected rather than silently overwritten. A public candidate subsequently identified as another vehicle requires explicit reclassification into research. No public publication endpoint is implemented.

After review, accepted originals remain private, with distinct vehicle-type directories and SQLite databases. The existing passive importer is reused for frame storage. Public Volt and private non-Volt data cannot accidentally share a database. Raw CAN/diagnostic traffic may itself contain VINs, identifiers, location or other sensitive payloads. A VIN-free manifest is not sufficient anonymization: retain original evidence privately and perform a separate payload/privacy review before any public release. Never publish raw VINs, security credentials, or user identifiers by default. The operator also needs the contributor's informed consent and an appropriate retention/deletion policy before a real public service is launched.

## Verification

Run Python intake tests with `python -m unittest discover -s tests -v`. Run Flutter tests with `flutter test` and static analysis with `flutter analyze`. Validate an actual capture on PCG-1 before deploying to contributors. This feature does not claim to provide automatic VIN decoding, a live upload endpoint, or production-ready public hosting.
