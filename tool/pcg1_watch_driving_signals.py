#!/usr/bin/env python3
"""Watch promoted passive driving signals in the PCG-1 Core state file."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

FIELDS = (
    "vehicle_speed_mph",
    "accelerator_pct",
    "accelerator_raw",
    "brake_raw",
    "drive_position",
    "drive_position_raw",
    "shift_position",
    "shift_position_raw",
)


def load_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path("/run/promethean/vehicle_state.json"),
    )
    parser.add_argument("--interval", type=float, default=0.10)
    args = parser.parse_args()

    previous: dict[str, Any] = {}
    print(f"Watching {args.state_file} for passive driving-signal changes.")
    print("Ctrl-C to stop.")

    try:
        while True:
            state = load_state(args.state_file)
            current = {field: state.get(field) for field in FIELDS if field in state}
            changed = {
                field: value
                for field, value in current.items()
                if previous.get(field) != value
            }
            if changed:
                stamp = time.strftime("%H:%M:%S")
                rendered = "  ".join(f"{key}={value}" for key, value in changed.items())
                print(f"[{stamp}] {rendered}", flush=True)
            previous = current
            time.sleep(max(args.interval, 0.02))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
