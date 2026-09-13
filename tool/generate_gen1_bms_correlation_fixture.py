#!/usr/bin/env python3
"""Generate deterministic passive-capture fixtures for Gen-1 BMS correlation tests."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import decode_gen1_internal_bms as internal  # noqa: E402


def set_motorola(payload: bytearray, start_bit: int, length: int, value: int) -> None:
    bit = start_bit
    for shift in range(length - 1, -1, -1):
        byte_index = bit // 8
        bit_index = bit % 8
        if value & (1 << shift):
            payload[byte_index] |= 1 << bit_index
        else:
            payload[byte_index] &= ~(1 << bit_index)
        bit = bit + 15 if bit_index == 0 else bit - 1


def synthetic_cell_voltage(cell_number: int, cycle: int) -> float:
    base = 3.60 + cell_number * 0.0016
    dynamic = (
        0.010 * math.sin(cycle * 0.73 + cell_number * 0.29)
        + 0.004 * math.sin(cycle * 1.37 + cell_number * 0.11)
    )
    return base + dynamic


def cell_to_slot(cell_number: int) -> int:
    return ((cell_number - 1) * 37) % 96 + 1


def _candump(timestamp: float, bus: str, can_id: int, payload: bytes) -> str:
    return f"({timestamp:.6f}) {bus} {can_id:03X}#{payload.hex().upper()}\n"


def generate_internal_lines(registry, cycles: int = 10) -> list[str]:
    cell_defs = [
        definition
        for defs in registry.values()
        for definition in defs
        if definition.signal_name.startswith("Cell_")
    ]
    by_id = {}
    for definition in cell_defs:
        by_id.setdefault(definition.can_id, []).append(definition)

    lines = []
    for cycle in range(cycles):
        base_time = cycle * 1.0
        for index, (can_id, definitions) in enumerate(sorted(by_id.items())):
            payload = bytearray(8)
            for definition in definitions:
                cell_number = int(definition.signal_name.split("_")[1])
                volts = synthetic_cell_voltage(cell_number, cycle)
                raw = int(round((volts - definition.offset) / definition.scale))
                set_motorola(payload, definition.start_bit, definition.length, raw)
            lines.append(_candump(base_time + index * 0.001, "can125", can_id, payload))
    return lines


def generate_hv_lines(cycles: int = 10) -> list[str]:
    lines = []
    can_ids = [0x200, 0x202, 0x204, 0x206]
    for cycle in range(cycles):
        base_time = cycle * 1.0 + 0.080
        slot_values = {
            cell_to_slot(cell): synthetic_cell_voltage(cell, cycle)
            for cell in range(1, 97)
        }
        frame_index = 0
        for block_index, can_id in enumerate(can_ids):
            for bank in range(8):
                payload = bytearray(8)
                set_motorola(payload, 55, 3, bank)
                slot_base = block_index * 24 + bank * 3
                for start_bit, slot in zip((4, 20, 39), range(slot_base + 1, slot_base + 4)):
                    raw = int(round(slot_values[slot] / 0.00125))
                    set_motorola(payload, start_bit, 12, raw)
                lines.append(_candump(base_time + frame_index * 0.001, "can500", can_id, payload))
                frame_index += 1
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=10)
    parser.add_argument("--registry", type=Path, default=internal.DEFAULT_REGISTRY)
    args = parser.parse_args()

    registry = internal.load_registry(args.registry)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    internal_path = args.out_dir / "sim_internal_bms_125k.log"
    hv_path = args.out_dir / "sim_hv_energy_500k.log"
    expected_path = args.out_dir / "sim_expected_cell_to_slot.csv"

    internal_path.write_text("".join(generate_internal_lines(registry, args.cycles)), encoding="utf-8")
    hv_path.write_text("".join(generate_hv_lines(args.cycles)), encoding="utf-8")
    expected_path.write_text(
        "cell,slot\n"
        + "".join(f"Cell_{cell:02d},HVslot_{cell_to_slot(cell):02d}\n" for cell in range(1, 97)),
        encoding="utf-8",
    )
    print(internal_path)
    print(hv_path)
    print(expected_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
