#!/usr/bin/env python3
"""Correlate Gen-1 125 kbit/s BICM cells with 500 kbit/s HV measurement slots.

The input captures must share a time base (the companion dual SocketCAN logger
does this). The result is deliberately a candidate mapping, never an automatic
promotion to confirmed signal identity.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import decode_gen1_hv_capture as hv  # noqa: E402
import decode_gen1_internal_bms as internal  # noqa: E402


@dataclass(frozen=True)
class Score:
    cell: str
    slot: str
    score: float
    delta_correlation: float
    rmse_v: float
    overlap: int


def _nearest_pairs(a, b, max_delta_s: float):
    if not a or not b:
        return []
    result = []
    j = 0
    for ta, va in a:
        while j + 1 < len(b) and abs(b[j + 1][0] - ta) <= abs(b[j][0] - ta):
            j += 1
        if abs(b[j][0] - ta) <= max_delta_s:
            result.append((va, b[j][1]))
    return result


def _pearson(values_a, values_b) -> float:
    if len(values_a) != len(values_b) or len(values_a) < 2:
        return 0.0
    mean_a = sum(values_a) / len(values_a)
    mean_b = sum(values_b) / len(values_b)
    da = [value - mean_a for value in values_a]
    db = [value - mean_b for value in values_b]
    numerator = sum(x * y for x, y in zip(da, db))
    denom = math.sqrt(sum(x * x for x in da) * sum(y * y for y in db))
    return numerator / denom if denom else 0.0


def _score_pair(cell, slot, cell_series, slot_series, *, max_delta_s: float) -> Score:
    pairs = _nearest_pairs(cell_series, slot_series, max_delta_s)
    if len(pairs) < 2:
        return Score(cell, slot, 0.0, 0.0, 999.0, len(pairs))
    cell_values = [a for a, _ in pairs]
    slot_values = [b for _, b in pairs]
    rmse = math.sqrt(sum((a - b) ** 2 for a, b in pairs) / len(pairs))
    cell_delta = [b - a for a, b in zip(cell_values, cell_values[1:])]
    slot_delta = [b - a for a, b in zip(slot_values, slot_values[1:])]
    corr = _pearson(cell_delta, slot_delta) if len(cell_delta) >= 2 else 0.0
    rmse_term = math.exp(-rmse / 0.005)
    overlap_term = min(1.0, len(pairs) / 8.0)
    score = 0.65 * max(0.0, corr) + 0.25 * rmse_term + 0.10 * overlap_term
    return Score(cell, slot, round(score, 6), round(corr, 6), round(rmse, 6), len(pairs))


def decode_internal_cells(lines: Iterable[str], registry=None):
    series = {}
    for row in internal.analyze(lines, registry):
        name = row["signal"]
        if name.startswith("Cell_"):
            series.setdefault(name, []).append((float(row["timestamp"]), float(row["value"])))
    for values in series.values():
        values.sort()
    return series


def decode_hv_slots(lines: Iterable[str]):
    series = {}
    for row in hv.analyze(lines):
        decoded = row["decoded"]
        if decoded.get("type") != "batteryCellVoltageBlock":
            continue
        for slot, volts in zip(decoded["measurementSlots"], decoded["volts"]):
            name = f"HVslot_{slot:02d}"
            series.setdefault(name, []).append((float(row["timestamp"]), float(volts)))
    for values in series.values():
        values.sort()
    return series


def rank_mapping(cell_series, slot_series, *, max_delta_s: float = 0.25, min_pairs: int = 4) -> dict:
    scores = [
        _score_pair(cell, slot, a, b, max_delta_s=max_delta_s)
        for cell, a in sorted(cell_series.items())
        for slot, b in sorted(slot_series.items())
    ]
    assigned = []
    used_cells = set()
    used_slots = set()
    for item in sorted(scores, key=lambda value: value.score, reverse=True):
        if item.cell in used_cells or item.slot in used_slots:
            continue
        assigned.append(item)
        used_cells.add(item.cell)
        used_slots.add(item.slot)

    candidates_by_cell = {}
    for item in scores:
        candidates_by_cell.setdefault(item.cell, []).append(item)
    for items in candidates_by_cell.values():
        items.sort(key=lambda value: value.score, reverse=True)

    rows = []
    for item in sorted(assigned, key=lambda value: value.cell):
        alternatives = [
            {"slot": alt.slot, "score": alt.score, "rmseV": alt.rmse_v,
             "deltaCorrelation": alt.delta_correlation, "overlap": alt.overlap}
            for alt in candidates_by_cell[item.cell][:3]
        ]
        if item.overlap < min_pairs:
            confidence = "insufficientOverlap"
        elif item.score >= 0.90 and item.rmse_v <= 0.003:
            confidence = "strongCandidate"
        elif item.score >= 0.75:
            confidence = "candidate"
        else:
            confidence = "weakCandidate"
        rows.append({
            "cell": item.cell, "slot": item.slot, "score": item.score,
            "rmseV": item.rmse_v, "deltaCorrelation": item.delta_correlation,
            "overlap": item.overlap, "confidence": confidence,
            "alternatives": alternatives,
        })

    return {
        "networkA": {"name": "internal_becm_bicm", "bitrateKbps": 125},
        "networkB": {"name": "hv_energy_management", "bitrateKbps": 500},
        "mappingStatus": "candidateOnly",
        "evidenceBoundary": (
            "Correlation never auto-promotes a mapping to confirmed. Repeat the same pairing "
            "across independent rest/charge/discharge sessions and review evidence before promotion."
        ),
        "cellCount": len(cell_series),
        "slotCount": len(slot_series),
        "assignedCount": len(rows),
        "mapping": rows,
    }


def correlate_files(internal_path: Path, hv_path: Path, *, registry_path=internal.DEFAULT_REGISTRY,
                    max_delta_s: float = 0.25, min_pairs: int = 4) -> dict:
    registry = internal.load_registry(registry_path)
    with internal_path.open("r", encoding="utf-8", errors="replace") as handle:
        cells = decode_internal_cells(handle, registry)
    with hv_path.open("r", encoding="utf-8", errors="replace") as handle:
        slots = decode_hv_slots(handle)
    return rank_mapping(cells, slots, max_delta_s=max_delta_s, min_pairs=min_pairs)


def write_mapping_csv(result: dict, path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "cell", "slot", "score", "rmse_v", "delta_correlation", "overlap", "confidence", "mapping_status"
        ])
        writer.writeheader()
        for row in result["mapping"]:
            writer.writerow({
                "cell": row["cell"], "slot": row["slot"], "score": row["score"],
                "rmse_v": row["rmseV"], "delta_correlation": row["deltaCorrelation"],
                "overlap": row["overlap"], "confidence": row["confidence"],
                "mapping_status": result["mappingStatus"],
            })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("internal_125k", type=Path)
    parser.add_argument("hv_500k", type=Path)
    parser.add_argument("--registry", type=Path, default=internal.DEFAULT_REGISTRY)
    parser.add_argument("--max-time-delta", type=float, default=0.25)
    parser.add_argument("--min-pairs", type=int, default=4)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--csv-out", type=Path)
    args = parser.parse_args()
    result = correlate_files(args.internal_125k, args.hv_500k, registry_path=args.registry,
                             max_delta_s=args.max_time_delta, min_pairs=args.min_pairs)
    text = json.dumps(result, indent=2) + "\n"
    if args.json_out:
        args.json_out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    if args.csv_out:
        write_mapping_csv(result, args.csv_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
