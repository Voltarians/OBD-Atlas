#!/usr/bin/env python3
"""Extract a provenance-preserving GM diagnostic reference map from Simulation.txt-style transcripts.

The input format is an annotated legacy GM diagnostic transcript, not a vehicle
capture. Atlas therefore emits `legacyReference` evidence only. The tool does
not transmit, derive security keys, or claim that any address is valid for a
specific Volt until independently observed.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REQUEST_SERVICES = {
    0x04: "ClearDiagnosticInformationLegacy",
    0x09: "RequestVehicleInformation",
    0x10: "DiagnosticSessionControl",
    0x11: "ECUReset",
    0x12: "GMFailureRecord",
    0x18: "ReadDTCInformationLegacy",
    0x22: "ReadDataByIdentifier",
    0x27: "SecurityAccess",
    0x2C: "DynamicallyDefineDataIdentifier",
    0x2E: "WriteDataByIdentifier",
    0x31: "RoutineControl",
    0x32: "GMService32",
    0x33: "GMService33",
    0x34: "RequestDownload",
    0x35: "RequestUpload",
    0x36: "TransferData",
    0x37: "RequestTransferExit",
    0x3E: "TesterPresent",
    0xA0: "GMLegacyServiceA0",
    0xA1: "GMLegacyServiceA1",
    0xA9: "GMReadDTCInformation",
    0xAA: "GMDynamicDataPacketControl",
}

POSITIVE_SERVICES = {((service + 0x40) & 0xFF): service for service in REQUEST_SERVICES}

KNOWN_MODULE_HEADINGS = (
    (re.compile(r"\bInflatable Restraint Sensing and Diagnostic Module\b", re.I), "Inflatable Restraint Sensing and Diagnostic Module"),
    (re.compile(r"\bElectronic Power Steering Control Module\b", re.I), "Electronic Power Steering Control Module"),
    (re.compile(r"\bElectronic Power Steering COntrol Module\b", re.I), "Electronic Power Steering Control Module"),
    (re.compile(r"\bElectronic Brake Control Module\b", re.I), "Electronic Brake Control Module"),
    (re.compile(r"\bElectronic Brake COntrol Module\b", re.I), "Electronic Brake Control Module"),
    (re.compile(r"\bImmobilizer Control Module\b", re.I), "Immobilizer Control Module"),
    (re.compile(r"\bKeyless Entry Control Module\b", re.I), "Keyless Entry Control Module"),
    (re.compile(r"\bInstrument Cluster\b", re.I), "Instrument Cluster"),
    (re.compile(r"\bFuel Pump Module\b", re.I), "Fuel Pump Module"),
    (re.compile(r"\bRadio\b", re.I), "Radio"),
    (re.compile(r"\bECM\b", re.I), "ECM"),
    (re.compile(r"\bTCM\b", re.I), "TCM"),
    (re.compile(r"\bBCM\b", re.I), "BCM"),
)


@dataclass(frozen=True)
class ReferenceFrame:
    line_number: int
    section: str | None
    module: str | None
    ordinal: int
    delay_ms: int | None
    can_id: int
    data: tuple[int, ...]


def _number(token: str) -> int:
    token = token.strip().rstrip(",")
    if token.lower().startswith("0x"):
        return int(token, 16)
    return int(token, 10)


def module_from_heading(heading: str) -> str | None:
    text = heading.strip()
    if not text or text.lower().startswith("original"):
        return None
    for pattern, canonical in KNOWN_MODULE_HEADINGS:
        if pattern.search(text):
            return canonical
    return None


def parse(lines: Iterable[str]) -> list[ReferenceFrame]:
    frames: list[ReferenceFrame] = []
    section: str | None = None
    module: str | None = None

    for line_number, raw in enumerate(lines, 1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith(";"):
            heading = stripped[1:].strip()
            if not heading:
                continue
            if re.match(r"^(?:Original\s*-\s*)?\d+\s", heading, flags=re.IGNORECASE):
                continue
            section = heading
            candidate = module_from_heading(heading)
            if candidate is not None:
                module = candidate
            continue

        tokens = stripped.split()
        if len(tokens) < 3:
            continue
        try:
            ordinal = _number(tokens[0])
        except ValueError:
            continue

        cursor = 1
        delay_ms: int | None = None
        try:
            if tokens[cursor].lower().startswith("0x"):
                can_id = _number(tokens[cursor])
                cursor += 1
            else:
                delay_ms = _number(tokens[cursor])
                cursor += 1
                can_id = _number(tokens[cursor])
                cursor += 1
            payload = tuple(_number(token) & 0xFF for token in tokens[cursor:])
        except (ValueError, IndexError):
            continue

        frames.append(
            ReferenceFrame(
                line_number=line_number,
                section=section,
                module=module,
                ordinal=ordinal,
                delay_ms=delay_ms,
                can_id=can_id,
                data=payload,
            )
        )
    return frames


def _service(frame: ReferenceFrame) -> tuple[str, int | None, str | None]:
    if not frame.data:
        return "empty", None, None
    sid = frame.data[0]
    if sid in REQUEST_SERVICES:
        return "request", sid, REQUEST_SERVICES[sid]
    if sid == 0x7F:
        requested = frame.data[1] if len(frame.data) > 1 else None
        return "negativeResponse", requested, REQUEST_SERVICES.get(requested)
    if sid in POSITIVE_SERVICES:
        requested = POSITIVE_SERVICES[sid]
        return "positiveResponse", requested, REQUEST_SERVICES.get(requested)
    return "data", None, None


def analyze(frames: list[ReferenceFrame]) -> dict:
    modules: dict[str, dict] = {}
    services = defaultdict(int)
    uncategorized = 0

    for frame in frames:
        direction, service, service_name = _service(frame)
        if service is not None:
            services[f"0x{service:02X} {service_name or 'unknown'}"] += 1
        if frame.module is None:
            uncategorized += 1
            continue

        entry = modules.setdefault(
            frame.module,
            {
                "module": frame.module,
                "confidence": "legacyReference",
                "requestCanIds": set(),
                "normalResponseCanIds": set(),
                "dataCanIds": set(),
                "functionalRequestCanIds": set(),
                "services": set(),
                "sections": set(),
            },
        )
        if frame.section:
            entry["sections"].add(frame.section)
        if service is not None:
            entry["services"].add(f"0x{service:02X}")

        if direction == "request":
            if frame.can_id == 0x7DF:
                entry["functionalRequestCanIds"].add(frame.can_id)
            else:
                entry["requestCanIds"].add(frame.can_id)
        elif direction in {"positiveResponse", "negativeResponse"}:
            entry["normalResponseCanIds"].add(frame.can_id)
        elif 0x500 <= frame.can_id <= 0x5FF:
            entry["dataCanIds"].add(frame.can_id)
        elif 0x600 <= frame.can_id <= 0x7FF:
            entry["normalResponseCanIds"].add(frame.can_id)

    output_modules = []
    for entry in modules.values():
        output_modules.append(
            {
                "module": entry["module"],
                "confidence": entry["confidence"],
                "requestCanIds": [f"0x{x:03X}" for x in sorted(entry["requestCanIds"])],
                "normalResponseCanIds": [f"0x{x:03X}" for x in sorted(entry["normalResponseCanIds"])],
                "dataCanIds": [f"0x{x:03X}" for x in sorted(entry["dataCanIds"])],
                "functionalRequestCanIds": [f"0x{x:03X}" for x in sorted(entry["functionalRequestCanIds"])],
                "services": sorted(entry["services"]),
                "sections": sorted(entry["sections"]),
            }
        )
    output_modules.sort(key=lambda row: row["module"])

    return {
        "schemaVersion": 1,
        "evidenceClass": "legacyReference",
        "sourceType": "annotated GM diagnostic simulation/reference transcript",
        "warning": "Addresses and services are reference evidence only; do not promote them to vehicle-confirmed mappings without a controlled capture or stronger provenance.",
        "frameCount": len(frames),
        "uncategorizedFrames": uncategorized,
        "serviceHistogram": dict(sorted(services.items())),
        "modules": output_modules,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    with args.transcript.open("r", encoding="utf-8", errors="replace") as handle:
        result = analyze(parse(handle))
    rendered = json.dumps(result, indent=2) + "\n"
    if args.json_out:
        args.json_out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
