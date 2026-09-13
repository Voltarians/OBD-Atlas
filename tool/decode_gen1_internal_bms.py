#!/usr/bin/env python3
"""Decode the Gen-1 Volt/Ampera internal 125 kbit/s BECM/BICM CAN bus.

Passive-only utility. Signal definitions are loaded from the normalized Atlas
community registry and retain their source confidence; this tool does not
promote community-derived definitions to direct vehicle validation.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

CANDUMP_RE = re.compile(
    r"^\((?P<timestamp>[0-9.]+)\)\s+(?P<bus>\S+)\s+(?P<id>[0-9A-Fa-f]+)#(?P<data>[0-9A-Fa-f]*)$"
)
DEFAULT_REGISTRY = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "gen1"
    / "community"
    / "internal_bms_known_signals.csv"
)


@dataclass(frozen=True)
class Frame:
    timestamp: float
    bus: str
    can_id: int
    data: bytes


@dataclass(frozen=True)
class SignalDef:
    network: str
    bitrate_kbps: int
    can_id: int
    message_name: str
    signal_name: str
    start_bit: int
    length: int
    endian: str
    signed: bool
    scale: float
    offset: float
    unit: str
    confidence: str
    source: str
    notes: str


def parse_frames(lines: Iterable[str]) -> Iterator[Frame]:
    for raw in lines:
        match = CANDUMP_RE.match(raw.strip())
        if not match:
            continue
        data_hex = match.group("data")
        if len(data_hex) % 2:
            continue
        yield Frame(
            timestamp=float(match.group("timestamp")),
            bus=match.group("bus"),
            can_id=int(match.group("id"), 16),
            data=bytes.fromhex(data_hex),
        )


def motorola(data: bytes, start_bit: int, length: int, *, signed: bool = False) -> int:
    bit = start_bit
    value = 0
    for _ in range(length):
        byte_index = bit // 8
        bit_index = bit % 8
        if byte_index >= len(data):
            raise ValueError("signal exceeds payload")
        value = (value << 1) | ((data[byte_index] >> bit_index) & 1)
        bit = bit + 15 if bit_index == 0 else bit - 1
    if signed and value & (1 << (length - 1)):
        value -= 1 << length
    return value


def little_endian(data: bytes, start_bit: int, length: int, *, signed: bool = False) -> int:
    value = int.from_bytes(data, "little")
    raw = (value >> start_bit) & ((1 << length) - 1)
    if signed and raw & (1 << (length - 1)):
        raw -= 1 << length
    return raw


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict[int, list[SignalDef]]:
    by_id: dict[int, list[SignalDef]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            signal_name = row["signal_name"].strip()
            if not signal_name:
                continue
            if not row["start_bit"].strip() or not row["length"].strip():
                continue
            item = SignalDef(
                network=row["network"].strip(),
                bitrate_kbps=int(row["bitrate_kbps"]),
                can_id=int(row["can_id_hex"], 16),
                message_name=row["message_name"].strip(),
                signal_name=signal_name,
                start_bit=int(row["start_bit"]),
                length=int(row["length"]),
                endian=row["endian"].strip().lower(),
                signed=_as_bool(row["signed"]),
                scale=float(row["scale"]),
                offset=float(row["offset"]),
                unit=row["unit"].strip(),
                confidence=row["confidence"].strip(),
                source=row["source"].strip(),
                notes=row["notes"].strip(),
            )
            if item.network != "internal_becm_bicm" or item.bitrate_kbps != 125:
                continue
            by_id.setdefault(item.can_id, []).append(item)
    return by_id


def decode_signal(data: bytes, definition: SignalDef) -> float:
    if definition.endian in {"motorola", "big", "big_endian"}:
        raw = motorola(
            data, definition.start_bit, definition.length, signed=definition.signed
        )
    elif definition.endian in {"little", "intel", "little_endian"}:
        raw = little_endian(
            data, definition.start_bit, definition.length, signed=definition.signed
        )
    else:
        raise ValueError(f"unsupported endian: {definition.endian}")
    return raw * definition.scale + definition.offset


def decode_frame(frame: Frame, registry: dict[int, list[SignalDef]]) -> list[dict]:
    rows: list[dict] = []
    for definition in registry.get(frame.can_id, []):
        try:
            value = decode_signal(frame.data, definition)
        except ValueError:
            continue
        rows.append(
            {
                "timestamp": frame.timestamp,
                "bus": frame.bus,
                "network": definition.network,
                "bitrateKbps": definition.bitrate_kbps,
                "canId": f"0x{frame.can_id:03X}",
                "message": definition.message_name,
                "signal": definition.signal_name,
                "value": round(value, 6),
                "unit": definition.unit,
                "confidence": definition.confidence,
                "source": definition.source,
                "payload": frame.data.hex().upper(),
                "notes": definition.notes,
            }
        )
    return rows


def analyze(
    lines: Iterable[str], registry: dict[int, list[SignalDef]] | None = None
) -> list[dict]:
    registry = registry or load_registry()
    rows: list[dict] = []
    for frame in parse_frames(lines):
        rows.extend(decode_frame(frame, registry))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="Atlas/candump log from the 125 kbit/s bus")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    registry = load_registry(args.registry)
    with args.capture.open("r", encoding="utf-8", errors="replace") as handle:
        rows = analyze(handle, registry)

    text = json.dumps(
        {
            "network": "internal_becm_bicm",
            "bitrateKbps": 125,
            "evidenceBoundary": "community-derived definitions; passive decode only",
            "rows": rows,
        },
        indent=2,
    ) + "\n"
    if args.json_out:
        args.json_out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
