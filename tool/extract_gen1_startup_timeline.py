#!/usr/bin/env python3
"""Extract a conservative Gen-1 Volt startup timeline from an Atlas candump log.

This tool only decodes signals already supported by Atlas evidence/community
cross-checks. It deliberately does not infer individual contactor states.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

CANDUMP_RE = re.compile(
    r"^\((?P<ts>\d+(?:\.\d+)?)\)\s+"
    r"(?P<channel>\S+)\s+"
    r"(?P<canid>[0-9A-Fa-f]+)#(?P<data>[0-9A-Fa-f]*)\s*$"
)


@dataclass(frozen=True)
class Frame:
    timestamp: float
    channel: str
    can_id: int
    data: bytes


def parse_frames(lines: Iterable[str]) -> list[Frame]:
    frames: list[Frame] = []
    for line in lines:
        match = CANDUMP_RE.match(line.strip())
        if not match:
            continue
        raw = match.group("data")
        if len(raw) % 2:
            continue
        try:
            data = bytes.fromhex(raw)
        except ValueError:
            continue
        frames.append(
            Frame(
                timestamp=float(match.group("ts")),
                channel=match.group("channel"),
                can_id=int(match.group("canid"), 16),
                data=data,
            )
        )
    frames.sort(key=lambda frame: frame.timestamp)
    return frames


def dbc_motorola(payload: bytes, start_bit: int, length: int, signed: bool = False) -> int:
    """Decode a Vector/DBC Motorola signal from a classic CAN payload."""
    if length <= 0:
        raise ValueError("length must be positive")
    bit = start_bit
    value = 0
    for _ in range(length):
        byte_index = bit // 8
        bit_index = bit % 8
        if byte_index >= len(payload):
            raise ValueError("signal exceeds payload")
        value = (value << 1) | ((payload[byte_index] >> bit_index) & 1)
        bit = bit + 15 if bit_index == 0 else bit - 1
    if signed and value & (1 << (length - 1)):
        value -= 1 << length
    return value


def decode_0f1(payload: bytes) -> tuple[bool, int] | None:
    if len(payload) < 2:
        return None
    return bool(payload[0] & 0x02), payload[1]


def decode_1f1(payload: bytes) -> int | None:
    if not payload:
        return None
    return payload[0] & 0x03


def decode_2c7(payload: bytes) -> tuple[float, float] | None:
    if len(payload) < 5:
        return None
    current_raw = dbc_motorola(payload, 12, 13, signed=True)
    voltage_raw = dbc_motorola(payload, 31, 12, signed=False)
    return current_raw * 0.15, voltage_raw * 0.125


def _first_transition(samples: list[tuple[float, object]], predicate) -> tuple[float, object] | None:
    for timestamp, value in samples:
        if predicate(value):
            return timestamp, value
    return None


def analyze(frames: list[Frame]) -> dict[str, object]:
    if not frames:
        raise ValueError("capture contains no candump frames")
    t0 = frames[0].timestamp
    channels: dict[str, dict[str, object]] = {}
    channel_frames: dict[str, list[Frame]] = defaultdict(list)
    for frame in frames:
        channel_frames[frame.channel].append(frame)
    for channel, rows in sorted(channel_frames.items()):
        channels[channel] = {
            "firstSeconds": round(rows[0].timestamp - t0, 6),
            "lastSeconds": round(rows[-1].timestamp - t0, 6),
            "frames": len(rows),
        }

    brake_samples: list[tuple[float, tuple[bool, int]]] = []
    power_samples: list[tuple[float, int]] = []
    hv_samples: list[tuple[float, tuple[float, float]]] = []
    for frame in frames:
        relative = frame.timestamp - t0
        if frame.can_id == 0x0F1:
            decoded = decode_0f1(frame.data)
            if decoded is not None:
                brake_samples.append((relative, decoded))
        elif frame.can_id == 0x1F1:
            decoded = decode_1f1(frame.data)
            if decoded is not None:
                power_samples.append((relative, decoded))
        elif frame.can_id == 0x2C7:
            decoded = decode_2c7(frame.data)
            if decoded is not None:
                hv_samples.append((relative, decoded))

    brake_motion = _first_transition(brake_samples, lambda value: value[1] > 0)
    brake_pressed = _first_transition(brake_samples, lambda value: value[0])
    crank = _first_transition(power_samples, lambda value: value == 3)
    run = None
    if crank is not None:
        run = next(((ts, value) for ts, value in power_samples if ts > crank[0] and value == 2), None)

    hv_transient = None
    if crank is not None:
        hv_transient = next(
            (
                (ts, value)
                for ts, value in hv_samples
                if ts >= crank[0] and abs(value[0]) >= 2.0
            ),
            None,
        )

    timeline: list[dict[str, object]] = []
    if brake_motion:
        timeline.append({"seconds": round(brake_motion[0], 6), "event": "brakePedalMovementBegins", "rawPosition": brake_motion[1][1]})
    if brake_pressed:
        timeline.append({"seconds": round(brake_pressed[0], 6), "event": "brakePedalPressed"})
    if crank:
        timeline.append({"seconds": round(crank[0], 6), "event": "startRequest", "systemPowerMode": 3})
    if hv_transient:
        current, voltage = hv_transient[1]
        timeline.append(
            {
                "seconds": round(hv_transient[0], 6),
                "event": "hvCurrentTransient",
                "hvBatteryCurrentCandidateAmps": round(current, 3),
                "hvBatteryVoltageVolts": round(voltage, 3),
            }
        )
    if run:
        timeline.append({"seconds": round(run[0], 6), "event": "systemRun", "systemPowerMode": 2})
    timeline.sort(key=lambda row: float(row["seconds"]))

    intervals: dict[str, float] = {}
    if brake_motion and crank:
        intervals["brakeMovementToStartRequestMs"] = round((crank[0] - brake_motion[0]) * 1000, 3)
    if crank and hv_transient:
        intervals["startRequestToHvCurrentTransientMs"] = round((hv_transient[0] - crank[0]) * 1000, 3)
    if crank and run:
        intervals["startRequestToRunMs"] = round((run[0] - crank[0]) * 1000, 3)
    if hv_transient and run:
        intervals["hvCurrentTransientToRunMs"] = round((run[0] - hv_transient[0]) * 1000, 3)

    direct_hv_present_at_start = False
    if crank:
        # Current PCG-1 mapping uses can2/can3 for the two auxiliary HS networks.
        direct_hv_present_at_start = any(
            float(channels.get(channel, {}).get("lastSeconds", -1)) >= crank[0]
            for channel in ("can2", "can3")
        )

    return {
        "frameCount": len(frames),
        "durationSeconds": round(frames[-1].timestamp - t0, 6),
        "channelCoverage": channels,
        "timeline": timeline,
        "derivedIntervals": intervals,
        "evidenceBoundary": {
            "directAuxiliaryHsPresentAtStart": direct_hv_present_at_start,
            "individualContactorStateConfirmed": False,
            "note": (
                "Individual contactor/precharge states require direct-network evidence or a mapped diagnostic parameter; "
                "they are not inferred from the gatewayed battery voltage/current transient."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    with args.capture.open("r", encoding="utf-8", errors="replace") as handle:
        frames = parse_frames(handle)
    result = analyze(frames)
    result["capture"] = args.capture.name
    result["sha256"] = hashlib.sha256(args.capture.read_bytes()).hexdigest()

    if args.json_out:
        args.json_out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
