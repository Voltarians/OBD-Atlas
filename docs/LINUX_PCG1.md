# OBD Atlas on Linux / PCG-1

OBD Atlas treats Linux as a first-class deployment target for PCG-1 and Raspberry Pi-class ARM64 systems.

## Design

The Linux path keeps the shared Atlas data model, local capture storage, frame counters, and offline-first behavior. Vehicle CAN transport is provided through Linux SocketCAN rather than vendor-specific Windows USB APIs.

Initial Linux transport:

- SocketCAN interface discovery through `/sys/class/net`
- Passive receive through `candump -L`
- Multi-channel mapping into the existing Atlas channel model
- Candump-compatible local capture files
- Standard CAN, extended CAN and remote-frame parsing
- Initial CAN FD payload acceptance; FD metadata/flags will be expanded later

This means any adapter that Linux exposes as a SocketCAN network interface can become an Atlas source without adding another vendor-specific UI path.

## Raspberry Pi / Debian prerequisites

Install the Linux desktop build toolchain and CAN utilities:

```bash
sudo apt update
sudo apt install -y \
  clang \
  cmake \
  ninja-build \
  pkg-config \
  libgtk-3-dev \
  libstdc++-12-dev \
  can-utils \
  git \
  curl \
  unzip \
  xz-utils \
  zip \
  libglu1-mesa
```

Install the current stable Flutter SDK separately and ensure `flutter` is on `PATH`.

Validate it:

```bash
flutter --version
flutter doctor -v
```

## Bootstrap OBD Atlas

From the repository root:

```bash
chmod +x tool/bootstrap-linux.sh
./tool/bootstrap-linux.sh
```

The script enables Linux desktop support, generates the standard Flutter Linux runner, resolves packages and checks the toolchain.

## Run the Linux application

```bash
flutter run -d linux -t lib/main_linux.dart
```

Release build:

```bash
flutter build linux --release -t lib/main_linux.dart
```

## SocketCAN setup

OBD Atlas intentionally does not change CAN bitrates or bring interfaces up as root. Configure the interface at the operating-system layer first.

Example 500 kbit/s interface:

```bash
sudo ip link set can0 down 2>/dev/null || true
sudo ip link set can0 type can bitrate 500000
sudo ip link set can0 up
ip -details link show can0
```

Example 33.333 kbit/s interface:

```bash
sudo ip link set can0 down 2>/dev/null || true
sudo ip link set can0 type can bitrate 33333
sudo ip link set can0 up
ip -details link show can0
```

Confirm traffic independently before blaming the application:

```bash
candump -L can0
```

If `candump` sees frames, OBD Atlas should be able to attach to the same active SocketCAN interface.

## PCG-1 direction

The Linux edition is intended to become the highest-capability Atlas host. Planned Linux-specific expansion includes:

- six CAN/CAN FD channels for PCG-1
- SWCAN interface integration
- LIN acquisition bridges
- persistent interface naming with udev
- automatic adapter inventory
- PCG-PSM telemetry
- headless capture service mode
- boot-time capture and recovery
- native SocketCAN FFI path to remove the `candump` helper-process dependency

The first implementation deliberately uses standard Linux tools because they are transparent, easy to diagnose and work across many adapter vendors.
