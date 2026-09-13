#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' 'OBD Atlas Linux / PCG-1 bootstrap'
printf '%s\n' 'Checking required tools...'

if ! command -v flutter >/dev/null 2>&1; then
  echo 'ERROR: Flutter is not installed or is not on PATH.' >&2
  echo 'Install the current stable Flutter SDK, then run this script again.' >&2
  exit 1
fi

if ! command -v candump >/dev/null 2>&1; then
  echo 'ERROR: candump is missing. Install can-utils first:' >&2
  echo '  sudo apt install -y can-utils' >&2
  exit 1
fi

flutter --version

printf '%s\n' 'Enabling Linux desktop support...'
flutter config --enable-linux-desktop

printf '%s\n' 'Generating the Linux platform project without replacing lib/ or pubspec.yaml...'
flutter create --platforms=linux --project-name obd_atlas .

printf '%s\n' 'Resolving packages...'
flutter pub get

printf '%s\n' 'Checking Linux toolchain...'
flutter doctor -v

cat <<'EOF'

Bootstrap complete.

Run OBD Atlas Linux:
  flutter run -d linux -t lib/main_linux.dart

Build a release bundle:
  flutter build linux --release -t lib/main_linux.dart

SocketCAN quick check:
  ip -details link show type can
  candump -L can0
EOF
