#!/usr/bin/env python3
"""Decode the real-car Gen-1 Volt HPCM2 0x430E contactor state stream.

This is an observation-only decoder. It does not transmit diagnostic traffic.

Controlled 2013 Chevrolet Volt + GDS2 captures on 2026-09-14 established that
GDS2 defines dynamic packet 0xFE from HPCM2 parameter 0x430E and receives the
packed state byte on CAN ID 0x5EC. The observed successful startup sequence is:

    0x68 -> 0x6A -> 0x6F -> 0x6B

The observed normal shutdown sequence is:

    0x6B -> 0x6A -> 0x68

Bit 2 is transient only during the observed precharge interval. Bits 0 and 1
are the two changing main-contactor bits, but this decoder intentionally does
not assign positive-vs-negative names until an independent controlled test
separates them.

DPID 0xFE is reusable. Samples are decoded only after the capture itself shows
a successful 0x2C definition of 0xFE -> 0x430E on the same Atlas channel.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

HPCM2_REQUEST_ID = 0x7E4
HPCM2_RESPONSE_ID = 0x7EC
HPCM2_DYNAMIC_RESPONSE_ID = 0x5EC
CONTACTOR_DID = 0x430E
CONTACTOR_DPID = 0xFE

CANDUMP_RE = re.compile(
    r"^\((?P<ts>\d+(?:\.\d+)?)\)\s+"
    r"(?P<channel>\S+)\s+"
    r"(?P<canid>[0-9A-Fa-f]+)#(?P<data>[0-9A-Fa-f]*)\s*$"
)
MARKER_RE = re.compile(
    r"^# ATLAS_EVENT \((?P<ts>\d+(?:\.\d+)?)\).*?\blabel=(?P<label>.*)$"
)

STATE_MAP = {
    0x68: {
        "phase": "hvOff",
        "mainContactorBit0": False,
        "mainContactorBit1": False,
        "prechargeBit2": False,
    },
    0x6A: {
        "phase": "firstMainContactorEngaged",
        "mainContactorBit0": False,
        "mainContactorBit1": True,
        "prechargeBit2": False,
    },
    0x6F: {
        "phase": "prechargeActive",
        "mainContactorBit0": True,
        "mainContactorBit1": True,
        "prechargeBit2": True,
    },
    0x6B: {
        "phase": "hvBusEstablished",
        "mainContactorBit0": True,
        "mainContactorBit1": True,
        "prechargeBit2": False,
    },
}


@dataclass(frozen=True)
class Sample:
    timestamp: float
    channel: str
    raw_state: int


@dataclass(frozen=True)
class Marker:
    timestamp: float
    label: str


def decode_state(raw_state: int) -> dict[str, object]:
    known = STATE_MAP.get(raw_state)
    result: dict[str, object] = {
        "raw": raw_state,
        "rawHex": f"0x{raw_state:02X}",
        "binary": f"{raw_state:08b}",
        "known": known is not None,
    }
    if known is None:
        result.update(
            {
                "phase": "unknown",
                "mainContactorBit0": bool(raw_state & 0x01),
                "mainContactorBit1": bool(raw_state & 0x02),
                "prechargeBit2": bool(raw_state & 0x04),
            }
        )
    else:
        result.update(known)
    return result


def _single_frame_payload(data: bytes) -> bytes | None:
    if not data or (data[0] >> 4) != 0:
        return None
    length = data[0] & 0x0F
    if length == 0 or length > 7 or len(data) < length + 1:
        return None
    return data[1 : 1 + length]


def parse(lines: Iterable[str]) -> tuple[list[Sample], list[Marker]]:
    samples: list[Sample] = []
    markers: list[Marker] = []
    pending_definitions: dict[str, tuple[int, int]] = {}
    confirmed_definitions: dict[str, dict[int, int]] = {}

    for line in lines:
        stripped = line.strip()
        marker = MARKER_RE.match(stripped)
        if marker:
            markers.append(
                Marker(
                    timestamp=float(marker.group("ts")),
                    label=marker.group("label"),
                )
            )
            continue

        match = CANDUMP_RE.match(stripped)
        if not match:
            continue
        channel = match.group("channel")
        can_id = int(match.group("canid"), 16)
        raw = match.group("data")
        if len(raw) % 2:
            continue
        try:
            data = bytes.fromhex(raw)
        except ValueError:
            continue

        if can_id == HPCM2_REQUEST_ID:
            payload = _single_frame_payload(data)
            if payload is not None and len(payload) >= 4 and payload[0] == 0x2C:
                dpid = payload[1]
                did = (payload[2] << 8) | payload[3]
                pending_definitions[channel] = (dpid, did)
            continue

        if can_id == HPCM2_RESPONSE_ID:
            payload = _single_frame_payload(data)
            pending = pending_definitions.get(channel)
            if payload is None or pending is None:
                continue
            if len(payload) >= 2 and payload[0] == 0x6C and payload[1] == pending[0]:
                confirmed_definitions.setdefault(channel, {})[pending[0]] = pending[1]
                pending_definitions.pop(channel, None)
            elif len(payload) >= 3 and payload[0] == 0x7F and payload[1] == 0x2C:
                pending_definitions.pop(channel, None)
            continue

        if can_id != HPCM2_DYNAMIC_RESPONSE_ID or len(data) < 2:
            continue
        dpid = data[0]
        if confirmed_definitions.get(channel, {}).get(dpid) != CONTACTOR_DID:
            continue
        samples.append(
            Sample(
                timestamp=float(match.group("ts")),
                channel=channel,
                raw_state=data[1],
            )
        )

    samples.sort(key=lambda row: row.timestamp)
    markers.sort(key=lambda row: row.timestamp)
    return samples, markers


def compress_states(samples: Iterable[Sample]) -> list[Sample]:
    out: list[Sample] = []
    last: int | None = None
    for sample in samples:
        if sample.raw_state == last:
            continue
        out.append(sample)
        last = sample.raw_state
    return out


def classify_sequence(states: Iterable[int]) -> str:
    compressed: list[int] = []
    for state in states:
        if not compressed or compressed[-1] != state:
            compressed.append(state)

    if compressed == [0x68, 0x6A, 0x6F, 0x6B]:
        return "successfulStartup"
    if compressed == [0x6B, 0x6A, 0x68]:
        return "normalShutdown"
    if compressed == [0x68]:
        return "stableHvOff"
    if compressed == [0x6B]:
        return "stableHvEstablished"
    return "unknownOrIncomplete"


def _marker_window(samples: list[Sample], markers: list[Marker]) -> list[Sample]:
    starts = [m for m in markers if m.label.lower().endswith(" start")]
    ends = [m for m in markers if m.label.lower().endswith(" end")]
    if not starts or not ends:
        return samples
    start = starts[0].timestamp
    end = next((m.timestamp for m in ends if m.timestamp >= start), None)
    if end is None:
        return [s for s in samples if s.timestamp >= start]
    return [s for s in samples if start <= s.timestamp <= end]


def analyze(samples: list[Sample], markers: list[Marker]) -> dict[str, object]:
    selected = _marker_window(samples, markers)
    transitions = compress_states(selected)

    counts: dict[str, int] = {}
    for sample in selected:
        key = f"0x{sample.raw_state:02X}"
        counts[key] = counts.get(key, 0) + 1

    cadence_ms: dict[str, float] | None = None
    if len(selected) >= 2:
        intervals = [
            (b.timestamp - a.timestamp) * 1000.0
            for a, b in zip(selected, selected[1:])
            if b.timestamp >= a.timestamp
        ]
        if intervals:
            cadence_ms = {
                "median": round(statistics.median(intervals), 3),
                "mean": round(statistics.mean(intervals), 3),
                "min": round(min(intervals), 3),
                "max": round(max(intervals), 3),
            }

    t0 = selected[0].timestamp if selected else None
    return {
        "diagnosticContext": {
            "module": "K114B HPCM2",
            "did": "0x430E",
            "dynamicPacketId": "0xFE",
            "dynamicResponseCanId": "0x5EC",
            "contextRequirement": "confirmed 0x2C definition in same capture/channel",
        },
        "classification": classify_sequence(s.raw_state for s in transitions),
        "sampleCount": len(selected),
        "stateCounts": counts,
        "cadenceMs": cadence_ms,
        "transitions": [
            {
                "timestamp": round(sample.timestamp, 6),
                "secondsFromWindowStart": (
                    round(sample.timestamp - t0, 6) if t0 is not None else None
                ),
                **decode_state(sample.raw_state),
            }
            for sample in transitions
        ],
        "markers": [
            {"timestamp": round(marker.timestamp, 6), "label": marker.label}
            for marker in markers
        ],
        "evidenceBoundary": {
            "prechargeBit2": "vehicleObservedSequence",
            "mainContactorBits0And1": "vehicleObservedSequence",
            "positiveVsNegativeBitAssignment": "notIndependentlySeparated",
            "bits3_5_6": "notMappedByThisEvidence",
            "note": (
                "The state machine is vehicle-observed. Positive-vs-negative "
                "assignment for bits 0 and 1 remains intentionally unresolved."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    with args.capture.open("r", encoding="utf-8", errors="replace") as handle:
        samples, markers = parse(handle)
    result = analyze(samples, markers)
    result["capture"] = args.capture.name
    result["sha256"] = hashlib.sha256(args.capture.read_bytes()).hexdigest()

    rendered = json.dumps(result, indent=2) + "\n"
    if args.json_out:
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
