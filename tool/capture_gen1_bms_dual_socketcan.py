#!/usr/bin/env python3
"""Passively capture synchronized Gen-1 125 kbit/s and 500 kbit/s SocketCAN buses.

The interfaces must already be configured at the correct bitrates. This tool
does not change interface state, configure bitrate, or transmit CAN frames.
"""

from __future__ import annotations

import argparse
import json
import select
import socket
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

CAN_FRAME = struct.Struct("=IB3x8s")
CAN_EFF_FLAG = 0x80000000
CAN_EFF_MASK = 0x1FFFFFFF
CAN_SFF_MASK = 0x000007FF


def open_can(iface: str) -> socket.socket:
    sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    sock.bind((iface,))
    sock.setblocking(False)
    return sock


def decode_socketcan_frame(raw: bytes) -> tuple[int, bytes]:
    can_id_raw, dlc, payload = CAN_FRAME.unpack(raw[: CAN_FRAME.size])
    if can_id_raw & CAN_EFF_FLAG:
        can_id = can_id_raw & CAN_EFF_MASK
    else:
        can_id = can_id_raw & CAN_SFF_MASK
    return can_id, payload[: min(dlc, 8)]


def format_candump(timestamp: float, iface: str, can_id: int, payload: bytes) -> str:
    width = 8 if can_id > 0x7FF else 3
    return f"({timestamp:.6f}) {iface} {can_id:0{width}X}#{payload.hex().upper()}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--internal-iface", required=True, help="preconfigured 125 kbit/s SocketCAN interface")
    parser.add_argument("--hv-iface", required=True, help="preconfigured 500 kbit/s SocketCAN interface")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--duration", type=float, help="optional capture duration in seconds")
    args = parser.parse_args()

    if args.internal_iface == args.hv_iface:
        parser.error("internal and HV interfaces must be different")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    internal_path = args.out_dir / f"gen1_internal_bms_125k_{stamp}.log"
    hv_path = args.out_dir / f"gen1_hv_energy_500k_{stamp}.log"
    manifest_path = args.out_dir / f"gen1_dual_bms_capture_{stamp}.json"

    internal_sock = open_can(args.internal_iface)
    hv_sock = open_can(args.hv_iface)
    sockets = {
        internal_sock: (args.internal_iface, internal_path, "internal_becm_bicm", 125),
        hv_sock: (args.hv_iface, hv_path, "hv_energy_management", 500),
    }
    start_mono = time.monotonic()
    counts = {"internal_becm_bicm": 0, "hv_energy_management": 0}

    try:
        with internal_path.open("w", encoding="utf-8") as internal_handle, hv_path.open(
            "w", encoding="utf-8"
        ) as hv_handle:
            handles = {internal_path: internal_handle, hv_path: hv_handle}
            while True:
                if args.duration is not None and time.monotonic() - start_mono >= args.duration:
                    break
                readable, _, _ = select.select(list(sockets), [], [], 0.25)
                now = time.monotonic()
                for sock in readable:
                    iface, path, network, _bitrate = sockets[sock]
                    raw = sock.recv(CAN_FRAME.size)
                    can_id, payload = decode_socketcan_frame(raw)
                    handles[path].write(format_candump(now, iface, can_id, payload))
                    counts[network] += 1
    except KeyboardInterrupt:
        pass
    finally:
        internal_sock.close()
        hv_sock.close()

    manifest = {
        "captureType": "gen1DualBmsPassive",
        "startedUtc": stamp,
        "commonTimestampClock": "time.monotonic",
        "transmit": False,
        "interfaceConfiguration": (
            "Interfaces must be configured before launch; this tool does not change bitrate or interface state."
        ),
        "networks": [
            {
                "name": "internal_becm_bicm",
                "expectedBitrateKbps": 125,
                "interface": args.internal_iface,
                "file": internal_path.name,
                "frames": counts["internal_becm_bicm"],
            },
            {
                "name": "hv_energy_management",
                "expectedBitrateKbps": 500,
                "interface": args.hv_iface,
                "file": hv_path.name,
                "frames": counts["hv_energy_management"],
            },
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
