# OBD Atlas

Universal passive-first OBD-II vehicle research by Voltarians.

## Frontend direction

OBD Atlas is being built as a standalone offline-first application for **Windows** and **Android**. Internet access is optional and is not required at the vehicle.

The first application shell includes:

- Vehicle workspace
- Adapter connection page
- Passive capture page
- Live-data dashboard
- Local Atlas capture library
- Offline-first settings

## Bootstrap

The current branch contains the shared Flutter source. On Windows with Flutter installed:

```powershell
powershell -ExecutionPolicy Bypass -File .\tool\bootstrap.ps1
```

Then run:

```powershell
flutter run -d windows
```

For Android, connect a device with USB debugging enabled and run:

```powershell
flutter devices
flutter run -d <device-id>
```

## Architecture

See `docs/OFFLINE_ARCHITECTURE.md`.
