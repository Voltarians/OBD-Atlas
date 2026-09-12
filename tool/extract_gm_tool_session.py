#!/usr/bin/env python3
"""Passively summarize GM diagnostic/programming traffic from Atlas candump logs.

The parser is observation-only. It never transmits vehicle traffic.

It understands classic ISO-TP framing and labels common UDS/GM services used by
GDS2, SPS/SPS2 and DPS, including diagnostic session control, ECU reset,
Read/WriteDataByIdentifier, SecurityAccess, dynamic data definitions, routines,
RequestDownload, TransferData, RequestTransferExit and TesterPresent.

Output is intentionally evidence-oriented: raw payloads are retained and fields
are decoded only where the service layout is unambiguous.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

CANDUMP_RE = re.compile(
    r"^\((?P<ts>\d+(?:\.\d+)?)\)\s+"
    r"(?P<channel>\S+)\s+"
    r"(?P<canid>[0-9A-Fa-f]+)#(?P<data>[0-9A-Fa-f]*)\s*$"
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

# Positive-response bytes that do not always follow the simple +0x40 rule in
# older GM examples. Standard +0x40 mappings are added automatically.
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

        # 0x3 flow control and non-ISO-TP traffic are intentionally ignored.


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
        fields["securityOperation"] = (
            "requestSeed" if access_type & 1 else "sendKey"
        )
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
            events.append(event)
    events.sort(key=lambda row: float(row["timestamp"]))
    return events


def build_summary(events: list[dict[str, object]]) -> dict[str, object]:
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

    return {
        "eventCount": len(events),
        "services": dict(sorted(service_counts.items())),
        "requests": dict(sorted(request_counts.items())),
        "negativeResponses": dict(sorted(negative_counts.items())),
        "programmingServicesObserved": programming_seen,
        "programmingTrafficObserved": bool(programming_seen),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="Atlas/candump log")
    parser.add_argument("--json-out", type=Path, help="optional JSON output path")
    parser.add_argument(
        "--include-transfer-data",
        action="store_true",
        help="include full 0x36 transfer blocks in JSON/console data; default redacts block bytes",
    )
    args = parser.parse_args()

    with args.capture.open("r", encoding="utf-8", errors="replace") as handle:
        frames = list(parse_frames(handle))
    messages = list(reassemble_isotp(frames))
    events = extract_diagnostic_events(messages)

    if not args.include_transfer_data:
        for event in events:
            if event.get("service") == "TransferData" and "transferData" in event:
                event["transferData"] = "<redacted>"
                event["transferDataRedacted"] = True

    result = {
        "capture": str(args.capture),
        "frameCount": len(frames),
        "isoTpMessageCount": len(messages),
        "summary": build_summary(events),
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
    if summary["programmingTrafficObserved"]:
        print(
            "programming services observed: "
            + ", ".join(summary["programmingServicesObserved"])
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
