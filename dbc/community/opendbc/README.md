# OpenDBC GM Global-A reference sources

These files are imported as **reference evidence**, not as independently confirmed OBD Atlas signals.

Upstream: `commaai/opendbc`
Pinned commit: `954217059383e0129c650740f11be74cb286000a` (2026-09-11)
License: MIT; see `LICENSE` in this directory.

The bulk importer `tool/import-community-dbcs.py` downloads and provenance-imports these six sources into Atlas's DBC SQLite store:

- `gm_global_a_high_voltage_management.dbc` — Volt/Ampera high-voltage management and BECM data
- `gm_global_a_lowspeed.dbc` — GM Global-A low-speed/SWCAN definitions
- `gm_global_a_chassis.dbc` — chassis-network definitions
- `gm_global_a_object.dbc` — object/radar-network definitions
- `gm_global_a_powertrain_expansion.dbc` — community powertrain/HV expansion definitions
- `generator/gm/gm_global_a_powertrain.dbc` — current generated powertrain source definitions

Import all sources with:

```bash
python3 tool/import-community-dbcs.py --database obd_atlas.sqlite3
```

Atlas stores the imported source filename and SHA-256 provenance. The verified Gen-1 catalog in `assets/signals/chevrolet_volt_gen1.json` remains authoritative for signals independently confirmed on the test vehicle.
