#!/usr/bin/env bash
set -euo pipefail

RULE='/etc/udev/rules.d/99-obd-atlas-uc2.rules'

cat <<'EOF' | sudo tee "$RULE" >/dev/null
SUBSYSTEM=="usb", ATTR{idVendor}=="0471", ATTR{idProduct}=="1200", MODE="0660", GROUP="plugdev", TAG+="uaccess"
EOF

if ! getent group plugdev >/dev/null 2>&1; then
  sudo groupadd --system plugdev
fi

sudo usermod -aG plugdev "$USER"
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=0471 --attr-match=idProduct=1200 || true

echo "Installed $RULE"
echo "User $USER added to plugdev. Log out/in once if Atlas cannot open the adapter yet."
echo "Unplug/replug UC2 adapters after installing the rule."
