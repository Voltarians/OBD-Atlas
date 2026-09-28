#!/usr/bin/env python3
"""Rank FleetCarma Volt CAN signal candidates against GPS vehicle speed.

This tool is evidence-generation only. It does not assign semantic signal
names or promote candidates to confirmed mappings.

Input can be:
  * a FleetCarma CANLOG ZIP archive
  * a directory containing .BIN files
  * a single .BIN file

The decoder is shared with tool/import_fleetcarma_c5.py.

For each bus/CAN ID the analyzer reports:
  * frame count and approximate period
  * per-byte min/max/change-rate
  * Pearson correlation of each byte with GPS speed
  * Pearson correlation of adjacent 16-bit little/big-endian words with speed
  * top speed-correlated candidates with overlap counts

GPS speed is sourced from GPVTG/GNVTG km/h when present. Each CAN sample is
paired with the nearest speed sample in the same logger file, subject to a
maximum timestamp delta.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import import_fleetcarma_c5 as fleetcarma  # noqa: E402


@dataclass(frozen=True)
class Sample:
    timestamp_ms: int
    value: float


def pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    denom = math.sqrt(sum(v * v for v in dx) * sum(v * v for v in dy))
    if denom == 0:
        return 0.0
    return sum(a * b for a, b in zip(dx, dy)) / denom


def parse_vtg_speed_kph(sentence: str) -> float | None:
    text = sentence.lstrip("$")
    fields = text.split(",")
    if not fields or not fields[0].endswith("VTG"):
        return None
    # NMEA VTG: ... speed knots, N, speed km/h, K, mode
    try:
        k_index = fields.index("K")
    except ValueError:
        return None
    if k_index < 1:
        return None
    try:
        return float(fields[k_index - 1])
    except (TypeError, ValueError):
        return None


def nearest_speed(
    timestamp_ms: int,
    speeds: list[Sample],
    *,
    max_delta_ms: int,
) -> float | None:
    if not speeds:
        return None

    lo = 0
    hi = len(speeds)
    while lo < hi:
        mid = (lo + hi) // 2
        if speeds[mid].timestamp_ms < timestamp_ms:
            lo = mid + 1
        else:
            hi = mid

    candidates = []
    if lo < len(speeds):
        candidates.append(speeds[lo])
    if lo > 0:
        candidates.append(speeds[lo - 1])
    if not candidates:
        return None

    best = min(candidates, key=lambda s: abs(s.timestamp_ms - timestamp_ms))
    if abs(best.timestamp_ms - timestamp_ms) > max_delta_ms:
        return None
    return best.value


def _period_stats(timestamps: list[int]) -> dict:
    if len(timestamps) < 2:
        return {"medianMs": None, "meanMs": None}
    deltas = [
        b - a
        for a, b in zip(timestamps, timestamps[1:])
        if b >= a
    ]
    if not deltas:
        return {"medianMs": None, "meanMs": None}
    return {
        "medianMs": round(statistics.median(deltas), 3),
        "meanMs": round(sum(deltas) / len(deltas), 3),
    }


def _change_rate(values: list[int]) -> float:
    if len(values) < 2:
        return 0.0
    changed = sum(1 for a, b in zip(values, values[1:]) if a != b)
    return changed / (len(values) - 1)


def analyze_records(
    decoded_by_source: Iterable[tuple[str, fleetcarma.DecodeResult]],
    *,
    max_speed_delta_ms: int = 6000,
    min_overlap: int = 20,
) -> dict:
    grouped = defaultdict(list)
    speed_by_source: dict[str, list[Sample]] = {}

    source_count = 0
    total_can = 0
    total_speed = 0

    for source, decoded in decoded_by_source:
        source_count += 1
        speeds = []
        for gps in decoded.gps:
            speed = parse_vtg_speed_kph(gps.sentence)
            if speed is not None:
                speeds.append(Sample(gps.timestamp_ms, speed))
        speeds.sort(key=lambda s: s.timestamp_ms)
        speed_by_source[source] = speeds
        total_speed += len(speeds)

        for frame in decoded.can:
            grouped[(frame.bus, frame.can_id)].append((source, frame))
            total_can += 1

    id_reports = []
    all_candidates = []

    for (bus, can_id), rows in sorted(grouped.items()):
        rows.sort(key=lambda x: (x[0], x[1].timestamp_ms))
        dlc_counts = Counter(len(frame.data) for _, frame in rows)
        dominant_dlc = dlc_counts.most_common(1)[0][0] if dlc_counts else 0

        byte_values = [[] for _ in range(dominant_dlc)]
        byte_x = [[] for _ in range(dominant_dlc)]
        byte_y = [[] for _ in range(dominant_dlc)]
        le_x = [[] for _ in range(max(0, dominant_dlc - 1))]
        le_y = [[] for _ in range(max(0, dominant_dlc - 1))]
        be_x = [[] for _ in range(max(0, dominant_dlc - 1))]
        be_y = [[] for _ in range(max(0, dominant_dlc - 1))]
        per_source_ts = defaultdict(list)

        for source, frame in rows:
            if len(frame.data) != dominant_dlc:
                continue
            per_source_ts[source].append(frame.timestamp_ms)
            speed = nearest_speed(
                frame.timestamp_ms,
                speed_by_source.get(source, []),
                max_delta_ms=max_speed_delta_ms,
            )
            for i, value in enumerate(frame.data):
                byte_values[i].append(value)
                if speed is not None:
                    byte_x[i].append(float(value))
                    byte_y[i].append(float(speed))
            if speed is not None:
                for i in range(dominant_dlc - 1):
                    lo = frame.data[i]
                    hi = frame.data[i + 1]
                    le = lo | (hi << 8)
                    be = (lo << 8) | hi
                    le_x[i].append(float(le))
                    le_y[i].append(float(speed))
                    be_x[i].append(float(be))
                    be_y[i].append(float(speed))

        period_values = []
        for ts in per_source_ts.values():
            if len(ts) >= 2:
                d = _period_stats(ts)
                if d["medianMs"] is not None:
                    period_values.append(float(d["medianMs"]))

        byte_reports = []
        for i, values in enumerate(byte_values):
            corr = pearson(byte_x[i], byte_y[i]) if len(byte_x[i]) >= min_overlap else 0.0
            item = {
                "byte": i,
                "min": min(values) if values else None,
                "max": max(values) if values else None,
                "changeRate": round(_change_rate(values), 6),
                "speedCorrelation": round(corr, 6),
                "speedOverlap": len(byte_x[i]),
            }
            byte_reports.append(item)
            if len(byte_x[i]) >= min_overlap:
                all_candidates.append({
                    "bus": bus,
                    "canIdHex": f"{can_id:03X}",
                    "kind": "u8",
                    "offset": i,
                    "speedCorrelation": round(corr, 6),
                    "absSpeedCorrelation": round(abs(corr), 6),
                    "overlap": len(byte_x[i]),
                })

        word_reports = []
        for i in range(max(0, dominant_dlc - 1)):
            le_corr = pearson(le_x[i], le_y[i]) if len(le_x[i]) >= min_overlap else 0.0
            be_corr = pearson(be_x[i], be_y[i]) if len(be_x[i]) >= min_overlap else 0.0
            word_reports.extend([
                {
                    "offset": i,
                    "encoding": "u16le",
                    "speedCorrelation": round(le_corr, 6),
                    "speedOverlap": len(le_x[i]),
                },
                {
                    "offset": i,
                    "encoding": "u16be",
                    "speedCorrelation": round(be_corr, 6),
                    "speedOverlap": len(be_x[i]),
                },
            ])
            if len(le_x[i]) >= min_overlap:
                all_candidates.append({
                    "bus": bus,
                    "canIdHex": f"{can_id:03X}",
                    "kind": "u16le",
                    "offset": i,
                    "speedCorrelation": round(le_corr, 6),
                    "absSpeedCorrelation": round(abs(le_corr), 6),
                    "overlap": len(le_x[i]),
                })
            if len(be_x[i]) >= min_overlap:
                all_candidates.append({
                    "bus": bus,
                    "canIdHex": f"{can_id:03X}",
                    "kind": "u16be",
                    "offset": i,
                    "speedCorrelation": round(be_corr, 6),
                    "absSpeedCorrelation": round(abs(be_corr), 6),
                    "overlap": len(be_x[i]),
                })

        id_reports.append({
            "bus": bus,
            "canIdHex": f"{can_id:03X}",
            "frames": len(rows),
            "dlcHistogram": {str(k): v for k, v in sorted(dlc_counts.items())},
            "dominantDlc": dominant_dlc,
            "medianPeriodMsAcrossSessions": (
                round(statistics.median(period_values), 3)
                if period_values else None
            ),
            "bytes": byte_reports,
            "words": word_reports,
        })

    all_candidates.sort(
        key=lambda row: (row["absSpeedCorrelation"], row["overlap"]),
        reverse=True,
    )

    for row in all_candidates:
        corr = row["absSpeedCorrelation"]
        if row["overlap"] < min_overlap:
            confidence = "insufficientOverlap"
        elif corr >= 0.95:
            confidence = "strongCandidate"
        elif corr >= 0.80:
            confidence = "candidate"
        elif corr >= 0.60:
            confidence = "weakCandidate"
        else:
            confidence = "background"
        row["confidence"] = confidence

    return {
        "schema": "atlas.fleetcarma-signal-correlation.v1",
        "mappingStatus": "candidateOnly",
        "evidenceBoundary": (
            "GPS correlation is external evidence, not semantic confirmation. "
            "Candidates must be reproduced in independent live Volt captures "
            "before promotion to confirmed vehicle signals."
        ),
        "sourceFiles": source_count,
        "canFrames": total_can,
        "gpsSpeedSamples": total_speed,
        "maxSpeedPairDeltaMs": max_speed_delta_ms,
        "minimumOverlap": min_overlap,
        "ids": id_reports,
        "topSpeedCandidates": all_candidates[:50],
    }


def analyze_path(
    path: Path,
    *,
    max_speed_delta_ms: int = 6000,
    min_overlap: int = 20,
) -> dict:
    decoded = (
        (source, fleetcarma.decode_blob(blob, source))
        for source, blob in fleetcarma.iter_inputs(path)
    )
    return analyze_records(
        decoded,
        max_speed_delta_ms=max_speed_delta_ms,
        min_overlap=min_overlap,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--max-speed-delta-ms", type=int, default=6000)
    parser.add_argument("--min-overlap", type=int, default=20)
    args = parser.parse_args()

    result = analyze_path(
        args.input,
        max_speed_delta_ms=args.max_speed_delta_ms,
        min_overlap=args.min_overlap,
    )
    text = json.dumps(result, indent=2) + "\n"
    if args.json_out:
        args.json_out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
