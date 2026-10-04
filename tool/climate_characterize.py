#!/usr/bin/env python3
"""Capture and compare Gen-1 Volt SWCAN climate activity.

Workflow:
  1) capture a BASELINE window
  2) prompt for one physical HVAC action
  3) capture an ACTION window
  4) report changed IDs/bytes and save JSON evidence

Receive-only. Uses SocketCAN interface can0 by default.
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CAN_EFF_MASK = 0x1FFFFFFF
DEFAULT_INTERFACE = "can0"
DEFAULT_SECONDS = 8.0

KNOWN_CLIMATE_IDS = {
    0x10734099: "climate_general_status",
    0x10814099: "climate_basic_status_blower",
    0x10440099: "cabin_temperature_estimate",
    0x1047809D: "coolant_heater_status",
    0x102700CB: "ac_evaporator_compressor",
    0x106D4099: "heater_core_temperature",
    0x10390040: "remote_climate_status",
    0x107220A9: "seat_heat_status",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def capture(interface: str, seconds: float) -> dict[int, list[bytes]]:
    sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    sock.bind((interface,))
    sock.settimeout(0.5)

    out: dict[int, list[bytes]] = defaultdict(list)
    end = time.monotonic() + seconds
    try:
        while time.monotonic() < end:
            try:
                raw = sock.recv(16)
            except socket.timeout:
                continue
            if len(raw) < 16:
                continue
            can_id_raw, dlc, data = struct.unpack("=IB3x8s", raw)
            can_id = can_id_raw & CAN_EFF_MASK
            out[can_id].append(bytes(data[: min(int(dlc), 8)]))
    finally:
        sock.close()
    return dict(out)


def summarize(frames: dict[int, list[bytes]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for can_id, samples in frames.items():
        counts = Counter(samples)
        most_common, most_common_count = counts.most_common(1)[0]
        result[can_id] = {
            "count": len(samples),
            "unique_payloads": len(counts),
            "most_common": most_common,
            "most_common_count": most_common_count,
            "last": samples[-1],
        }
    return result


def byte_diffs(a: bytes, b: bytes) -> list[dict[str, int]]:
    diffs: list[dict[str, int]] = []
    n = max(len(a), len(b))
    for i in range(n):
        av = a[i] if i < len(a) else -1
        bv = b[i] if i < len(b) else -1
        if av != bv:
            diffs.append({
                "byte": i,
                "baseline": av,
                "action": bv,
                "xor": (av ^ bv) & 0xFF if av >= 0 and bv >= 0 else -1,
            })
    return diffs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interface", default=DEFAULT_INTERFACE)
    ap.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    ap.add_argument("--label", default="climate_action")
    ap.add_argument("--output-dir", type=Path, default=Path("evidence/climate"))
    args = ap.parse_args()

    print(f"Capturing BASELINE on {args.interface} for {args.seconds:.1f}s...")
    baseline = capture(args.interface, args.seconds)

    input(
        "\nPerform ONE physical HVAC action now (fan, temp, A/C, defrost, "
        "recirc, seat heat, etc.), then press Enter..."
    )

    print(f"Capturing ACTION on {args.interface} for {args.seconds:.1f}s...")
    action = capture(args.interface, args.seconds)

    base_sum = summarize(baseline)
    act_sum = summarize(action)

    ids = sorted(set(base_sum) | set(act_sum))
    changed: list[dict[str, Any]] = []

    for can_id in ids:
        b = base_sum.get(can_id)
        a = act_sum.get(can_id)

        if b is None:
            changed.append({
                "can_id": f"0x{can_id:08X}",
                "name": KNOWN_CLIMATE_IDS.get(can_id),
                "status": "appeared",
                "action_last": a["last"].hex().upper() if a else None,
                "action_count": a["count"] if a else 0,
            })
            continue

        if a is None:
            changed.append({
                "can_id": f"0x{can_id:08X}",
                "name": KNOWN_CLIMATE_IDS.get(can_id),
                "status": "disappeared",
                "baseline_last": b["last"].hex().upper(),
                "baseline_count": b["count"],
            })
            continue

        diffs = byte_diffs(b["most_common"], a["most_common"])
        count_delta = a["count"] - b["count"]
        if diffs or count_delta:
            changed.append({
                "can_id": f"0x{can_id:08X}",
                "name": KNOWN_CLIMATE_IDS.get(can_id),
                "status": "changed",
                "baseline_payload": b["most_common"].hex().upper(),
                "action_payload": a["most_common"].hex().upper(),
                "baseline_count": b["count"],
                "action_count": a["count"],
                "count_delta": count_delta,
                "byte_diffs": diffs,
            })

    changed.sort(
        key=lambda x: (
            0 if x.get("name") else 1,
            -len(x.get("byte_diffs", [])),
            x["can_id"],
        )
    )

    print("\n===== CLIMATE CHARACTERIZATION RESULT =====")
    if not changed:
        print("No changed CAN IDs detected.")
    else:
        for item in changed:
            print(f"{item['can_id']}  {item.get('name') or ''}  {item['status']}")
            if item["status"] == "changed":
                print(f"  baseline: {item['baseline_payload']}")
                print(f"  action:   {item['action_payload']}")
                for d in item["byte_diffs"]:
                    print(
                        f"  byte {d['byte']}: "
                        f"{d['baseline']:02X} -> {d['action']:02X} "
                        f"(xor {d['xor']:02X})"
                    )
                if item["count_delta"]:
                    print(f"  frame-count delta: {item['count_delta']:+d}")
            elif item["status"] == "appeared":
                print(f"  action: {item.get('action_last')}")
            elif item["status"] == "disappeared":
                print(f"  baseline: {item.get('baseline_last')}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = args.output_dir / f"{stamp}_{args.label}.json"

    doc = {
        "schema": "promethean.climate.characterization.v1",
        "created_utc": utc_now(),
        "interface": args.interface,
        "capture_seconds": args.seconds,
        "label": args.label,
        "known_climate_ids": {
            f"0x{k:08X}": v for k, v in KNOWN_CLIMATE_IDS.items()
        },
        "changed": changed,
    }
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"\nSaved evidence: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
