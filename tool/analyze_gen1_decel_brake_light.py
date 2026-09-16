#!/usr/bin/env python3
"""Offline analyzer for Gen-1 Volt deceleration brake-light research captures.

The tool is passive. It reads an Atlas candump-compatible capture, consumes
`# ATLAS_EVENT` markers, derives vehicle deceleration from the 0x3E9 speed
candidate, aligns already-known brake/gear/current candidates, ranks raw CAN
bytes that correlate with deceleration and L-vs-D lift behavior, and can replay
the software-only brake-light shadow logic when a regen-current polarity is
explicitly selected.

Nothing in this tool transmits CAN frames or commands vehicle lamps.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

CANDUMP_RE = re.compile(
    r"^\((?P<timestamp>[0-9.]+)\)\s+(?P<bus>\S+)\s+"
    r"(?P<id>[0-9A-Fa-f]+)#(?P<data>[0-9A-Fa-f]*)$"
)
EVENT_RE = re.compile(
    r"^# ATLAS_EVENT \((?P<timestamp>[0-9.]+)\).*?\slabel=(?P<label>.*)$"
)

SPEED_ID = 0x3E9
BRAKE_ID = 0x0F1
GEAR_ID = 0x1F5
ACCELERATOR_ID = 0x1C3
PACK_CURRENT_2C7_ID = 0x2C7
PACK_CURRENT_210_ID = 0x210

KNOWN_IDS = {
    BRAKE_ID: "brakePedal",
    0x0C9: "brakePressedEcm",
    0x1E9: "ebcmVehicleDynamic",
    0x0D1: "brakeNormalized1",
    0x214: "userBrakePressure",
    GEAR_ID: "gearSelector",
    ACCELERATOR_ID: "acceleratorPositionCandidate",
    SPEED_ID: "vehicleSpeedCandidate",
    PACK_CURRENT_2C7_ID: "hvBatteryCurrentCandidate",
    PACK_CURRENT_210_ID: "packCurrentCandidate",
}

EVENT_WINDOWS = {
    "baseline": ("DBL_00_BASELINE", "DBL_10_D_STEADY"),
    "dSteady": ("DBL_10_D_STEADY", "DBL_20_D_LIFT_START"),
    "dLift": ("DBL_20_D_LIFT_START", "DBL_21_D_LIFT_END"),
    "lLift": ("DBL_30_L_LIFT_START", "DBL_31_L_LIFT_END"),
    "lightBrake": ("DBL_40_LIGHT_BRAKE_START", "DBL_41_LIGHT_BRAKE_END"),
    "mediumBrake": ("DBL_50_MEDIUM_BRAKE_START", "DBL_51_MEDIUM_BRAKE_END"),
}

GEAR_NAMES = {0x01: "park", 0x02: "reverse", 0x03: "neutral", 0x04: "drive", 0x05: "low"}


@dataclass(frozen=True)
class Frame:
    timestamp: float
    bus: str
    can_id: int
    data: bytes


@dataclass(frozen=True)
class Event:
    timestamp: float
    label: str


@dataclass
class OnlineCorrelation:
    n: int = 0
    sum_x: float = 0.0
    sum_y: float = 0.0
    sum_xx: float = 0.0
    sum_yy: float = 0.0
    sum_xy: float = 0.0
    minimum: int = 255
    maximum: int = 0
    d_sum: float = 0.0
    d_n: int = 0
    l_sum: float = 0.0
    l_n: int = 0

    def add(self, x: int, y: float, event_name: str | None) -> None:
        self.n += 1
        self.sum_x += x
        self.sum_y += y
        self.sum_xx += x * x
        self.sum_yy += y * y
        self.sum_xy += x * y
        self.minimum = min(self.minimum, x)
        self.maximum = max(self.maximum, x)
        if event_name == "dLift":
            self.d_sum += x
            self.d_n += 1
        elif event_name == "lLift":
            self.l_sum += x
            self.l_n += 1

    def pearson(self) -> float:
        if self.n < 3:
            return 0.0
        numerator = self.n * self.sum_xy - self.sum_x * self.sum_y
        denom_x = self.n * self.sum_xx - self.sum_x * self.sum_x
        denom_y = self.n * self.sum_yy - self.sum_y * self.sum_y
        if denom_x <= 0 or denom_y <= 0:
            return 0.0
        return numerator / math.sqrt(denom_x * denom_y)


def parse_line(raw: str) -> Frame | Event | None:
    stripped = raw.strip()
    event = EVENT_RE.match(stripped)
    if event:
        return Event(float(event.group("timestamp")), event.group("label").strip())
    frame = CANDUMP_RE.match(stripped)
    if not frame:
        return None
    data_hex = frame.group("data")
    if len(data_hex) % 2:
        return None
    try:
        data = bytes.fromhex(data_hex)
    except ValueError:
        return None
    return Frame(
        timestamp=float(frame.group("timestamp")),
        bus=frame.group("bus"),
        can_id=int(frame.group("id"), 16),
        data=data,
    )


def iter_records(lines: Iterable[str]) -> Iterator[Frame | Event]:
    for raw in lines:
        parsed = parse_line(raw)
        if parsed is not None:
            yield parsed


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


def decode_speed_raw(frame: Frame) -> int | None:
    if frame.can_id != SPEED_ID or len(frame.data) < 2:
        return None
    return (frame.data[0] << 8) | frame.data[1]


def speed_from_raw(raw: int, mode: str) -> tuple[float, float]:
    if mode == "kph64":
        kph = raw / 64.0
        mps = kph / 3.6
        return mps, kph
    if mode == "mph01":
        mph = raw * 0.01
        mps = mph * 0.44704
        return mps, mps * 3.6
    raise ValueError(f"unsupported speed mode: {mode}")


def decode_brake(frame: Frame) -> bool | None:
    if frame.can_id != BRAKE_ID or len(frame.data) < 1:
        return None
    return bool(frame.data[0] & 0x02)


def decode_gear(frame: Frame) -> str | None:
    if frame.can_id != GEAR_ID or len(frame.data) < 4:
        return None
    return GEAR_NAMES.get(frame.data[3], f"raw_0x{frame.data[3]:02X}")


def decode_accelerator_raw(frame: Frame) -> int | None:
    if frame.can_id != ACCELERATOR_ID or len(frame.data) < 7:
        return None
    return frame.data[6]


def decode_pack_current_2c7(frame: Frame) -> float | None:
    if frame.can_id != PACK_CURRENT_2C7_ID or len(frame.data) < 4:
        return None
    try:
        return motorola(frame.data, 12, 13, signed=True) * 0.15
    except ValueError:
        return None


def decode_pack_current_210(frame: Frame) -> float | None:
    if frame.can_id != PACK_CURRENT_210_ID or len(frame.data) < 3:
        return None
    try:
        return motorola(frame.data, 23, 8, signed=True) * 0.1 - 0.1
    except ValueError:
        return None


def _median(values: Iterable[float | int]) -> float | None:
    seq = list(values)
    return float(statistics.median(seq)) if seq else None


def marker_map(events: list[Event]) -> dict[str, float]:
    result: dict[str, float] = {}
    for event in events:
        result.setdefault(event.label, event.timestamp)
    return result


def event_windows(events: list[Event]) -> dict[str, tuple[float, float]]:
    markers = marker_map(events)
    windows: dict[str, tuple[float, float]] = {}
    for name, (start_label, end_label) in EVENT_WINDOWS.items():
        start = markers.get(start_label)
        end = markers.get(end_label)
        if start is not None and end is not None and end > start:
            windows[name] = (start, end)
    return windows


def event_for_timestamp(timestamp: float, windows: dict[str, tuple[float, float]]) -> str | None:
    for name, (start, end) in windows.items():
        if start <= timestamp <= end:
            return name
    return None


def choose_speed_bus(speed_frames: list[Frame]) -> str | None:
    counts: dict[str, int] = {}
    for frame in speed_frames:
        counts[frame.bus] = counts.get(frame.bus, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def choose_speed_mode(
    speed_frames: list[Frame],
    events: list[Event],
    requested: str,
) -> tuple[str, dict]:
    if requested in {"kph64", "mph01"}:
        return requested, {"method": "explicit", "selected": requested}

    windows = event_windows(events)
    steady = windows.get("dSteady")
    diagnostics = {"method": "protocolFit", "selected": "kph64", "candidates": {}}
    if steady is None:
        diagnostics["method"] = "defaultWithoutSteadyMarker"
        return "kph64", diagnostics

    start, end = steady
    raw_values = [
        raw
        for frame in speed_frames
        if start <= frame.timestamp <= end
        if (raw := decode_speed_raw(frame)) is not None
    ]
    if not raw_values:
        diagnostics["method"] = "defaultNoSteadySamples"
        return "kph64", diagnostics

    raw_median = statistics.median(raw_values)
    expected_mid_mph = 27.5
    best = "kph64"
    best_error = float("inf")
    for mode in ("kph64", "mph01"):
        mps, _ = speed_from_raw(int(round(raw_median)), mode)
        mph = mps / 0.44704
        error = abs(mph - expected_mid_mph)
        diagnostics["candidates"][mode] = {
            "steadyMedianMph": round(mph, 4),
            "distanceFromProtocolMidpointMph": round(error, 4),
        }
        if error < best_error:
            best = mode
            best_error = error
    diagnostics["selected"] = best
    diagnostics["note"] = (
        "Protocol-fit selection is only a convenience for analysis; it is not independent speed validation."
    )
    return best, diagnostics


def linear_slope(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 3:
        return None
    t0 = points[len(points) // 2][0]
    xs = [t - t0 for t, _ in points]
    ys = [value for _, value in points]
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom <= 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom


def derive_motion(speed_frames: list[Frame], speed_mode: str) -> list[dict]:
    points: list[tuple[float, float, float, int, str]] = []
    for frame in speed_frames:
        raw = decode_speed_raw(frame)
        if raw is None:
            continue
        mps, kph = speed_from_raw(raw, speed_mode)
        points.append((frame.timestamp, mps, kph, raw, frame.bus))
    points.sort(key=lambda row: row[0])

    result: list[dict] = []
    times = [row[0] for row in points]
    for index, (timestamp, mps, kph, raw, bus) in enumerate(points):
        left = bisect.bisect_left(times, timestamp - 0.35)
        right = bisect.bisect_right(times, timestamp + 0.35)
        slope = linear_slope([(row[0], row[1]) for row in points[left:right]])
        decel = None if slope is None else max(0.0, -slope)
        result.append(
            {
                "timestamp": timestamp,
                "bus": bus,
                "speedRaw": raw,
                "vehicleSpeedMps": mps,
                "vehicleSpeedKph": kph,
                "decelerationMps2": decel,
            }
        )
    return result


def _latest_value(series: list[tuple[float, object]], timestamp: float, max_age: float = 0.30):
    if not series:
        return None
    times = [row[0] for row in series]
    index = bisect.bisect_right(times, timestamp) - 1
    if index < 0:
        return None
    sample_time, value = series[index]
    if timestamp - sample_time > max_age:
        return None
    return value


def collect_primary(lines: Iterable[str]) -> tuple[list[Frame], list[Event], dict[str, list[tuple[float, object]]]]:
    speed_frames: list[Frame] = []
    events: list[Event] = []
    series: dict[str, list[tuple[float, object]]] = {
        "brake": [],
        "gear": [],
        "accelerator": [],
        "current2c7": [],
        "current210": [],
    }
    for record in iter_records(lines):
        if isinstance(record, Event):
            events.append(record)
            continue
        if record.can_id == SPEED_ID:
            speed_frames.append(record)
        brake = decode_brake(record)
        if brake is not None:
            series["brake"].append((record.timestamp, brake))
        gear = decode_gear(record)
        if gear is not None:
            series["gear"].append((record.timestamp, gear))
        accelerator = decode_accelerator_raw(record)
        if accelerator is not None:
            series["accelerator"].append((record.timestamp, accelerator))
        current = decode_pack_current_2c7(record)
        if current is not None:
            series["current2c7"].append((record.timestamp, current))
        current = decode_pack_current_210(record)
        if current is not None:
            series["current210"].append((record.timestamp, current))
    speed_frames.sort(key=lambda frame: frame.timestamp)
    events.sort(key=lambda event: event.timestamp)
    for values in series.values():
        values.sort(key=lambda row: row[0])
    return speed_frames, events, series


def align_timeline(
    motion: list[dict],
    series: dict[str, list[tuple[float, object]]],
    windows: dict[str, tuple[float, float]],
    regen_source: str,
    regen_threshold_a: float,
) -> list[dict]:
    requested = False
    timeline: list[dict] = []
    for row in motion:
        timestamp = row["timestamp"]
        brake = _latest_value(series["brake"], timestamp)
        gear = _latest_value(series["gear"], timestamp)
        accelerator = _latest_value(series["accelerator"], timestamp)
        current2c7 = _latest_value(series["current2c7"], timestamp)
        current210 = _latest_value(series["current210"], timestamp)
        decel = row["decelerationMps2"]
        speed = row["vehicleSpeedMps"]

        regen: bool | None = None
        if regen_source != "none":
            source_name, polarity = regen_source.rsplit("-", 1)
            current = current2c7 if source_name == "2c7" else current210
            if current is not None:
                regen = current >= regen_threshold_a if polarity == "positive" else current <= -regen_threshold_a

        shadow: bool | None = None
        reason = "regenSourceNotConfigured" if regen_source == "none" else "invalidInput"
        if regen_source != "none" and regen is not None and decel is not None:
            if brake is True:
                requested = False
                shadow = False
                reason = "factoryBrakeApplied"
            elif speed < 1.4:
                requested = False
                shadow = False
                reason = "belowMinimumSpeed"
            elif not regen:
                requested = False
                shadow = False
                reason = "regenNotConfirmed"
            elif requested:
                if decel < 0.7:
                    requested = False
                    shadow = False
                    reason = "belowThreshold"
                else:
                    shadow = True
                    reason = "hysteresisHold"
            elif decel >= 1.3:
                requested = True
                shadow = True
                reason = "regenDeceleration"
            else:
                shadow = False
                reason = "belowThreshold"

        timeline.append(
            {
                **row,
                "event": event_for_timestamp(timestamp, windows),
                "factoryBrakeApplied": brake,
                "gear": gear,
                "acceleratorRaw": accelerator,
                "packCurrent2c7CandidateA": current2c7,
                "packCurrent210CandidateA": current210,
                "regenConfirmedByConfiguredCandidate": regen,
                "decelThresholdOnly": bool(decel is not None and decel >= 1.3),
                "regenBrakeLightRequest": shadow,
                "shadowReason": reason,
            }
        )
    return timeline


def summarize_events(timeline: list[dict], windows: dict[str, tuple[float, float]]) -> dict:
    summary: dict[str, dict] = {}
    for name in windows:
        rows = [row for row in timeline if row["event"] == name]
        if not rows:
            continue
        decels = [row["decelerationMps2"] for row in rows if row["decelerationMps2"] is not None]
        speeds = [row["vehicleSpeedKph"] for row in rows]
        currents2c7 = [row["packCurrent2c7CandidateA"] for row in rows if row["packCurrent2c7CandidateA"] is not None]
        currents210 = [row["packCurrent210CandidateA"] for row in rows if row["packCurrent210CandidateA"] is not None]
        brakes = [row["factoryBrakeApplied"] for row in rows if row["factoryBrakeApplied"] is not None]
        gears = [row["gear"] for row in rows if row["gear"] is not None]
        summary[name] = {
            "samples": len(rows),
            "medianSpeedKph": _median(speeds),
            "medianDecelerationMps2": _median(decels),
            "maxDecelerationMps2": max(decels) if decels else None,
            "brakeAppliedFraction": (sum(bool(value) for value in brakes) / len(brakes)) if brakes else None,
            "medianPackCurrent2c7CandidateA": _median(currents2c7),
            "medianPackCurrent210CandidateA": _median(currents210),
            "observedGears": sorted(set(gears)),
        }
    return summary


def infer_current_polarity(event_summary: dict, field: str) -> dict:
    steady = event_summary.get("dSteady", {}).get(field)
    l_lift = event_summary.get("lLift", {}).get(field)
    d_lift = event_summary.get("dLift", {}).get(field)
    if steady is None or l_lift is None:
        return {"status": "insufficientData"}
    delta = l_lift - steady
    return {
        "status": "candidateOnly",
        "lLiftMinusDSteadyA": round(delta, 4),
        "dLiftMinusDSteadyA": None if d_lift is None else round(d_lift - steady, 4),
        "candidatePolarityDuringLLift": "positive" if delta > 0 else "negative" if delta < 0 else "noChange",
        "note": "This is event correlation only and must not be treated as validated regen polarity by itself.",
    }


def nearest_motion(motion_times: list[float], motion: list[dict], timestamp: float, max_delta: float = 0.15) -> dict | None:
    index = bisect.bisect_left(motion_times, timestamp)
    choices = []
    if index < len(motion):
        choices.append(motion[index])
    if index > 0:
        choices.append(motion[index - 1])
    if not choices:
        return None
    best = min(choices, key=lambda row: abs(row["timestamp"] - timestamp))
    return best if abs(best["timestamp"] - timestamp) <= max_delta else None


def rank_candidate_bytes(
    capture: Path,
    timeline: list[dict],
    windows: dict[str, tuple[float, float]],
    limit: int,
) -> list[dict]:
    motion = [row for row in timeline if row["decelerationMps2"] is not None]
    motion_times = [row["timestamp"] for row in motion]
    stats: dict[tuple[str, int, int], OnlineCorrelation] = {}
    if not motion:
        return []

    with capture.open("r", encoding="utf-8", errors="replace") as handle:
        for record in iter_records(handle):
            if not isinstance(record, Frame):
                continue
            aligned = nearest_motion(motion_times, motion, record.timestamp)
            if aligned is None:
                continue
            decel = aligned["decelerationMps2"]
            event_name = event_for_timestamp(record.timestamp, windows)
            for byte_index, value in enumerate(record.data):
                key = (record.bus, record.can_id, byte_index)
                stats.setdefault(key, OnlineCorrelation()).add(value, decel, event_name)

    ranked = []
    for (bus, can_id, byte_index), item in stats.items():
        dynamic_range = item.maximum - item.minimum
        if item.n < 20 or dynamic_range < 2:
            continue
        corr = item.pearson()
        d_mean = item.d_sum / item.d_n if item.d_n else None
        l_mean = item.l_sum / item.l_n if item.l_n else None
        contrast = 0.0
        if d_mean is not None and l_mean is not None and dynamic_range:
            contrast = abs(l_mean - d_mean) / dynamic_range
        score = abs(corr) + min(1.0, contrast)
        ranked.append(
            {
                "bus": bus,
                "canId": f"0x{can_id:X}",
                "byteIndex": byte_index,
                "knownMessage": KNOWN_IDS.get(can_id),
                "samples": item.n,
                "range": [item.minimum, item.maximum],
                "pearsonVsDerivedDeceleration": round(corr, 5),
                "dLiftMeanRaw": None if d_mean is None else round(d_mean, 4),
                "lLiftMeanRaw": None if l_mean is None else round(l_mean, 4),
                "normalizedLLiftVsDLiftContrast": round(contrast, 5),
                "score": round(score, 5),
            }
        )
    ranked.sort(key=lambda row: row["score"], reverse=True)
    return ranked[:limit]


def write_csv(path: Path, timeline: list[dict]) -> None:
    fields = [
        "timestamp",
        "event",
        "vehicleSpeedKph",
        "vehicleSpeedMps",
        "decelerationMps2",
        "factoryBrakeApplied",
        "gear",
        "acceleratorRaw",
        "packCurrent2c7CandidateA",
        "packCurrent210CandidateA",
        "regenConfirmedByConfiguredCandidate",
        "decelThresholdOnly",
        "regenBrakeLightRequest",
        "shadowReason",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(timeline)


def analyze_capture(
    capture: Path,
    *,
    speed_mode: str = "auto",
    regen_source: str = "none",
    regen_threshold_a: float = 1.0,
    top_candidates: int = 40,
) -> dict:
    with capture.open("r", encoding="utf-8", errors="replace") as handle:
        speed_frames, events, series = collect_primary(handle)

    selected_bus = choose_speed_bus(speed_frames)
    if selected_bus is not None:
        speed_frames = [frame for frame in speed_frames if frame.bus == selected_bus]
    selected_mode, speed_diagnostics = choose_speed_mode(speed_frames, events, speed_mode)
    windows = event_windows(events)
    motion = derive_motion(speed_frames, selected_mode)
    timeline = align_timeline(motion, series, windows, regen_source, regen_threshold_a)
    event_summary = summarize_events(timeline, windows)
    candidates = rank_candidate_bytes(capture, timeline, windows, top_candidates)

    return {
        "schemaVersion": 1,
        "tool": "analyze_gen1_decel_brake_light",
        "safetyBoundary": "offline analysis only; no CAN transmit and no lamp actuation",
        "capture": str(capture),
        "markers": [{"timestamp": event.timestamp, "label": event.label} for event in events],
        "detectedWindows": {name: [start, end] for name, (start, end) in windows.items()},
        "speed": {
            "canId": "0x3E9",
            "selectedBus": selected_bus,
            "selectedDecode": selected_mode,
            "diagnostics": speed_diagnostics,
            "sampleCount": len(motion),
        },
        "shadowReplay": {
            "regenSource": regen_source,
            "regenThresholdA": regen_threshold_a,
            "engageDecelerationMps2": 1.3,
            "releaseDecelerationMps2": 0.7,
            "minimumVehicleSpeedMps": 1.4,
            "note": (
                "regenBrakeLightRequest remains null unless a regen-current source and polarity are explicitly configured; "
                "candidate current polarity is not silently promoted to confirmed regen."
            ),
        },
        "eventSummary": event_summary,
        "regenCurrentCorrelation": {
            "0x2C7": infer_current_polarity(event_summary, "medianPackCurrent2c7CandidateA"),
            "0x210": infer_current_polarity(event_summary, "medianPackCurrent210CandidateA"),
        },
        "candidateBytes": candidates,
        "timeline": timeline,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="Atlas/candump capture containing DBL markers")
    parser.add_argument("--json-out", type=Path, help="write the complete analysis report as JSON")
    parser.add_argument("--csv-out", type=Path, help="write the aligned motion/signal timeline as CSV")
    parser.add_argument(
        "--speed-decode",
        choices=("auto", "kph64", "mph01"),
        default="auto",
        help="0x3E9 candidate scaling; auto uses the 25-30 mph dSteady protocol window when available",
    )
    parser.add_argument(
        "--regen-source",
        choices=("none", "2c7-positive", "2c7-negative", "210-positive", "210-negative"),
        default="none",
        help="explicit candidate current/polarity for shadow replay; default keeps shadow output unasserted",
    )
    parser.add_argument("--regen-threshold-a", type=float, default=1.0)
    parser.add_argument("--top-candidates", type=int, default=40)
    args = parser.parse_args()

    report = analyze_capture(
        args.capture,
        speed_mode=args.speed_decode,
        regen_source=args.regen_source,
        regen_threshold_a=max(0.0, args.regen_threshold_a),
        top_candidates=max(1, args.top_candidates),
    )
    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    else:
        compact = {key: value for key, value in report.items() if key != "timeline"}
        print(json.dumps(compact, indent=2))
    if args.csv_out:
        write_csv(args.csv_out, report["timeline"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
