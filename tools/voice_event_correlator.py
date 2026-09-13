#!/usr/bin/env python3
"""Correlate timestamped Atlas voice annotations with raw candump changes."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


CANDUMP_RE = re.compile(
    r"^\((?P<timestamp>\d+(?:\.\d+)?)\)\s+"
    r"(?P<interface>\S+)\s+"
    r"(?P<can_id>[0-9A-Fa-f]{1,8})#(?P<data>[0-9A-Fa-f]*)$"
)


def distribution_distance(left: Counter[int], right: Counter[int]) -> float:
    left_total = sum(left.values())
    right_total = sum(right.values())
    if not left_total or not right_total:
        return 0.0
    values = set(left) | set(right)
    return 0.5 * sum(
        abs(left[value] / left_total - right[value] / right_total)
        for value in values
    )


def load_frames(path: Path) -> list[tuple[float, str, int, bytes]]:
    frames: list[tuple[float, str, int, bytes]] = []
    with path.open("r", encoding="utf-8", errors="strict") as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            match = CANDUMP_RE.match(line)
            if not match:
                raise ValueError(f"Malformed candump line {line_number}: {line[:120]}")
            data_text = match.group("data")
            if len(data_text) % 2:
                raise ValueError(f"Odd-length CAN data on line {line_number}")
            frames.append(
                (
                    float(match.group("timestamp")),
                    match.group("interface"),
                    int(match.group("can_id"), 16),
                    bytes.fromhex(data_text),
                )
            )
    return frames


def load_transcript(path: Path) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"audio_start_seconds", "audio_end_seconds", "text"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(
                "Transcript requires audio_start_seconds, audio_end_seconds, and text"
            )
        previous_end = -1.0
        for index, row in enumerate(reader, start=1):
            start = float(row["audio_start_seconds"])
            end = float(row["audio_end_seconds"])
            text = row["text"].strip()
            if start < previous_end or end < start:
                raise ValueError(f"Invalid transcript timing at row {index + 1}")
            previous_end = end
            if text:
                events.append({"index": index, "start": start, "end": end, "text": text})
    return events


def correlate(
    frames: list[tuple[float, str, int, bytes]],
    events: list[dict[str, object]],
    audio_epoch: float,
    *,
    baseline_seconds: float,
    after_seconds: float,
    minimum_observations: int,
    limit: int,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for event in events:
        audio_start = float(event["start"])
        audio_end = float(event["end"])
        can_start = audio_epoch + audio_start
        can_end = audio_epoch + max(audio_end, audio_start + 0.050) + after_seconds
        baseline_start = can_start - baseline_seconds
        buckets: dict[str, defaultdict[tuple[str, int, int], Counter[int]]] = {
            "baseline": defaultdict(Counter),
            "action": defaultdict(Counter),
        }

        for timestamp, interface, arbitration_id, data in frames:
            if timestamp < baseline_start or timestamp >= can_end:
                continue
            if timestamp < can_start:
                period = "baseline"
            else:
                period = "action"
            for byte_index, value in enumerate(data):
                buckets[period][(interface, arbitration_id, byte_index)][value] += 1

        candidates: list[dict[str, object]] = []
        keys = set(buckets["baseline"]) & set(buckets["action"])
        for interface, arbitration_id, byte_index in keys:
            baseline = buckets["baseline"][(interface, arbitration_id, byte_index)]
            action = buckets["action"][(interface, arbitration_id, byte_index)]
            baseline_count = sum(baseline.values())
            action_count = sum(action.values())
            if baseline_count < minimum_observations or action_count < minimum_observations:
                continue
            baseline_mean = sum(value * count for value, count in baseline.items()) / baseline_count
            action_mean = sum(value * count for value, count in action.items()) / action_count
            distance = distribution_distance(baseline, action)
            score = 100 * distance + 20 * abs(action_mean - baseline_mean) / 255
            candidates.append(
                {
                    "interface": interface,
                    "can_id_hex": f"0x{arbitration_id:X}",
                    "byte_index": byte_index,
                    "baseline_observations": baseline_count,
                    "action_observations": action_count,
                    "baseline_mean": round(baseline_mean, 6),
                    "action_mean": round(action_mean, 6),
                    "distribution_distance": round(distance, 6),
                    "score": round(score, 6),
                }
            )
        candidates.sort(key=lambda item: float(item["score"]), reverse=True)
        results.append(
            {
                "annotation_index": event["index"],
                "text": event["text"],
                "audio_start_seconds": audio_start,
                "audio_end_seconds": audio_end,
                "can_window_start_epoch_seconds": can_start,
                "can_window_end_epoch_seconds": can_end,
                "candidates": candidates[:limit],
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candump", type=Path)
    parser.add_argument("voice_metadata", type=Path)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline-seconds", type=float, default=5.0)
    parser.add_argument("--after-seconds", type=float, default=0.75)
    parser.add_argument("--minimum-observations", type=int, default=3)
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()

    metadata = json.loads(args.voice_metadata.read_text(encoding="utf-8"))
    audio_epoch = metadata.get("audio_start_epoch_seconds")
    if audio_epoch is None:
        parser.error("voice metadata has no audio_start_epoch_seconds")

    frames = load_frames(args.candump)
    events = load_transcript(args.transcript)
    results = correlate(
        frames,
        events,
        float(audio_epoch),
        baseline_seconds=args.baseline_seconds,
        after_seconds=args.after_seconds,
        minimum_observations=args.minimum_observations,
        limit=args.limit,
    )

    payload = {
        "schema": "obd-atlas.voice-event-correlation.v1",
        "evidence_class": "voiceSupportingEvidenceOnly",
        "input_latency_calibrated": bool(
            metadata.get("alignment", {}).get("input_latency_calibrated", False)
        ),
        "candump": str(args.candump),
        "voice_metadata": str(args.voice_metadata),
        "transcript": str(args.transcript),
        "baseline_seconds": args.baseline_seconds,
        "after_seconds": args.after_seconds,
        "events": results,
    }

    output = args.output or args.transcript.with_suffix(".correlation.json")
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"Voice events correlated: {len(results)}")
    for event in results:
        print(f"\n[{event['audio_start_seconds']:.3f}] {event['text']}")
        for rank, candidate in enumerate(event["candidates"], start=1):
            print(
                f"  {rank:>2}. {candidate['interface']} {candidate['can_id_hex']} "
                f"byte {candidate['byte_index']}: {candidate['score']:.2f}"
            )
    print(f"Correlation report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
