#!/usr/bin/env python3
"""Decode evidence-backed Gen-1 Volt high-voltage-management CAN frames.

This tool is intentionally passive: it reads Atlas/candump logs and never
transmits.  It concentrates on signals that have useful community definitions
and direct Atlas observations.  Ambiguous fields (notably 0x308 and 0x30A) are
preserved as raw payloads rather than promoted to settled decodes.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

CANDUMP_RE = re.compile(
    r"^\((?P<timestamp>[0-9.]+)\)\s+(?P<bus>\S+)\s+(?P<id>[0-9A-Fa-f]+)#(?P<data>[0-9A-Fa-f]*)$"
)

CELL_IDS = {0x200: 1, 0x202: 2, 0x204: 3, 0x206: 4}


@dataclass(frozen=True)
class Frame:
    timestamp: float
    bus: str
    can_id: int
    data: bytes


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
    """Decode a DBC Motorola/big-endian signal."""
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


def decode_cell_block(frame: Frame) -> dict:
    block = CELL_IDS[frame.can_id]
    bank = motorola(frame.data, 55, 3)
    values = [
        motorola(frame.data, 4, 12) * 0.00125,
        motorola(frame.data, 20, 12) * 0.00125,
        motorola(frame.data, 39, 12) * 0.00125,
    ]
    # The four blocks x eight banks x three slots yield 96 measurements.  The
    # physical GM Battery 1..96 ordering still needs GDS2 cross-validation, so
    # these are deliberately called measurement slots rather than cell numbers.
    slot_base = (block - 1) * 24 + bank * 3
    return {
        "type": "batteryCellVoltageBlock",
        "block": block,
        "bank": bank,
        "measurementSlots": [slot_base + 1, slot_base + 2, slot_base + 3],
        "volts": [round(value, 5) for value in values],
        "mappingBoundary": "slot order is not yet equated to GM Battery 1-96 numbering",
    }


def decode_pack_stats(frame: Frame) -> dict:
    voltage = motorola(frame.data, 7, 12) * 0.125
    current = motorola(frame.data, 23, 8, signed=True) * 0.1 - 0.1
    return {
        "type": "packStats",
        "packVoltageV": round(voltage, 3),
        "packCurrentCandidateA": round(current, 3),
        "currentConfidence": "candidate",
    }


def decode_charger_stats(frame: Frame) -> dict:
    return {
        "type": "chargerStats",
        "hvCurrentA": round(motorola(frame.data, 7, 13) * 0.05, 3),
        "hvVoltageV": round(motorola(frame.data, 10, 10) * 0.5, 3),
        "lvCurrentA": round(motorola(frame.data, 16, 8) * 0.2, 3),
        "lvVoltageV": round(motorola(frame.data, 24, 8) * 0.1, 3),
        "confidence": "communityCorroborated",
    }


def decode_battery_temp(frame: Frame) -> dict:
    mux = (frame.data[0] >> 2) & 0x01
    if mux == 0:
        labels = list("ABCDEF")
        raw_values = frame.data[1:7]
    else:
        labels = list("GHI")
        raw_values = frame.data[1:4]
    values = [round(raw * 0.5 - 40.0, 3) for raw in raw_values]
    return {
        "type": "batteryTemperatureGroup",
        "mux": mux,
        "labels": labels,
        "temperaturesC": values,
        "mappingBoundary": "A-I are community labels; exact GM scan-tool sensor numbering needs GDS2 cross-validation",
    }


def decode_charger_command(frame: Frame) -> dict:
    mode = frame.data[0] if frame.data else None
    mode_names = {0: "disabled", 1: "lv12VOnly", 2: "hvOnly", 3: "hvAndLv12V"}
    return {
        "type": "chargerModeCommand",
        "mode": mode,
        "modeName": mode_names.get(mode, "unknown"),
        "trailingRaw": frame.data[1:].hex().upper(),
        "confidence": "communityCorroborated",
    }


def decode_charger_parameters(frame: Frame) -> dict:
    # Independent charger implementations encode current in byte 1 at 20 counts/A
    # and voltage as the big-endian bytes 2-3 at 2 counts/V.  A disabled command
    # may retain an irrelevant/stale voltage field, so callers should interpret
    # setpoints only together with an enabled 0x30E mode.
    if len(frame.data) < 4:
        raise ValueError("0x304 requires 4 bytes")
    voltage_raw = (frame.data[2] << 8) | frame.data[3]
    return {
        "type": "chargerParameters",
        "unknownByte0": frame.data[0],
        "requestedCurrentA": round(frame.data[1] * 0.05, 3),
        "requestedVoltageV": round(voltage_raw * 0.5, 3),
        "validityNote": "interpret requested setpoints only when 0x30E enables the relevant charger output",
        "confidence": "communityCorroborated",
    }


def decode_coolant(frame: Frame) -> dict:
    inlet = motorola(frame.data, 1, 10) * 0.125 - 40.0
    outlet = motorola(frame.data, 17, 10) * 0.125 - 40.0
    return {
        "type": "batteryCoolantTemperature",
        "inletC": round(inlet, 3),
        "outletC": round(outlet, 3),
        "confidence": "atlasObservedCandidate",
    }


def decode_frame(frame: Frame) -> dict | None:
    if frame.can_id in CELL_IDS and len(frame.data) >= 8:
        decoded = decode_cell_block(frame)
    elif frame.can_id == 0x210 and len(frame.data) >= 8:
        decoded = decode_pack_stats(frame)
    elif frame.can_id == 0x212 and len(frame.data) >= 5:
        decoded = decode_charger_stats(frame)
    elif frame.can_id == 0x302 and len(frame.data) >= 8:
        decoded = decode_battery_temp(frame)
    elif frame.can_id == 0x304 and len(frame.data) >= 4:
        decoded = decode_charger_parameters(frame)
    elif frame.can_id == 0x30E and len(frame.data) >= 1:
        decoded = decode_charger_command(frame)
    elif frame.can_id == 0x460 and len(frame.data) >= 4:
        decoded = decode_coolant(frame)
    elif frame.can_id in {0x308, 0x30A}:
        decoded = {
            "type": "ambiguousRaw",
            "reason": "community definitions are not sufficiently consistent for Atlas promotion",
            "payload": frame.data.hex().upper(),
        }
    else:
        return None
    return {
        "timestamp": frame.timestamp,
        "bus": frame.bus,
        "canId": f"0x{frame.can_id:03X}",
        "payload": frame.data.hex().upper(),
        "decoded": decoded,
    }


def analyze(lines: Iterable[str]) -> list[dict]:
    rows = []
    for frame in parse_frames(lines):
        decoded = decode_frame(frame)
        if decoded is not None:
            rows.append(decoded)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="Atlas/candump log")
    parser.add_argument("--json-out", type=Path, help="write decoded rows as JSON")
    args = parser.parse_args()

    with args.capture.open("r", encoding="utf-8", errors="replace") as handle:
        rows = analyze(handle)

    if args.json_out:
        args.json_out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
