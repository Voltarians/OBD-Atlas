#!/usr/bin/env python3
"""Passively summarize GM diagnostic/programming traffic from Atlas candump logs.

The parser is observation-only. It never transmits vehicle traffic.

It understands classic ISO-TP framing and labels common UDS/GM services used by
GDS2, SPS/SPS2 and DPS. When a provenance-preserving GM address reference is
available, it also recognizes legacy unframed request/response families and
reports matching 0x5xx data-stream traffic without pretending the reference is
vehicle-confirmed.

Output is intentionally evidence-oriented: raw payloads are retained and fields
are decoded only where the service layout is unambiguous.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

CANDUMP_RE = re.compile(
    r"^\((?P<ts>\d+(?:\.\d+)?)\)\s+"
    r"(?P<channel>\S+)\s+"
    r"(?P<canid>[0-9A-Fa-f]+)#(?P<data>[0-9A-Fa-f]*)\s*$"
)

DEFAULT_ADDRESS_REFERENCE = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "diagnostics"
    / "gm_legacy_simulation_address_reference.json"
)

SERVICES = {
    0x04: "ClearDiagnosticInformationLegacy",
    0x09: "RequestVehicleInformation",
    0x10: "DiagnosticSessionControl",
    0x11: "ECUReset",
    0x12: "GMFailureRecord",
    0x18: "ReadDTCInformationLegacy",
    0x22: "ReadDataByIdentifier",
    0x27: "SecurityAccess",
    0x28: "CommunicationControl",
    0x2C: "DynamicallyDefineDataIdentifier",
    0x2E: "WriteDataByIdentifier",
    0x31: "RoutineControl",
    0x34: "RequestDownload",
    0x35: "RequestUpload",
    0x36: "TransferData",
    0x37: "RequestTransferExit",
    0x3E: "TesterPresent",
    0x85: "ControlDTCSetting",
    0xA9: "GMReadDTCInformation",
    0xAA: "GMDynamicDataPacketControl",
}

SPECIAL_POSITIVE = {
    0x44: 0x04,
    0x49: 0x09,
    0x52: 0x12,
    0x58: 0x18,
    0x81: 0xA9,
}

NRC_NAMES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x14: "responseTooLong",
    0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceedNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x70: "uploadDownloadNotAccepted",
    0x71: "transferDataSuspended",
    0x72: "generalProgrammingFailure",
    0x73: "wrongBlockSequenceCounter",
    0x78: "responsePending",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}


@dataclass(frozen=True)
class Frame:
    timestamp: float
    channel: str
    can_id: int
    data: bytes


@dataclass(frozen=True)
class IsoTpMessage:
    timestamp: float
    channel: str
    can_id: int
    payload: bytes


def parse_frames(lines: Iterable[str]) -> Iterable[Frame]:
    for line in lines:
        match = CANDUMP_RE.match(line.strip())
        if not match:
            continue
        raw = match.group("data")
        if len(raw) % 2:
            continue
        try:
            payload = bytes.fromhex(raw)
        except ValueError:
            continue
        yield Frame(
            timestamp=float(match.group("ts")),
            channel=match.group("channel"),
            can_id=int(match.group("canid"), 16),
            data=payload,
        )


def reassemble_isotp(frames: Iterable[Frame]) -> Iterable[IsoTpMessage]:
    """Reassemble classic ISO-TP single/first/consecutive frames.

    Extended addressing and CAN FD are deliberately not inferred.
    """
    active: dict[tuple[str, int], dict[str, object]] = {}

    for frame in frames:
        if not frame.data:
            continue
        pci_type = frame.data[0] >> 4
        key = (frame.channel, frame.can_id)

        if pci_type == 0x0:
            length = frame.data[0] & 0x0F
            if 0 < length <= len(frame.data) - 1:
                yield IsoTpMessage(
                    frame.timestamp,
                    frame.channel,
                    frame.can_id,
                    frame.data[1 : 1 + length],
                )
            continue

        if pci_type == 0x1 and len(frame.data) >= 2:
            length = ((frame.data[0] & 0x0F) << 8) | frame.data[1]
            if length <= 6:
                continue
            active[key] = {
                "timestamp": frame.timestamp,
                "length": length,
                "nextSequence": 1,
                "data": bytearray(frame.data[2:]),
            }
            if len(active[key]["data"]) >= length:
                buf = active[key]["data"]
                assert isinstance(buf, bytearray)
                yield IsoTpMessage(
                    frame.timestamp,
                    frame.channel,
                    frame.can_id,
                    bytes(buf[:length]),
                )
                active.pop(key, None)
            continue

        if pci_type == 0x2 and key in active:
            state = active[key]
            sequence = frame.data[0] & 0x0F
            expected_sequence = int(state["nextSequence"])
            if sequence != expected_sequence:
                active.pop(key, None)
                continue
            buf = state["data"]
            assert isinstance(buf, bytearray)
            buf.extend(frame.data[1:])
            state["nextSequence"] = (expected_sequence + 1) & 0x0F
            length = int(state["length"])
            if len(buf) >= length:
                yield IsoTpMessage(
                    float(state["timestamp"]),
                    frame.channel,
                    frame.can_id,
                    bytes(buf[:length]),
                )
                active.pop(key, None)
            continue


def _positive_map() -> dict[int, int]:
    result = dict(SPECIAL_POSITIVE)
    for request_sid in SERVICES:
        positive_sid = request_sid + 0x40
        if positive_sid <= 0xFF:
            result.setdefault(positive_sid, request_sid)
    return result


POSITIVE_TO_REQUEST = _positive_map()


def _decode_fields(service: int, payload: bytes, direction: str) -> dict[str, object]:
    fields: dict[str, object] = {}
    data = payload[1:]

    if service in (0x10, 0x11, 0x3E, 0x85) and data:
        fields["subFunction"] = f"0x{data[0]:02X}"
    elif service == 0x22 and len(data) >= 2:
        fields["did"] = f"0x{(data[0] << 8) | data[1]:04X}"
        if direction == "positiveResponse":
            fields["data"] = data[2:].hex().upper()
        elif len(data) > 2:
            fields["additionalRequestBytes"] = data[2:].hex().upper()
    elif service == 0x27 and data:
        access_type = data[0]
        fields["securityAccessType"] = f"0x{access_type:02X}"
        fields["securityOperation"] = "requestSeed" if access_type & 1 else "sendKey"
        if len(data) > 1:
            fields["securityData"] = data[1:].hex().upper()
    elif service == 0x2C and data:
        fields["dynamicIdentifierOrPacket"] = f"0x{data[0]:02X}"
        if len(data) > 1:
            fields["definition"] = data[1:].hex().upper()
    elif service == 0x2E and len(data) >= 2:
        fields["did"] = f"0x{(data[0] << 8) | data[1]:04X}"
        if len(data) > 2:
            fields["data"] = data[2:].hex().upper()
    elif service == 0x31 and data:
        fields["routineControlType"] = f"0x{data[0]:02X}"
        if len(data) >= 3:
            fields["routineIdentifier"] = f"0x{(data[1] << 8) | data[2]:04X}"
        if len(data) > 3:
            fields["routineData"] = data[3:].hex().upper()
    elif service in (0x34, 0x35):
        if data:
            fields["formatOrLengthByte"] = f"0x{data[0]:02X}"
        if len(data) > 1:
            fields["transferParameters"] = data[1:].hex().upper()
    elif service == 0x36:
        if data:
            fields["blockSequenceCounter"] = data[0]
        if len(data) > 1:
            fields["transferBytes"] = len(data) - 1
            fields["transferData"] = data[1:].hex().upper()
    elif service == 0x37 and data:
        fields["transferExitData"] = data.hex().upper()
    elif service == 0xAA and data:
        fields["gmControlByte"] = f"0x{data[0]:02X}"
        if len(data) > 1:
            fields["gmPacketArguments"] = data[1:].hex().upper()
    elif service in (0x04, 0x09, 0x12, 0x18, 0x28, 0xA9) and data:
        fields["parameters"] = data.hex().upper()

    return fields


def classify_message(message: IsoTpMessage) -> dict[str, object] | None:
    if not message.payload:
        return None

    sid = message.payload[0]
    base: dict[str, object] = {
        "timestamp": message.timestamp,
        "channel": message.channel,
        "canId": f"0x{message.can_id:X}",
        "payload": message.payload.hex().upper(),
    }

    if sid == 0x7F and len(message.payload) >= 3:
        original = message.payload[1]
        nrc = message.payload[2]
        base.update(
            {
                "direction": "negativeResponse",
                "service": SERVICES.get(original, f"Service0x{original:02X}"),
                "serviceId": f"0x{original:02X}",
                "negativeResponseCode": f"0x{nrc:02X}",
                "negativeResponseName": NRC_NAMES.get(nrc, "unknown"),
            }
        )
        return base

    if sid in SERVICES:
        service = sid
        direction = "request"
    elif sid in POSITIVE_TO_REQUEST:
        service = POSITIVE_TO_REQUEST[sid]
        direction = "positiveResponse"
    else:
        return None

    base.update(
        {
            "direction": direction,
            "service": SERVICES[service],
            "serviceId": f"0x{service:02X}",
            "wireServiceId": f"0x{sid:02X}",
        }
    )
    base.update(_decode_fields(service, message.payload, direction))
    return base


def extract_diagnostic_events(messages: Iterable[IsoTpMessage]) -> list[dict[str, object]]:
    events = []
    for message in messages:
        event = classify_message(message)
        if event is not None:
            event["transport"] = "isoTp"
            events.append(event)
    events.sort(key=lambda row: float(row["timestamp"]))
    return events


def _parse_can_id(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def load_address_reference(path: Path | None) -> dict[str, object] | None:
    if path is None or not path.exists():
        return None
    root = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(root, dict) or root.get("schemaVersion") != 1:
        raise ValueError(f"Unsupported address reference: {path}")
    if not isinstance(root.get("modules"), list):
        raise ValueError(f"Address reference has no modules: {path}")
    return root


def build_address_index(reference: dict[str, object] | None) -> dict[int, list[dict[str, str]]]:
    index: dict[int, list[dict[str, str]]] = defaultdict(list)
    if reference is None:
        return {}

    confidence = str(reference.get("confidence", "unknown"))
    catalog_id = str(reference.get("catalogId", "unknown"))
    role_fields = {
        "requestCanIds": "request",
        "normalResponseCanIds": "normalResponse",
        "dataCanIds": "dataStream",
        "functionalRequestCanIds": "functionalRequest",
    }
    modules = reference.get("modules", [])
    assert isinstance(modules, list)
    for raw_module in modules:
        if not isinstance(raw_module, dict) or not isinstance(raw_module.get("module"), str):
            continue
        module = str(raw_module["module"])
        for field, role in role_fields.items():
            values = raw_module.get(field, [])
            if not isinstance(values, list):
                continue
            for raw_can_id in values:
                can_id = _parse_can_id(raw_can_id)
                if can_id is None:
                    continue
                candidate = {
                    "module": module,
                    "role": role,
                    "confidence": confidence,
                    "catalogId": catalog_id,
                }
                if candidate not in index[can_id]:
                    index[can_id].append(candidate)
    return dict(index)


def annotate_events(
    events: list[dict[str, object]],
    address_index: dict[int, list[dict[str, str]]],
) -> None:
    for event in events:
        can_id = _parse_can_id(event.get("canId"))
        if can_id is None:
            continue
        matches = address_index.get(can_id, [])
        if not matches:
            continue
        event["addressMatches"] = matches
        if len(matches) == 1:
            match = matches[0]
            event["likelyModule"] = match["module"]
            event["addressRole"] = match["role"]
            event["addressEvidence"] = match["confidence"]


def extract_legacy_reference_events(
    frames: Iterable[Frame],
    address_index: dict[int, list[dict[str, str]]],
    iso_events: Iterable[dict[str, object]] = (),
) -> list[dict[str, object]]:
    """Classify unframed legacy GM request/response records on known endpoint IDs.

    0x5xx data-stream IDs are intentionally not treated as diagnostic services;
    they are reported by endpoint traffic aggregation instead.
    """
    events: list[dict[str, object]] = []
    iso_origins = {
        (float(event["timestamp"]), str(event["channel"]), _parse_can_id(event.get("canId")))
        for event in iso_events
    }
    for frame in frames:
        if (frame.timestamp, frame.channel, frame.can_id) in iso_origins:
            continue
        matches = address_index.get(frame.can_id, [])
        if not matches or not frame.data:
            continue
        roles = {match["role"] for match in matches}
        if not roles.intersection({"request", "functionalRequest", "normalResponse"}):
            continue

        sid = frame.data[0]
        if sid not in SERVICES and sid not in POSITIVE_TO_REQUEST and sid != 0x7F:
            continue

        event = classify_message(
            IsoTpMessage(frame.timestamp, frame.channel, frame.can_id, frame.data)
        )
        if event is None:
            continue

        direction = str(event["direction"])
        if direction == "request" and not roles.intersection({"request", "functionalRequest"}):
            continue
        if direction != "request" and "normalResponse" not in roles:
            continue

        event["transport"] = "legacyUnframedReference"
        events.append(event)

    events.sort(key=lambda row: float(row["timestamp"]))
    return events


def merge_events(*event_lists: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[float, str, str, str, str]] = set()
    result: list[dict[str, object]] = []
    for events in event_lists:
        for event in events:
            key = (
                float(event["timestamp"]),
                str(event["channel"]),
                str(event["canId"]),
                str(event["payload"]),
                str(event["direction"]),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(event)
    result.sort(key=lambda row: float(row["timestamp"]))
    return result


def build_endpoint_traffic(
    frames: Iterable[Frame],
    address_index: dict[int, list[dict[str, str]]],
) -> list[dict[str, object]]:
    buckets: dict[tuple[str, int, str, str, str], dict[str, object]] = {}
    for frame in frames:
        for match in address_index.get(frame.can_id, []):
            key = (
                frame.channel,
                frame.can_id,
                match["module"],
                match["role"],
                match["confidence"],
            )
            bucket = buckets.setdefault(
                key,
                {
                    "channel": frame.channel,
                    "canId": f"0x{frame.can_id:X}",
                    "module": match["module"],
                    "role": match["role"],
                    "confidence": match["confidence"],
                    "frameCount": 0,
                    "firstTimestamp": frame.timestamp,
                    "lastTimestamp": frame.timestamp,
                },
            )
            bucket["frameCount"] = int(bucket["frameCount"]) + 1
            bucket["lastTimestamp"] = frame.timestamp

    result = list(buckets.values())
    result.sort(key=lambda row: (str(row["module"]), str(row["role"]), str(row["channel"])))
    return result


def _event_matches_module_role(
    event: dict[str, object],
    module: str,
    roles: set[str],
) -> bool:
    matches = event.get("addressMatches")
    if not isinstance(matches, list):
        return False
    return any(
        isinstance(match, dict)
        and match.get("module") == module
        and match.get("role") in roles
        for match in matches
    )


def build_transactions(events: list[dict[str, object]]) -> list[dict[str, object]]:
    """Pair uniquely addressed requests with responses and calculate latency.

    Ambiguous functional requests are left unpaired. A responsePending NRC is
    recorded as the initial response and pairing continues until a terminal
    positive or negative response is observed.
    """
    transactions: list[dict[str, object]] = []

    for index, request in enumerate(events):
        if request.get("direction") != "request":
            continue
        matches = request.get("addressMatches")
        if not isinstance(matches, list):
            continue
        request_matches = [
            match
            for match in matches
            if isinstance(match, dict) and match.get("role") == "request"
        ]
        modules = {str(match["module"]) for match in request_matches if "module" in match}
        if len(modules) != 1:
            continue
        module = next(iter(modules))
        service = str(request["service"])
        channel = str(request["channel"])
        request_ts = float(request["timestamp"])
        responses: list[dict[str, object]] = []

        for candidate in events[index + 1 :]:
            if str(candidate["channel"]) != channel:
                continue
            if (
                candidate.get("direction") == "request"
                and str(candidate.get("service")) == service
                and _event_matches_module_role(candidate, module, {"request"})
            ):
                break
            if str(candidate.get("service")) != service:
                continue
            if not _event_matches_module_role(candidate, module, {"normalResponse"}):
                continue
            if candidate.get("direction") not in {"positiveResponse", "negativeResponse"}:
                continue

            response_ts = float(candidate["timestamp"])
            response = {
                "timestamp": response_ts,
                "canId": candidate["canId"],
                "direction": candidate["direction"],
                "latencyMs": round((response_ts - request_ts) * 1000.0, 3),
            }
            if candidate.get("direction") == "negativeResponse":
                response["negativeResponseCode"] = candidate.get("negativeResponseCode")
                response["negativeResponseName"] = candidate.get("negativeResponseName")
            responses.append(response)

            if not (
                candidate.get("direction") == "negativeResponse"
                and candidate.get("negativeResponseName") == "responsePending"
            ):
                break

        transaction: dict[str, object] = {
            "module": module,
            "addressEvidence": request_matches[0].get("confidence", "unknown"),
            "channel": channel,
            "service": service,
            "serviceId": request["serviceId"],
            "requestTimestamp": request_ts,
            "requestCanId": request["canId"],
            "transport": request.get("transport"),
            "responseCount": len(responses),
            "responses": responses,
        }
        if responses:
            transaction["initialResponseLatencyMs"] = responses[0]["latencyMs"]
            transaction["finalResponseLatencyMs"] = responses[-1]["latencyMs"]
            transaction["finalResponseDirection"] = responses[-1]["direction"]
        else:
            transaction["unanswered"] = True
        transactions.append(transaction)

    return transactions


def build_summary(
    events: list[dict[str, object]],
    endpoint_traffic: list[dict[str, object]] | None = None,
    transactions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    service_counts = Counter(str(event["service"]) for event in events)
    request_counts = Counter(
        str(event["service"])
        for event in events
        if event.get("direction") == "request"
    )
    negative_counts = Counter(
        str(event.get("negativeResponseName", "unknown"))
        for event in events
        if event.get("direction") == "negativeResponse"
    )

    programming_services = {
        "DiagnosticSessionControl",
        "ECUReset",
        "SecurityAccess",
        "WriteDataByIdentifier",
        "RoutineControl",
        "RequestDownload",
        "RequestUpload",
        "TransferData",
        "RequestTransferExit",
    }
    programming_seen = sorted(set(service_counts) & programming_services)

    summary: dict[str, object] = {
        "eventCount": len(events),
        "services": dict(sorted(service_counts.items())),
        "requests": dict(sorted(request_counts.items())),
        "negativeResponses": dict(sorted(negative_counts.items())),
        "programmingServicesObserved": programming_seen,
        "programmingTrafficObserved": bool(programming_seen),
    }
    if endpoint_traffic is not None:
        modules = sorted({str(row["module"]) for row in endpoint_traffic})
        roles = Counter(str(row["role"]) for row in endpoint_traffic)
        summary["addressReferencedModulesObserved"] = modules
        summary["addressReferencedModuleCount"] = len(modules)
        summary["addressReferencedTrafficByRole"] = dict(sorted(roles.items()))
    if transactions is not None:
        answered = sum(1 for row in transactions if not row.get("unanswered"))
        summary["transactionCount"] = len(transactions)
        summary["answeredTransactionCount"] = answered
        summary["unansweredTransactionCount"] = len(transactions) - answered
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="Atlas/candump log")
    parser.add_argument("--json-out", type=Path, help="optional JSON output path")
    parser.add_argument(
        "--include-transfer-data",
        action="store_true",
        help="include full 0x36 transfer blocks in JSON/console data; default redacts block bytes",
    )
    parser.add_argument(
        "--address-reference",
        type=Path,
        default=DEFAULT_ADDRESS_REFERENCE,
        help="provenance-preserving GM address reference JSON",
    )
    parser.add_argument(
        "--no-address-reference",
        action="store_true",
        help="disable ECU/address-family matching",
    )
    args = parser.parse_args()

    with args.capture.open("r", encoding="utf-8", errors="replace") as handle:
        frames = list(parse_frames(handle))

    address_reference = None
    address_index: dict[int, list[dict[str, str]]] = {}
    if not args.no_address_reference:
        address_reference = load_address_reference(args.address_reference)
        address_index = build_address_index(address_reference)

    messages = list(reassemble_isotp(frames))
    iso_events = extract_diagnostic_events(messages)
    legacy_events = extract_legacy_reference_events(frames, address_index, iso_events)
    events = merge_events(iso_events, legacy_events)
    annotate_events(events, address_index)

    endpoint_traffic = build_endpoint_traffic(frames, address_index)
    transactions = build_transactions(events)

    if not args.include_transfer_data:
        for event in events:
            if event.get("service") == "TransferData" and "transferData" in event:
                event["transferData"] = "<redacted>"
                event["transferDataRedacted"] = True

    result = {
        "capture": str(args.capture),
        "frameCount": len(frames),
        "isoTpMessageCount": len(messages),
        "addressReference": (
            {
                "catalogId": address_reference.get("catalogId"),
                "confidence": address_reference.get("confidence"),
                "path": str(args.address_reference),
            }
            if address_reference is not None
            else None
        ),
        "summary": build_summary(events, endpoint_traffic, transactions),
        "endpointTraffic": endpoint_traffic,
        "transactions": transactions,
        "events": events,
    }

    if args.json_out:
        args.json_out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    summary = result["summary"]
    print(f"frames: {result['frameCount']}")
    print(f"ISO-TP messages: {result['isoTpMessageCount']}")
    print(f"diagnostic events: {summary['eventCount']}")
    print("services:")
    for name, count in summary["services"].items():
        print(f"  {name}: {count}")
    modules = summary.get("addressReferencedModulesObserved", [])
    if modules:
        print("address-reference matches: " + ", ".join(modules))
        print(
            "transactions: "
            f"{summary['answeredTransactionCount']} answered / "
            f"{summary['unansweredTransactionCount']} unanswered"
        )
    if summary["programmingTrafficObserved"]:
        print(
            "programming services observed: "
            + ", ".join(summary["programmingServicesObserved"])
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
