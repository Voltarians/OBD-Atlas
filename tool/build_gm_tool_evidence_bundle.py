#!/usr/bin/env python3
"""Build a provenance-preserving GM tool evidence bundle.

This tool is offline and observation-only. It correlates existing Atlas candump
captures, J2534 proxy traces, GDS2 DID/dynamic-packet extraction, and operator
markers. It never loads a J2534 provider, opens an adapter, transmits traffic, or
promotes a diagnostic/signaling definition to confirmed status.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import extract_gds2_dids as gds2
import extract_gm_tool_session as gm
import j2534_trace as jtrace

SCHEMA_ID = "obd-atlas.gm-tool-evidence-bundle.v1"
ATLAS_EVENT_RE = re.compile(
    r"^# ATLAS_EVENT \((?P<epoch>\d+(?:\.\d+)?)\)\s+"
    r"(?P<utc>\S+)\s+source=(?P<source>\S+)\s+label=(?P<label>.*)$"
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_to_epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def input_record(path: Path, role: str) -> dict[str, Any]:
    return {
        "role": role,
        "path": str(path),
        "sizeBytes": path.stat().st_size,
        "sha256": sha256_path(path),
    }


def parse_atlas_markers(lines: Iterable[str]) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for line in lines:
        match = ATLAS_EVENT_RE.match(line.strip())
        if not match:
            continue
        markers.append(
            {
                "timestamp": float(match.group("epoch")),
                "utc": match.group("utc"),
                "source": match.group("source"),
                "label": match.group("label"),
                "evidenceClass": "operatorMarker",
            }
        )
    markers.sort(key=lambda row: float(row["timestamp"]))
    return markers


def load_voice_markers(path: Path) -> list[dict[str, Any]]:
    root = json.loads(path.read_text(encoding="utf-8"))
    if root.get("schema") != "obd-atlas.voice-event-correlation.v1":
        raise ValueError(f"unsupported voice-correlation schema: {path}")
    calibrated = bool(root.get("input_latency_calibrated", False))
    markers = []
    for event in root.get("events", []):
        start = float(event["can_window_start_epoch_seconds"])
        end = float(event["can_window_end_epoch_seconds"])
        markers.append(
            {
                "timestamp": start,
                "windowEndTimestamp": end,
                "source": "voice",
                "label": str(event.get("text", "")),
                "evidenceClass": "voiceSupportingEvidenceOnly",
                "inputLatencyCalibrated": calibrated,
                "voiceAnnotationIndex": event.get("annotation_index"),
            }
        )
    return markers


def _default_address_references() -> tuple[list[dict[str, Any]], dict[int, list[dict[str, str]]]]:
    references: list[dict[str, Any]] = []
    for path in gm.DEFAULT_ADDRESS_REFERENCES:
        reference = gm.load_address_reference(path)
        if reference is not None:
            references.append(reference)
    return references, gm.build_address_index(references)


def analyze_capture(path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    markers = parse_atlas_markers(lines)

    frames = list(gm.parse_frames(lines))
    messages = list(gm.reassemble_isotp(frames))
    references, address_index = _default_address_references()
    iso_events = gm.extract_diagnostic_events(messages)
    legacy_events = gm.extract_legacy_reference_events(frames, address_index, iso_events)
    events = gm.merge_events(iso_events, legacy_events)
    gm.annotate_events(events, address_index)
    endpoint_traffic = gm.build_endpoint_traffic(frames, address_index)
    transactions = gm.build_transactions(events)

    # Match extract_gm_tool_session.py's safe default: keep programming phase
    # evidence while not duplicating TransferData firmware bytes in this bundle.
    for event in events:
        if event.get("service") == "TransferData" and "transferData" in event:
            event["transferData"] = "<redacted>"
            event["transferDataRedacted"] = True

    gm_result = {
        "frameCount": len(frames),
        "isoTpMessageCount": len(messages),
        "addressReferences": [
            {
                "catalogId": reference.get("catalogId"),
                "confidence": reference.get("confidence"),
            }
            for reference in references
        ],
        "summary": gm.build_summary(events, endpoint_traffic, transactions),
        "events": events,
        "endpointTraffic": endpoint_traffic,
        "transactions": transactions,
    }

    gds2_frames = list(gds2.parse_frames(lines))
    gds2_messages = list(gds2.reassemble_isotp(gds2_frames))
    did_transactions = gds2.extract_did_transactions(gds2_messages)
    dynamic_events = gds2.extract_dynamic_packet_sessions(gds2_frames, gds2_messages)
    gds2_result = {
        "physicalDidTransactions": did_transactions,
        "dynamicPacketEvents": dynamic_events,
    }
    return gm_result, gds2_result, markers


def analyze_j2534_trace(path: Path) -> dict[str, Any]:
    records = jtrace.read_trace(path)
    session = records[0]
    return {
        "session": {
            key: session.get(key)
            for key in (
                "sourceApplication",
                "sourceApplicationVersion",
                "observerMode",
                "proxyMayTransmitIndependently",
                "provider",
                "providerFingerprintSha256",
                "sensitivePayloadPolicy",
            )
        },
        "summary": jtrace.summarize_trace(records),
        "records": records,
    }


def _normalize_service(value: Any) -> str | None:
    if value is None:
        return None
    try:
        number = int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        return None
    return f"0x{number & 0xFF:02X}"


def _payload_candidates(message: dict[str, Any]) -> set[str]:
    if message.get("payloadRedacted"):
        return set()
    raw = message.get("payloadHex")
    if not isinstance(raw, str):
        return set()
    compact = "".join(raw.split()).upper()
    if len(compact) % 2:
        return set()
    candidates = {compact}
    # ISO15765 J2534 messages commonly prepend a four-byte CAN identifier to
    # the application payload. Keep both forms; do not assume either layout.
    if len(compact) > 8:
        candidates.add(compact[8:])
    return {candidate for candidate in candidates if candidate}


def j2534_message_events(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for record in records:
        messages = record.get("messages") or []
        if not isinstance(messages, list) or not messages:
            continue
        api = str(record.get("api", ""))
        record_type = str(record.get("recordType", ""))
        if api == "PassThruWriteMsgs" and record_type == "callBegin":
            direction = "applicationToProvider"
        elif api == "PassThruReadMsgs" and record_type == "callEnd":
            direction = "providerToApplication"
        elif api == "PassThruStartPeriodicMsg" and record_type == "callBegin":
            direction = "applicationToProviderPeriodic"
        else:
            direction = "other"
        timestamp = utc_to_epoch(str(record["utc"]))
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                continue
            output.append(
                {
                    "timestamp": timestamp,
                    "utc": record["utc"],
                    "monotonicNs": record.get("monotonicNs"),
                    "sequence": record.get("sequence"),
                    "callId": record.get("callId"),
                    "api": api,
                    "recordType": record_type,
                    "direction": direction,
                    "messageIndex": index,
                    "serviceId": _normalize_service(message.get("service")),
                    "message": message,
                }
            )
    output.sort(key=lambda row: (float(row["timestamp"]), int(row.get("sequence") or 0)))
    return output


def _bus_direction_matches(j_direction: str, bus_direction: str) -> bool:
    if j_direction in {"applicationToProvider", "applicationToProviderPeriodic"}:
        return bus_direction == "request"
    if j_direction == "providerToApplication":
        return bus_direction in {"positiveResponse", "negativeResponse"}
    return False


def correlate_j2534_to_bus(
    message_events: list[dict[str, Any]],
    bus_events: list[dict[str, Any]],
    *,
    max_delta_s: float,
) -> list[dict[str, Any]]:
    correlations: list[dict[str, Any]] = []
    for item in message_events:
        if item["direction"] == "other":
            continue
        timestamp = float(item["timestamp"])
        message = item["message"]
        candidates = _payload_candidates(message)
        service_id = item.get("serviceId")
        ranked: list[tuple[int, float, dict[str, Any], bool, bool]] = []
        for event in bus_events:
            if not _bus_direction_matches(str(item["direction"]), str(event.get("direction", ""))):
                continue
            delta = abs(float(event["timestamp"]) - timestamp)
            if delta > max_delta_s:
                continue
            bus_payload = str(event.get("payload", "")).upper()
            exact_payload = bool(bus_payload and any(candidate.endswith(bus_payload) for candidate in candidates))
            bus_service = str(event.get("serviceId", "")) or None
            service_match = bool(service_id and bus_service == service_id)
            score = (100 if exact_payload else 0) + (30 if service_match else 0) - int(delta * 1000)
            ranked.append((score, delta, event, exact_payload, service_match))
        ranked.sort(key=lambda row: (row[0], -row[1]), reverse=True)
        if not ranked:
            correlations.append(
                {
                    "callId": item.get("callId"),
                    "api": item["api"],
                    "messageIndex": item["messageIndex"],
                    "j2534Direction": item["direction"],
                    "j2534Timestamp": timestamp,
                    "serviceId": service_id,
                    "status": "noBusCandidateInWindow",
                }
            )
            continue
        _, delta, event, exact_payload, service_match = ranked[0]
        if exact_payload:
            status = "exactPayloadAndTimeMatch"
        elif service_match:
            status = "serviceAndTimeCandidate"
        else:
            status = "timeOnlyCandidate"
        correlations.append(
            {
                "callId": item.get("callId"),
                "api": item["api"],
                "messageIndex": item["messageIndex"],
                "j2534Direction": item["direction"],
                "j2534Timestamp": timestamp,
                "serviceId": service_id,
                "status": status,
                "deltaMs": round(delta * 1000.0, 3),
                "payloadCompared": not bool(message.get("payloadRedacted")),
                "busEvent": {
                    key: event.get(key)
                    for key in (
                        "timestamp",
                        "channel",
                        "canId",
                        "direction",
                        "service",
                        "serviceId",
                        "wireServiceId",
                        "did",
                        "likelyModule",
                        "addressEvidence",
                        "transport",
                    )
                    if key in event
                },
            }
        )
    return correlations


def correlate_markers_to_bus(
    markers: list[dict[str, Any]],
    bus_events: list[dict[str, Any]],
    *,
    window_s: float,
    limit: int = 12,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for marker in markers:
        start = float(marker["timestamp"])
        end = float(marker.get("windowEndTimestamp", start))
        nearby: list[tuple[float, dict[str, Any]]] = []
        for event in bus_events:
            event_ts = float(event["timestamp"])
            if event_ts < start - window_s or event_ts > end + window_s:
                continue
            if start <= event_ts <= end:
                delta = 0.0
            else:
                delta = min(abs(event_ts - start), abs(event_ts - end))
            nearby.append((delta, event))
        nearby.sort(key=lambda row: (row[0], float(row[1]["timestamp"])))
        output.append(
            {
                "marker": marker,
                "nearbyDiagnosticEvents": [
                    {
                        "deltaMsFromMarkerWindow": round(delta * 1000.0, 3),
                        **{
                            key: event.get(key)
                            for key in (
                                "timestamp",
                                "channel",
                                "canId",
                                "direction",
                                "service",
                                "serviceId",
                                "wireServiceId",
                                "did",
                                "likelyModule",
                                "addressEvidence",
                                "transport",
                            )
                            if key in event
                        },
                    }
                    for delta, event in nearby[:limit]
                ],
            }
        )
    return output


def build_bundle(
    *,
    capture: Path | None = None,
    j2534_trace: Path | None = None,
    voice_correlations: Iterable[Path] = (),
    source_application: str | None = None,
    max_j2534_delta_s: float = 1.0,
    marker_window_s: float = 5.0,
) -> dict[str, Any]:
    voice_paths = list(voice_correlations)
    if capture is None and j2534_trace is None and not voice_paths:
        raise ValueError("at least one evidence input is required")

    inputs: list[dict[str, Any]] = []
    gm_result: dict[str, Any] | None = None
    gds2_result: dict[str, Any] | None = None
    markers: list[dict[str, Any]] = []
    if capture is not None:
        inputs.append(input_record(capture, "atlasCandump"))
        gm_result, gds2_result, markers = analyze_capture(capture)

    for voice_path in voice_paths:
        inputs.append(input_record(voice_path, "voiceCorrelation"))
        markers.extend(load_voice_markers(voice_path))
    markers.sort(key=lambda row: float(row["timestamp"]))

    j2534_result: dict[str, Any] | None = None
    message_events: list[dict[str, Any]] = []
    if j2534_trace is not None:
        inputs.append(input_record(j2534_trace, "j2534Trace"))
        j2534_result = analyze_j2534_trace(j2534_trace)
        message_events = j2534_message_events(j2534_result["records"])
        if source_application is None:
            raw_source = j2534_result["session"].get("sourceApplication")
            if raw_source:
                source_application = str(raw_source)

    bus_events = [] if gm_result is None else list(gm_result.get("events", []))
    j2534_correlations = correlate_j2534_to_bus(
        message_events,
        bus_events,
        max_delta_s=max_j2534_delta_s,
    ) if message_events and bus_events else []
    marker_correlations = correlate_markers_to_bus(
        markers,
        bus_events,
        window_s=marker_window_s,
    ) if markers and bus_events else []

    bundle = {
        "schema": SCHEMA_ID,
        "generatedAt": utc_now_iso(),
        "analysisMode": "offlineObservationOnly",
        "sourceApplication": source_application or "unknown",
        "safety": {
            "loadsJ2534Provider": False,
            "opensVehicleAdapter": False,
            "transmitsVehicleTraffic": False,
            "signalPromotionAuthorized": False,
        },
        "evidenceBoundary": (
            "Correlations associate existing evidence layers by timing, service, and payload where available. "
            "They do not by themselves confirm module identity, DID meaning, signal meaning, or vehicle behavior."
        ),
        "integrity": {"inputs": inputs},
        "summary": {
            "inputFiles": len(inputs),
            "operatorMarkers": len(markers),
            "gmDiagnosticEvents": len(bus_events),
            "gmTransactions": 0 if gm_result is None else len(gm_result.get("transactions", [])),
            "gds2DidTransactions": 0 if gds2_result is None else len(gds2_result.get("physicalDidTransactions", [])),
            "gds2DynamicEvents": 0 if gds2_result is None else len(gds2_result.get("dynamicPacketEvents", [])),
            "j2534MessageEvents": len(message_events),
            "j2534BusCorrelations": len(j2534_correlations),
        },
        "markers": markers,
        "gmSession": gm_result,
        "gds2": gds2_result,
        "j2534": j2534_result,
        "correlations": {
            "j2534ToBus": j2534_correlations,
            "markersToDiagnostics": marker_correlations,
        },
    }
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, help="Atlas/candump capture")
    parser.add_argument("--j2534-trace", type=Path, help="Atlas J2534 proxy JSONL trace")
    parser.add_argument(
        "--voice-correlation",
        type=Path,
        action="append",
        default=[],
        help="optional obd-atlas.voice-event-correlation.v1 report; repeatable",
    )
    parser.add_argument("--source-application", help="gds2, sps2, dps, or another source label")
    parser.add_argument("--max-j2534-delta-ms", type=float, default=1000.0)
    parser.add_argument("--marker-window-seconds", type=float, default=5.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    bundle = build_bundle(
        capture=args.capture,
        j2534_trace=args.j2534_trace,
        voice_correlations=args.voice_correlation,
        source_application=args.source_application,
        max_j2534_delta_s=args.max_j2534_delta_ms / 1000.0,
        marker_window_s=args.marker_window_seconds,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"GM tool evidence bundle: {args.output}")
    print(f"Inputs: {bundle['summary']['inputFiles']}")
    print(f"GM diagnostic events: {bundle['summary']['gmDiagnosticEvents']}")
    print(f"J2534/bus correlations: {bundle['summary']['j2534BusCorrelations']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
