# OBD Atlas

Universal passive-first OBD-II vehicle research by Voltarians.

## Public alpha

Download the current Windows, Linux x64, Raspberry Pi/Linux ARM64, or Android test build from [GitHub Releases](https://github.com/Voltarians/OBD-Atlas/releases). See [the public prerelease instructions](docs/PUBLIC_PRERELEASE.md) before installing. This is an alpha research tool; use passive/listen-only capture.

## Frontend direction

OBD Atlas is being built as a standalone offline-first application for **Windows**, **Android**, and **Linux**. Internet access is optional and is not required at the vehicle.

The first application shell includes:

- Vehicle workspace
- Adapter connection page
- Passive capture page
- Live-data dashboard
- Local Atlas capture library
- Offline-first settings

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

Linux also supports receive-only OBDLink MX+ monitoring through a BlueZ RFCOMM
serial device. See [OBDLink MX+ on Linux ARM64](docs/LINUX_OBDLINK_MX.md) for
pairing, binding and connection instructions.

See `docs/LINUX_PCG1.md` for Raspberry Pi, SocketCAN and PCG-1 setup.

## Architecture

See `docs/OFFLINE_ARCHITECTURE.md` and `docs/LINUX_PCG1.md`.
