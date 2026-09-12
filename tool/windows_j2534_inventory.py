#!/usr/bin/env python3
"""Inventory installed Windows J2534 PassThru providers for OBD Atlas.

This is a read-only discovery tool. It does not load a J2534 DLL, open a
vehicle interface, alter registry values, or communicate with a vehicle.

On 64-bit Windows both native and WOW6432Node registrations are checked. The
output is intended to seed Atlas GM Tool Capture manifests with the exact
vendor/library identity selected for GDS2, SPS/SPS2 or DPS.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Iterable

try:  # pragma: no cover - unavailable on non-Windows CI
    import winreg  # type: ignore
except ImportError:  # pragma: no cover
    winreg = None


J2534_REGISTRY_LOCATIONS = (
    r"SOFTWARE\PassThruSupport.04.04",
    r"SOFTWARE\WOW6432Node\PassThruSupport.04.04",
    r"SOFTWARE\PassThruSupport.05.00",
    r"SOFTWARE\WOW6432Node\PassThruSupport.05.00",
)

INTERESTING_VALUES = (
    "Name",
    "Vendor",
    "FunctionLibrary",
    "ConfigApplication",
    "CAN",
    "ISO15765",
    "ISO9141",
    "ISO14230",
    "J1850PWM",
    "J1850VPW",
    "SCI_A_ENGINE",
    "SCI_A_TRANS",
    "SCI_B_ENGINE",
    "SCI_B_TRANS",
)


def registry_locations() -> tuple[str, ...]:
    return J2534_REGISTRY_LOCATIONS


def _read_value(key: Any, name: str) -> Any | None:
    assert winreg is not None
    try:
        value, _kind = winreg.QueryValueEx(key, name)
        return value
    except FileNotFoundError:
        return None


def _iter_subkeys(key: Any) -> Iterable[str]:
    assert winreg is not None
    index = 0
    while True:
        try:
            yield winreg.EnumKey(key, index)
        except OSError:
            return
        index += 1


def _library_metadata(path_value: Any) -> dict[str, Any]:
    if not isinstance(path_value, str) or not path_value.strip():
        return {
            "path": None,
            "exists": False,
            "sizeBytes": None,
            "modifiedUnixSeconds": None,
        }
    path = Path(os.path.expandvars(path_value.strip().strip('"')))
    try:
        stat = path.stat()
        return {
            "path": str(path),
            "exists": True,
            "sizeBytes": stat.st_size,
            "modifiedUnixSeconds": stat.st_mtime,
        }
    except OSError:
        return {
            "path": str(path),
            "exists": False,
            "sizeBytes": None,
            "modifiedUnixSeconds": None,
        }


def normalize_provider(
    *,
    registry_path: str,
    subkey: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    function_library = values.get("FunctionLibrary")
    return {
        "registryPath": registry_path,
        "registrySubkey": subkey,
        "name": values.get("Name") or subkey,
        "vendor": values.get("Vendor"),
        "functionLibrary": _library_metadata(function_library),
        "configApplication": values.get("ConfigApplication"),
        "capabilities": {
            name: values[name]
            for name in INTERESTING_VALUES
            if name not in {"Name", "Vendor", "FunctionLibrary", "ConfigApplication"}
            and name in values
        },
    }


def inventory_windows_registry() -> list[dict[str, Any]]:
    if winreg is None:
        raise RuntimeError("Windows J2534 registry inventory requires Windows.")

    providers: list[dict[str, Any]] = []
    access = winreg.KEY_READ
    for registry_path in J2534_REGISTRY_LOCATIONS:
        try:
            root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path, 0, access)
        except FileNotFoundError:
            continue
        with root:
            for subkey in _iter_subkeys(root):
                try:
                    provider_key = winreg.OpenKey(root, subkey, 0, access)
                except OSError:
                    continue
                with provider_key:
                    values: dict[str, Any] = {}
                    for name in INTERESTING_VALUES:
                        value = _read_value(provider_key, name)
                        if value is not None:
                            values[name] = value
                    providers.append(
                        normalize_provider(
                            registry_path=registry_path,
                            subkey=subkey,
                            values=values,
                        )
                    )
    providers.sort(
        key=lambda row: (
            str(row.get("vendor") or "").lower(),
            str(row.get("name") or "").lower(),
            str(row.get("registryPath") or "").lower(),
        )
    )
    return providers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, help="optional JSON output")
    args = parser.parse_args()

    try:
        providers = inventory_windows_registry()
    except RuntimeError as error:
        print(error)
        return 2

    result = {
        "schemaVersion": 1,
        "source": "Windows J2534 registry",
        "readOnly": True,
        "providerCount": len(providers),
        "providers": providers,
    }

    rendered = json.dumps(result, indent=2)
    if args.json_out:
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
