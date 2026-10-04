#!/usr/bin/env python3
"""Rank candidate radio/audio CAN IDs from existing Atlas/PCG-1 capture logs.

Accepts candump-style .log/.txt files containing forms such as:
  can4  10734099   [6]  00 00 00 8C 00 00
  (timestamp) can1 123#11223344
  can1 123#11223344

This is an offline analysis tool. It never opens vehicle interfaces.

The ranking favors IDs with multiple payload variants and byte-level activity,
which is useful for locating button/status traffic such as volume, source,
seek, mute, steering-wheel controls, HMI state, and amplifier status.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HASH_RE = re.compile(
    r"(?P<bus>can[0-9]+)\s+"
    r"(?P<id>[0-9A-Fa-f]{3,8})#(?P<data>[0-9A-Fa-f]*)"
)
BRACKET_RE = re.compile(
    r"(?P<bus>can[0-9]+)\s+"
    r"(?P<id>[0-9A-Fa-f]{3,8})\s+"
    r"\[(?P<dlc>[0-8])\]\s+"
    r"(?P<data>(?:[0-9A-Fa-f]{2}(?:\s+|$)){0,8})"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_line(line: str):
    m = HASH_RE.search(line)
    if m:
        data_hex = m.group("data")
        if len(data_hex) % 2:
            return None
        try:
            return (
                m.group("bus"),
                int(m.group("id"), 16),
                bytes.fromhex(data_hex),
            )
        except ValueError:
            return None

    m = BRACKET_RE.search(line)
    if m:
        try:
            data = bytes.fromhex(m.group("data"))
            dlc = int(m.group("dlc"))
            return (
                m.group("bus"),
                int(m.group("id"), 16),
                data[:dlc],
            )
        except ValueError:
            return None

    return None


def entropy(values: list[int]) -> float:
    if not values:
        return 0.0
    counts = Counter(values)
    total = len(values)
    result = 0.0
    for count in counts.values():
        p = count / total
        result -= p * math.log2(p)
    return result


def analyze(files: list[Path]) -> list[dict[str, Any]]:
    frames: dict[tuple[str, int], list[bytes]] = defaultdict(list)

    for path in files:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parsed = parse_line(line)
                if parsed is None:
                    continue
                bus, can_id, data = parsed
                frames[(bus, can_id)].append(data)

    rows: list[dict[str, Any]] = []

    for (bus, can_id), samples in frames.items():
        payload_counts = Counter(samples)
        max_len = max((len(s) for s in samples), default=0)
        byte_stats = []

        for index in range(max_len):
            vals = [s[index] for s in samples if len(s) > index]
            if not vals:
                continue
            unique = len(set(vals))
            ent = entropy(vals)
            if unique > 1:
                byte_stats.append({
                    "byte": index,
                    "unique_values": unique,
                    "entropy_bits": round(ent, 4),
                    "min": min(vals),
                    "max": max(vals),
                })

        variant_count = len(payload_counts)
        changing_bytes = len(byte_stats)
        payload_entropy = entropy([
            hash(payload) & 0xFFFFFFFF for payload in samples
        ])

        # Deliberately simple heuristic: prioritize observable state-change
        # traffic, while de-emphasizing constant heartbeat IDs.
        score = (
            min(variant_count, 64) * 2.0
            + changing_bytes * 4.0
            + min(payload_entropy, 8.0) * 3.0
            + math.log2(len(samples) + 1)
        )

        rows.append({
            "bus": bus,
            "can_id": f"0x{can_id:08X}",
            "frames": len(samples),
            "unique_payloads": variant_count,
            "changing_bytes": changing_bytes,
            "score": round(score, 3),
            "byte_activity": byte_stats,
            "top_payloads": [
                {"payload": payload.hex().upper(), "count": count}
                for payload, count in payload_counts.most_common(8)
            ],
        })

    rows.sort(
        key=lambda row: (
            -row["score"],
            -row["changing_bytes"],
            -row["unique_payloads"],
            row["bus"],
            row["can_id"],
        )
    )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--bus", action="append")
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()

    files: list[Path] = []
    for path in args.paths:
        if path.is_dir():
            files.extend(
                p for p in path.rglob("*")
                if p.is_file() and p.suffix.lower() in {".log", ".txt"}
            )
        elif path.is_file():
            files.append(path)

    if not files:
        ap.error("no readable .log/.txt capture files found")

    rows = analyze(files)
    if args.bus:
        wanted = set(args.bus)
        rows = [row for row in rows if row["bus"] in wanted]

    print("===== PASSIVE RADIO/AUDIO CANDIDATE RANKING =====")
    for row in rows[: args.top]:
        changing = ",".join(
            str(x["byte"]) for x in row["byte_activity"]
        ) or "-"
        print(
            f"{row['bus']:>4} {row['can_id']} "
            f"score={row['score']:7.3f} "
            f"frames={row['frames']:7d} "
            f"variants={row['unique_payloads']:4d} "
            f"changing_bytes={changing}"
        )

    output = args.output
    if output is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = Path("evidence/radio") / f"{stamp}_passive_scan.json"

    output.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "promethean.radio.passive_scan.v1",
        "created_utc": utc_now(),
        "offline_only": True,
        "files": [str(p) for p in files],
        "ranked_candidates": rows,
    }
    output.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"\nSaved analysis: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
