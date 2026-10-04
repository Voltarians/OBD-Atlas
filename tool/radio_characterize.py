#!/usr/bin/env python3
"""Capture and compare Gen-1 Volt radio/audio activity on PCG-1 SWCAN.

Workflow:
  1) capture a BASELINE window
  2) prompt for one physical radio/audio action
  3) capture an ACTION window
  4) report changed IDs/bytes and save JSON evidence

Receive-only. Uses the PCG-1 RH02 SocketCAN SWCAN interface (can0) by default.
It intentionally reports every changed ID, not only pre-labeled radio IDs, so
unknown radio/HMI/amplifier traffic can be discovered from the vehicle.
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
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000

DEFAULT_INTERFACE = "can0"
DEFAULT_SECONDS = 8.0

SUGGESTED_LABELS = (
    "volume_up",
    "volume_down",
    "mute",
    "source",
    "seek_up",
    "seek_down",
    "tune_up",
    "tune_down",
    "preset_1",
    "preset_2",
    "steering_volume_up",
    "steering_volume_down",
    "steering_seek",
    "power",
)


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
            if can_id_raw & (CAN_RTR_FLAG | CAN_ERR_FLAG):
                continue

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


def payload_variants(samples: list[bytes], limit: int = 8) -> list[dict[str, Any]]:
    counts = Counter(samples)
    return [
        {"payload": payload.hex().upper(), "count": count}
        for payload, count in counts.most_common(limit)
    ]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Receive-only Gen-1 Volt radio/audio SWCAN characterization"
    )
    ap.add_argument("--interface", default=DEFAULT_INTERFACE)
    ap.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    ap.add_argument("--label", default="radio_action")
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=Path("evidence/radio"),
    )
    ap.add_argument(
        "--show-labels",
        action="store_true",
        help="print suggested action labels and exit",
    )
    args = ap.parse_args()

    if args.show_labels:
        for label in SUGGESTED_LABELS:
            print(label)
        return 0

    print(f"Capturing RADIO BASELINE on {args.interface} for {args.seconds:.1f}s...")
    baseline = capture(args.interface, args.seconds)

    input(
        "\nPerform ONE physical radio/audio action now, then press Enter "
        "to capture the changed state..."
    )

    print(f"Capturing RADIO ACTION on {args.interface} for {args.seconds:.1f}s...")
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
                "status": "appeared",
                "action_count": a["count"] if a else 0,
                "action_variants": payload_variants(action.get(can_id, [])),
            })
            continue

        if a is None:
            changed.append({
                "can_id": f"0x{can_id:08X}",
                "status": "disappeared",
                "baseline_count": b["count"],
                "baseline_variants": payload_variants(baseline.get(can_id, [])),
            })
            continue

        diffs = byte_diffs(b["most_common"], a["most_common"])
        count_delta = a["count"] - b["count"]
        variant_delta = a["unique_payloads"] - b["unique_payloads"]

        if diffs or count_delta or variant_delta:
            changed.append({
                "can_id": f"0x{can_id:08X}",
                "status": "changed",
                "baseline_payload": b["most_common"].hex().upper(),
                "action_payload": a["most_common"].hex().upper(),
                "baseline_count": b["count"],
                "action_count": a["count"],
                "count_delta": count_delta,
                "baseline_unique_payloads": b["unique_payloads"],
                "action_unique_payloads": a["unique_payloads"],
                "unique_payload_delta": variant_delta,
                "byte_diffs": diffs,
                "baseline_variants": payload_variants(baseline.get(can_id, [])),
                "action_variants": payload_variants(action.get(can_id, [])),
            })

    changed.sort(
        key=lambda item: (
            -len(item.get("byte_diffs", [])),
            -abs(item.get("unique_payload_delta", 0)),
            -abs(item.get("count_delta", 0)),
            item["can_id"],
        )
    )

    print("\n===== RADIO CHARACTERIZATION RESULT =====")
    if not changed:
        print("No changed CAN IDs detected.")
    else:
        for item in changed:
            print(f"{item['can_id']}  {item['status']}")
            if item["status"] == "changed":
                print(f"  baseline: {item['baseline_payload']}")
                print(f"  action:   {item['action_payload']}")
                for d in item["byte_diffs"]:
                    print(
                        f"  byte {d['byte']}: "
                        f"{d['baseline']:02X} -> {d['action']:02X} "
                        f"(xor {d['xor']:02X})"
                    )
                if item["unique_payload_delta"]:
                    print(
                        "  unique-payload delta: "
                        f"{item['unique_payload_delta']:+d}"
                    )
                if item["count_delta"]:
                    print(f"  frame-count delta: {item['count_delta']:+d}")
            elif item["status"] == "appeared":
                print("  appeared only during action window")
            elif item["status"] == "disappeared":
                print("  disappeared during action window")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = args.output_dir / f"{stamp}_{args.label}.json"

    doc = {
        "schema": "promethean.radio.characterization.v1",
        "created_utc": utc_now(),
        "interface": args.interface,
        "capture_seconds": args.seconds,
        "label": args.label,
        "receive_only": True,
        "capture_scope": "pcg1_rh02_swcan",
        "suggested_labels": list(SUGGESTED_LABELS),
        "changed": changed,
    }

    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"\nSaved evidence: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
