# OBD Atlas

Universal, passive-first OBD-II vehicle research for Android and iOS, with a
Proxmox-ready fleet-data receiver.

## Version 0.1 scope

- qualify ELM327/STN adapters before capture
- inventory legislated OBD-II protocols and responding ECU addresses
- record Atlas-compatible candump and detailed CSV logs
- preserve capture manifests, integrity counters, and source provenance
- upload only with explicit operator consent
- keep active diagnostics, clearing, control, security access, and programming disabled

Voltec Atlas remains the deep Chevrolet Volt/Cadillac ELR specialization. OBD
Atlas provides the reusable universal layer and does not claim manufacturer-
specific coverage without evidence.

## App

The Flutter source is shared by Android and iOS. Until generated platform files
are committed, run `flutter create --platforms=android,ios .`, then `flutter
pub get`, `flutter analyze`, and `flutter test`.

## Backend

Copy `.env.example` to `.env`, choose a strong API key, and run:

```bash
docker compose up -d --build
```

The receiver accepts gzipped or plain session bundles at `/v1/captures`, stores
immutable payloads on a mounted data volume, and records metadata in PostgreSQL.

## Safety

Version 0.1 is read-only and passive-first. VIN collection and upload require
clear operator consent. Public research exports must hash or remove VINs and
strip location, account, and device identifiers.
