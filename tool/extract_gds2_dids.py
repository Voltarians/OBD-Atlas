#!/usr/bin/env python3
"""Extract Gen-1 Volt HPCM2 diagnostic data from Atlas/candump captures.

Default HPCM2 diagnostic addressing:
    physical request   0x7E4
    physical response  0x7EC
    dynamic response   0x5EC

The tool is passive: it only parses an existing log. It handles two GM diagnostic
patterns useful for mapping GDS2 Data Display parameters:

* service 0x22 -> 0x62 ReadDataByParameterIdentifier transactions; and
* service 0x2C dynamic packet definitions followed by service 0xAA packet reads
  and UUDT data on 0x5EC.

Classic ISO-TP single, first, consecutive and flow-control framing is understood.
No diagnostic traffic is transmitted by this tool.
"""

from __future__ import annotations

import argparse
import json
import re
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
    # key -> [first_timestamp, expected_length, bytearray]
    active: dict[tuple[str, int], list[object]] = {}

    for frame in frames:
        if not frame.data:
            continue
        pci = frame.data[0] >> 4
        key = (frame.channel, frame.can_id)

        if pci == 0x0:  # single frame
            length = frame.data[0] & 0x0F
            if length == 0 or length > len(frame.data) - 1:
                continue
            yield IsoTpMessage(
                frame.timestamp,
                frame.channel,
                frame.can_id,
                frame.data[1 : 1 + length],
            )
            continue

        if pci == 0x1 and len(frame.data) >= 2:  # first frame
            length = ((frame.data[0] & 0x0F) << 8) | frame.data[1]
            if length <= 6:
                continue
            buf = bytearray(frame.data[2:])
            active[key] = [frame.timestamp, length, buf]
            if len(buf) >= length:
                yield IsoTpMessage(
                    frame.timestamp,
                    frame.channel,
                    frame.can_id,
                    bytes(buf[:length]),
                )
                active.pop(key, None)
            continue

        if pci == 0x2 and key in active:  # consecutive frame
            first_ts, expected, buf = active[key]
            assert isinstance(first_ts, float)
            assert isinstance(expected, int)
            assert isinstance(buf, bytearray)
            buf.extend(frame.data[1:])
            if len(buf) >= expected:
                yield IsoTpMessage(
                    first_ts,
                    frame.channel,
                    frame.can_id,
                    bytes(buf[:expected]),
                )
                active.pop(key, None)
            continue

        # Flow control (0x3) and unrelated/raw CAN are intentionally ignored here.


def extract_did_transactions(
    messages: Iterable[IsoTpMessage],
    tx_id: int = 0x7E4,
    rx_id: int = 0x7EC,
    response_window_s: float = 2.0,
) -> list[dict[str, object]]:
    """Match physical service 0x22 requests with positive 0x62 responses."""
    pending: dict[tuple[str, int], list[IsoTpMessage]] = {}
    output: list[dict[str, object]] = []

    for message in messages:
        payload = message.payload
        if message.can_id == tx_id and len(payload) >= 3 and payload[0] == 0x22:
            did = (payload[1] << 8) | payload[2]
            pending.setdefault((message.channel, did), []).append(message)
            continue

        if message.can_id == rx_id and len(payload) >= 3 and payload[0] == 0x62:
            did = (payload[1] << 8) | payload[2]
            key = (message.channel, did)
            requests = pending.get(key, [])
            request = None
            while requests:
                candidate = requests.pop(0)
                if 0 <= message.timestamp - candidate.timestamp <= response_window_s:
                    request = candidate
                    break
            if request is None:
                continue
            output.append(
                {
                    "kind": "readDataByParameterIdentifier",
                    "channel": message.channel,
                    "did": f"0x{did:04X}",
                    "requestTimestamp": request.timestamp,
                    "responseTimestamp": message.timestamp,
                    "latencyMs": round((message.timestamp - request.timestamp) * 1000.0, 3),
                    "requestPayload": request.payload.hex().upper(),
                    "responsePayload": message.payload.hex().upper(),
                    "data": message.payload[3:].hex().upper(),
                }
            )

    return output


def _dynamic_definitions(
    messages: Iterable[IsoTpMessage], tx_id: int
) -> list[dict[str, object]]:
    """Decode GM 0x2C packet definitions: [2C, packet_id, DID_hi, DID_lo, ...]."""
    definitions: list[dict[str, object]] = []
    for message in messages:
        payload = message.payload
        if message.can_id != tx_id or len(payload) < 4 or payload[0] != 0x2C:
            continue
        remainder = payload[2:]
        if len(remainder) % 2:
            continue
        dids = [
            f"0x{(remainder[i] << 8) | remainder[i + 1]:04X}"
            for i in range(0, len(remainder), 2)
        ]
        definitions.append(
            {
                "kind": "dynamicDefinition",
                "timestamp": message.timestamp,
                "channel": message.channel,
                "packetId": f"0x{payload[1]:02X}",
                "dids": dids,
                "requestPayload": payload.hex().upper(),
            }
        )
    return definitions


def extract_dynamic_packet_sessions(
    frames: list[Frame],
    messages: list[IsoTpMessage],
    tx_id: int = 0x7E4,
    dynamic_rx_id: int = 0x5EC,
) -> list[dict[str, object]]:
    """Extract 0x2C definitions, 0xAA packet starts/stops and raw UUDT samples.

    Data byte boundaries between multiple DIDs are intentionally not guessed because
    PID response lengths are calibration-specific metadata. For a one-DID packet the
    entire UUDT payload after the packet ID is exposed as ``singleDidData``.
    """
    definitions = _dynamic_definitions(messages, tx_id)
    events: list[dict[str, object]] = list(definitions)

    # Latest definition at a point in time, keyed by channel and packet id.
    current: dict[tuple[str, int], dict[str, object]] = {}
    timeline: list[tuple[float, str, int, dict[str, object]]] = []
    for definition in definitions:
        packet_id = int(str(definition["packetId"]), 16)
        timeline.append(
            (
                float(definition["timestamp"]),
                str(definition["channel"]),
                packet_id,
                definition,
            )
        )
    timeline.sort(key=lambda item: item[0])

    # Start/stop commands are ordinary ISO-TP requests: AA <rate> <packet-id>.
    for message in messages:
        payload = message.payload
        if message.can_id != tx_id or len(payload) < 3 or payload[0] != 0xAA:
            continue
        rate = payload[1]
        packet_id = payload[2]
        events.append(
            {
                "kind": "dynamicPacketControl",
                "timestamp": message.timestamp,
                "channel": message.channel,
                "packetId": f"0x{packet_id:02X}",
                "rate": rate,
                "state": "stop" if rate == 0 else ("single" if rate == 1 else "periodic"),
                "requestPayload": payload.hex().upper(),
            }
        )

    # UUDT frames on 0x5EC are raw application data, not ISO-TP framed.
    definition_index = 0
    for frame in sorted(frames, key=lambda item: item.timestamp):
        while definition_index < len(timeline) and timeline[definition_index][0] <= frame.timestamp:
            _, channel, packet_id, definition = timeline[definition_index]
            current[(channel, packet_id)] = definition
            definition_index += 1

        if frame.can_id != dynamic_rx_id or not frame.data:
            continue
        packet_id = frame.data[0]
        definition = current.get((frame.channel, packet_id))
        dids = list(definition.get("dids", [])) if definition else []
        event: dict[str, object] = {
            "kind": "dynamicPacketSample",
            "timestamp": frame.timestamp,
            "channel": frame.channel,
            "canId": f"0x{frame.can_id:03X}",
            "packetId": f"0x{packet_id:02X}",
            "dids": dids,
            "data": frame.data[1:].hex().upper(),
        }
        if len(dids) == 1:
            event["singleDid"] = dids[0]
            event["singleDidData"] = frame.data[1:].hex().upper()
        events.append(event)

    events.sort(key=lambda event: float(event.get("timestamp", 0.0)))
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="Atlas/candump log")
    parser.add_argument("--tx-id", default="7E4", help="physical request CAN ID in hex")
    parser.add_argument("--rx-id", default="7EC", help="physical response CAN ID in hex")
    parser.add_argument(
        "--dynamic-rx-id",
        default="5EC",
        help="dynamic UUDT response CAN ID in hex (default 5EC)",
    )
    parser.add_argument("--json-out", type=Path, help="optional JSON output path")
    args = parser.parse_args()

    tx_id = int(args.tx_id, 16)
    rx_id = int(args.rx_id, 16)
    dynamic_rx_id = int(args.dynamic_rx_id, 16)
    with args.capture.open("r", encoding="utf-8", errors="replace") as handle:
        frames = list(parse_frames(handle))
    messages = list(reassemble_isotp(frames))
    did_transactions = extract_did_transactions(messages, tx_id=tx_id, rx_id=rx_id)
    dynamic_events = extract_dynamic_packet_sessions(
        frames,
        messages,
        tx_id=tx_id,
        dynamic_rx_id=dynamic_rx_id,
    )
    result = {
        "physicalDidTransactions": did_transactions,
        "dynamicPacketEvents": dynamic_events,
    }

    if args.json_out:
        args.json_out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    for row in did_transactions:
        print(
            f"{row['requestTimestamp']:.6f} {row['channel']} {row['did']} "
            f"-> {row['data']} ({row['latencyMs']} ms)"
        )
    for event in dynamic_events:
        if event["kind"] == "dynamicDefinition":
            print(
                f"{event['timestamp']:.6f} {event['channel']} DEFINE "
                f"{event['packetId']} = {','.join(event['dids'])}"
            )
        elif event["kind"] == "dynamicPacketSample" and event.get("singleDid"):
            print(
                f"{event['timestamp']:.6f} {event['channel']} {event['singleDid']} "
                f"=> {event['singleDidData']} via {event['canId']}"
            )
    print(f"0x22 DID transactions: {len(did_transactions)}")
    print(f"dynamic packet events: {len(dynamic_events)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
