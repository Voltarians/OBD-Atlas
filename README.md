# OBD Atlas

Universal passive-first OBD-II vehicle research by Voltarians.

## Frontend direction

OBD Atlas is being built as a standalone offline-first application for **Windows**, **Android**, and **Linux**. Internet access is optional and is not required at the vehicle.

The first application shell includes:

- Vehicle workspace
- Adapter connection page
- Passive capture page
- Live-data dashboard
- Local Atlas capture library
- Offline-first settings
- A shared DBC workspace on Windows, Android, and Linux for validated local
  import, provenance display, and revalidated `.dbc` export

## Import and export DBC definitions

Atlas can parse DBC files into normalized SQLite tables, list stored definition
sources, and export deterministic DBC files with semantic round-trip validation:

```bash
python3 atlas.py dbc-import vehicle.dbc --database obd_atlas.sqlite3 --name research-source
python3 atlas.py dbc-list --database obd_atlas.sqlite3
python3 atlas.py dbc-export research-source exported.dbc --database obd_atlas.sqlite3
```

Imported definitions retain their source filename and SHA-256 hash. Atlas does
not promote changing-byte candidates into named DBC signals automatically.
See [docs/DBC_SUPPORT.md](docs/DBC_SUPPORT.md) for supported constructs,
provenance rules, CAN FD handling and limitations.

### Included evidence source

The repository includes the MIT-licensed
[`Volt_BMS.dbc`](dbc/third_party/volt_bms/Volt_BMS.dbc) for the Gen-1
Volt/Ampera battery's internal 125-kbit/s BMS network. It imports as 39
messages and 112 signals. This database is not a complete vehicle-network DBC;
see its [source and scope record](dbc/third_party/volt_bms/SOURCE.md).

## Windows and Android bootstrap

With Flutter installed on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\tool\bootstrap.ps1
```

Then run Windows:

```powershell
flutter run -d windows
```

For Android, connect a device with USB debugging enabled and run:

```powershell
flutter devices
flutter run -d <device-id>
```

## Linux / PCG-1 bootstrap

Linux uses the standard SocketCAN stack so OBD Atlas can receive traffic from CAN interfaces exposed by the Linux kernel without tying the application to one USB-adapter vendor.

Install the required Linux development packages, Flutter stable, and `can-utils`, then run:

```bash
chmod +x tool/bootstrap-linux.sh
./tool/bootstrap-linux.sh
```

Run the Linux PCG-1 entry point:

```bash
flutter run -d linux -t lib/main_linux.dart
```

Build a Linux release bundle:

```bash
flutter build linux --release -t lib/main_linux.dart
```

See `docs/LINUX_PCG1.md` for Raspberry Pi, SocketCAN and PCG-1 setup.

## Architecture

See `docs/OFFLINE_ARCHITECTURE.md` and `docs/LINUX_PCG1.md`.
