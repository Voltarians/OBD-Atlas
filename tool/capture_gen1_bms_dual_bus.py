#!/usr/bin/env python3
"""Capture Gen-1 BECM/BICM 125k and HV Energy Management 500k simultaneously.

Passive-only wrapper around candump. Both interfaces are captured by one
candump process so timestamps share the same host clock. Configure the CAN
interfaces (including hardware/software listen-only) before running this tool.
"""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--internal-if", required=True, help="125 kbit/s BECM/BICM SocketCAN interface")
    parser.add_argument("--hv-if", required=True, help="500 kbit/s HV Energy Management SocketCAN interface")
    parser.add_argument("--out", type=Path, required=True, help="candump log output path")
    parser.add_argument("--manifest", type=Path, help="optional JSON session manifest")
    parser.add_argument("--duration", type=float, help="optional capture duration in seconds")
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    command = ["candump", "-L", args.internal_if, args.hv_if]

    with args.out.open("w", encoding="utf-8") as handle:
        proc = subprocess.Popen(command, stdout=handle, stderr=subprocess.PIPE, text=True)
        try:
            proc.wait(timeout=args.duration)
        except subprocess.TimeoutExpired:
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=5)
        except KeyboardInterrupt:
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=5)

    ended = datetime.now(timezone.utc)
    stderr = proc.stderr.read() if proc.stderr else ""
    manifest = {
        "schema": "obd-atlas.gen1-bms-dual-bus-capture.v1",
        "captureMode": "passive",
        "startedUtc": started.isoformat(),
        "endedUtc": ended.isoformat(),
        "durationSeconds": (ended - started).total_seconds(),
        "interfaces": [
            {"name": args.internal_if, "network": "internal_becm_bicm", "bitrateKbps": 125},
            {"name": args.hv_if, "network": "hv_energy_management", "bitrateKbps": 500},
        ],
        "log": str(args.out),
        "candumpExitCode": proc.returncode,
        "stderr": stderr.strip(),
        "evidenceBoundary": "Interface bitrate/listen-only configuration must be established before this capture; this tool never transmits.",
    }
    if args.manifest:
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0 if proc.returncode in (0, -signal.SIGINT) else proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
