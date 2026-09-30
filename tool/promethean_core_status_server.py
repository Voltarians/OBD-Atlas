#!/usr/bin/env python3
"""Read-only Promethean Core / PCG-1 status endpoint.

This service reports Linux SocketCAN interface state and counters for Voltarian
Phase 1. It does not open CAN sockets, change interface configuration, or
transmit frames.

Examples:
  python3 tool/promethean_core_status_server.py --once
  python3 tool/promethean_core_status_server.py --bind 0.0.0.0 --port 8765

Endpoint:
  GET /v1/status
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SCHEMA = "promethean.core.status.v1"
IDENTITY = "Promethean Core gateway"
DEFAULT_PORT = 8765


def _run_json(command: list[str]) -> Any:
    completed = subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return json.loads(completed.stdout)


def _git_version(repo_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "describe", "--always", "--dirty", "--tags"],
            cwd=repo_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        value = completed.stdout.strip()
        return value or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _nested(mapping: Any, *keys: str, default: Any = None) -> Any:
    current = mapping
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _ctrlmode_list(info_data: dict[str, Any]) -> list[str]:
    value = info_data.get("ctrlmode", [])
    if isinstance(value, list):
        return [str(item).upper() for item in value]
    if isinstance(value, str):
        return [part.strip().upper() for part in value.replace(",", " ").split()]
    if isinstance(value, dict):
        return [
            str(key).upper()
            for key, enabled in value.items()
            if bool(enabled)
        ]
    return []


def _bitrate(info_data: dict[str, Any]) -> int:
    candidates = (
        _nested(info_data, "bittiming", "bitrate"),
        info_data.get("bitrate"),
    )
    for value in candidates:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return 0


def _stats(entry: dict[str, Any]) -> tuple[int, int, int]:
    stats = entry.get("stats64")
    if not isinstance(stats, dict):
        stats = entry.get("stats", {})
    rx = stats.get("rx", {}) if isinstance(stats, dict) else {}

    frames = int(rx.get("packets", 0) or 0)
    errors = int(rx.get("errors", 0) or 0)
    overflows = int(
        rx.get("over_errors", 0)
        or rx.get("fifo_errors", 0)
        or rx.get("missed_errors", 0)
        or 0
    )
    return frames, errors, overflows


def read_can_interfaces() -> list[dict[str, Any]]:
    """Return status for existing SocketCAN interfaces without changing them."""
    try:
        entries = _run_json(
            ["ip", "-details", "-statistics", "-json", "link", "show", "type", "can"]
        )
    except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError):
        return []

    buses: list[dict[str, Any]] = []
    if not isinstance(entries, list):
        return buses

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        info_data = _nested(entry, "linkinfo", "info_data", default={})
        if not isinstance(info_data, dict):
            info_data = {}
        ctrlmodes = _ctrlmode_list(info_data)
        frames, errors, overflows = _stats(entry)
        buses.append(
            {
                "name": str(entry.get("ifname", "CAN")).upper(),
                "interface": str(entry.get("ifname", "unknown")),
                "bitrateBps": _bitrate(info_data),
                "frames": frames,
                "framesPerSecond": 0.0,
                "errors": errors,
                "overflows": overflows,
                "listenOnly": "LISTEN-ONLY" in ctrlmodes
                or "LISTEN_ONLY" in ctrlmodes
                or "LISTENONLY" in ctrlmodes,
            }
        )
    return buses


def sample_can_interfaces(interval: float = 0.25) -> list[dict[str, Any]]:
    first = read_can_interfaces()
    if not first:
        return first

    started = time.monotonic()
    time.sleep(interval)
    second = read_can_interfaces()
    elapsed = max(time.monotonic() - started, 0.001)

    first_by_interface = {
        str(bus.get("interface")): bus
        for bus in first
    }
    for bus in second:
        previous = first_by_interface.get(str(bus.get("interface")))
        if previous is None:
            continue
        delta = int(bus.get("frames", 0)) - int(previous.get("frames", 0))
        bus["framesPerSecond"] = max(delta, 0) / elapsed
    return second


def build_status(
    repo_root: Path,
    *,
    vim3_available: bool = False,
    hmi_available: bool = False,
) -> dict[str, Any]:
    buses = sample_can_interfaces()
    return {
        "schema": SCHEMA,
        "capturedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "node": {
            "hostname": socket.gethostname(),
            "identity": IDENTITY,
            "softwareVersion": _git_version(repo_root),
        },
        "platform": {
            "vim3Available": vim3_available,
            "hmiAvailable": hmi_available,
        },
        "safety": {
            "transmitLocked": True,
        },
        "buses": buses,
    }


class StatusHandler(BaseHTTPRequestHandler):
    server_version = "PrometheanCoreStatus/1"

    def do_GET(self) -> None:
        if self.path not in ("/v1/status", "/v1/status/"):
            self.send_error(404, "Not found")
            return

        payload = build_status(
            self.server.repo_root,  # type: ignore[attr-defined]
            vim3_available=self.server.vim3_available,  # type: ignore[attr-defined]
            hmi_available=self.server.hmi_available,  # type: ignore[attr-defined]
        )
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.client_address[0], self.log_date_time_string(), format % args)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print one JSON status document and exit.",
    )
    parser.add_argument(
        "--vim3-available",
        action="store_true",
        help="Mark the VIM3 as available in this status sample.",
    )
    parser.add_argument(
        "--hmi-available",
        action="store_true",
        help="Mark the HMI/display as available in this status sample.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]

    if args.port < 1 or args.port > 65535:
        raise SystemExit("--port must be between 1 and 65535")

    if args.once:
        print(
            json.dumps(
                build_status(
                    repo_root,
                    vim3_available=args.vim3_available,
                    hmi_available=args.hmi_available,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    server = ThreadingHTTPServer((args.bind, args.port), StatusHandler)
    server.repo_root = repo_root  # type: ignore[attr-defined]
    server.vim3_available = args.vim3_available  # type: ignore[attr-defined]
    server.hmi_available = args.hmi_available  # type: ignore[attr-defined]
    print(
        f"Promethean Core read-only status service: "
        f"http://{args.bind}:{args.port}/v1/status",
        flush=True,
    )
    print("CAN configuration is not modified; no CAN transmit path is opened.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping status service.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
