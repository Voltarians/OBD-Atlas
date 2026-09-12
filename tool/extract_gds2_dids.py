#!/usr/bin/env python3
"""Extract HPCM2 ReadDataByIdentifier traffic from Atlas/candump captures.

Default Gen-1 Volt HPCM2 diagnostic pair:
    request  0x7E4
    response 0x7EC

The tool is passive: it only parses an existing log. It understands classic ISO-TP
single, first and consecutive frames, preserves arbitrary CAN channel names, and
matches UDS/GMLAN service 0x22 requests to positive 0x62 responses by DID.
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

        # Flow control (0x3) and unrelated/raw CAN are intentionally ignored.


def extract_did_transactions(
    messages: Iterable[IsoTpMessage],
    tx_id: int = 0x7E4,
    rx_id: int = 0x7EC,
    response_window_s: float = 2.0,
) -> list[dict[str, object]]:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="Atlas/candump log")
    parser.add_argument("--tx-id", default="7E4", help="request CAN ID in hex (default 7E4)")
    parser.add_argument("--rx-id", default="7EC", help="response CAN ID in hex (default 7EC)")
    parser.add_argument("--json-out", type=Path, help="optional JSON output path")
    args = parser.parse_args()

    tx_id = int(args.tx_id, 16)
    rx_id = int(args.rx_id, 16)
    with args.capture.open("r", encoding="utf-8", errors="replace") as handle:
        messages = reassemble_isotp(parse_frames(handle))
        transactions = extract_did_transactions(messages, tx_id=tx_id, rx_id=rx_id)

    if args.json_out:
        args.json_out.write_text(json.dumps(transactions, indent=2) + "\n", encoding="utf-8")

    for row in transactions:
        print(
            f"{row['requestTimestamp']:.6f} {row['channel']} {row['did']} "
            f"-> {row['data']} ({row['latencyMs']} ms)"
        )
    print(f"DID transactions: {len(transactions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
