#!/usr/bin/env python3
"""Build passive unknown-module discovery reports from GDS2 bench JSONL logs."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from gds2_bench_simulator import DEFAULT_REGISTRY_PATH, load_module_registry, parse_single_frame


def _timestamp(record: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(record["timestamp"]).replace("Z", "+00:00"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from error
            if not isinstance(row, dict) or "timestamp" not in row:
                raise ValueError(f"{path}:{line_number}: expected timestamped JSON object")
            records.append(row)
    return records


def append_marker(path: Path, label: str) -> dict[str, Any]:
    label = label.strip()
    if not label:
        raise ValueError("marker label must not be empty")
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "direction": "marker",
        "label": label,
        "source": "operator",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
    return record


def candidate_response_id(request_id: int) -> str | None:
    # Legacy GMLAN normal-addressing convention. This is a lead, never proof.
    if 0x200 <= request_id <= 0x2FF:
        return f"0x{request_id + 0x400:03X}"
    return None


def build_report(
    records: Iterable[dict[str, Any]],
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    rows = sorted(records, key=_timestamp)
    registry = load_module_registry(registry_path)
    known_requests = {profile.request_id: profile for profile in registry.values()}
    markers = [row for row in rows if row.get("direction") == "marker"]
    by_id: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        if row.get("direction") != "rx" or "canId" not in row:
            continue
        can_id = int(str(row["canId"]), 0)
        profile = known_requests.get(can_id)
        if profile is not None and profile.implemented:
            continue
        by_id[can_id].append(row)

    modules = []
    for can_id, observations in sorted(by_id.items()):
        services: Counter[str] = Counter()
        sequences = []
        for row in observations:
            raw = bytes.fromhex(str(row.get("data", "")))
            payload = parse_single_frame(raw)
            payload_hex = None if payload is None else payload.hex().upper()
            service = "unsupportedTransport" if not payload else f"0x{payload[0]:02X}"
            services[service] += 1
            sequences.append({"timestamp": row["timestamp"], "request": payload_hex})

        first = _timestamp(observations[0])
        last = _timestamp(observations[-1])
        nearby_markers = []
        for marker in markers:
            delta = (_timestamp(marker) - first).total_seconds()
            if -5.0 <= delta <= (last - first).total_seconds() + 5.0:
                nearby_markers.append({
                    "timestamp": marker["timestamp"],
                    "label": marker.get("label", ""),
                })

        profile = known_requests.get(can_id)
        modules.append({
            "requestCanId": f"0x{can_id:03X}",
            "registryKey": None if profile is None else profile.key,
            "registryStatus": "unregistered" if profile is None else profile.simulation_status,
            "observationCount": len(observations),
            "firstTimestamp": observations[0]["timestamp"],
            "lastTimestamp": observations[-1]["timestamp"],
            "durationSeconds": round((last - first).total_seconds(), 6),
            "services": dict(sorted(services.items())),
            "requestSequence": sequences,
            "nearbyMarkers": nearby_markers,
            "candidateNormalResponseCanId": candidate_response_id(can_id),
            "candidateBasis": "legacyGmlanPlus0x400" if candidate_response_id(can_id) else None,
            "candidateConfidence": "hypothesisOnly" if candidate_response_id(can_id) else None,
            "transmitAuthorized": False,
        })

    return {
        "schema": "obd-atlas.gds2-unknown-module-discovery.v1",
        "passiveOnly": True,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "markerCount": len(markers),
        "unknownModuleCount": len(modules),
        "modules": modules,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    marker = subparsers.add_parser("mark", help="append an operator marker")
    marker.add_argument("log", type=Path)
    marker.add_argument("label")

    report = subparsers.add_parser("report", help="build a passive discovery report")
    report.add_argument("log", type=Path)
    report.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    report.add_argument("--output", type=Path)

    args = parser.parse_args(argv)
    if args.command == "mark":
        print(json.dumps(append_marker(args.log, args.label), sort_keys=True))
        return 0

    result = build_report(read_jsonl(args.log), registry_path=args.registry)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
