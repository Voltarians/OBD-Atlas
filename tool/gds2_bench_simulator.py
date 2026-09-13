#!/usr/bin/env python3
"""Read-only Chevrolet Volt Gen-1 HPCM2 simulator for an isolated GDS2 bench.

Architecture:
    GDS2 -> J2534 provider -> VCX -> isolated 500 kbit/s CAN bench
         -> UC2 device 0 CAN1 -> this simulator

The simulator intentionally implements only diagnostic behavior that is useful
for identification and read-only scan-tool exploration. It refuses services
that could represent security unlock, programming, writes, routines, actuator
control, or communication changes.

The vehicle MUST remain disconnected while this simulator is active.
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from uc2_vcx_bench import (
    DEVICE_TYPE,
    TIMING,
    U32_ERROR,
    VciCanObj,
    VciInitConfig,
    bind,
    check_layouts,
    find_library,
    frame_bytes,
    make_init_config,
)

HPCM2_REQUEST_ID = 0x7E4
HPCM2_RESPONSE_ID = 0x7EC
DEFAULT_VIN = "1G1RA6E40DU100001"

# Plausible, static read-only values. Candidate DID meanings come from Atlas's
# Gen-1 HPCM2 evidence catalog. These bytes are simulator fixtures, not claims
# about exact physical values on a real vehicle.
DEFAULT_DIDS: dict[int, bytes] = {
    0x40E9: bytes.fromhex("0800"),  # pack resistance candidate
    0x41B0: bytes.fromhex("05DC"),  # 14 V power available candidate
    0x41C4: bytes.fromhex("0096"),  # average battery voltage sensor candidate
    0x4329: bytes.fromhex("0094"),  # minimum module voltage candidate
    0x432B: bytes.fromhex("0098"),  # maximum module voltage candidate
    0x432C: bytes.fromhex("18"),    # module index candidate
    0x433B: bytes.fromhex("02BC"),  # minimum pack voltage candidate
    0x433C: bytes.fromhex("0320"),  # maximum pack voltage candidate
    0x432D: bytes.fromhex("02DC"),  # pack voltage candidate (~380 V by community scale)
    0x4356: bytes.fromhex("0000"),  # pack current candidate, zero on static bench
    0x43AF: bytes.fromhex("3200"),  # high-resolution SOC candidate fixture
    0x4369: bytes.fromhex("00"),    # charger input current candidate
    0x4368: bytes.fromhex("00"),    # charger input voltage candidate
    0x434F: bytes.fromhex("82"),    # battery temperature candidate fixture
    0x801F: bytes.fromhex("82"),    # ambient temperature candidate fixture
}

BLOCKED_SERVICES = {
    0x14,  # ClearDiagnosticInformation
    0x27,  # SecurityAccess
    0x28,  # CommunicationControl
    0x2E,  # WriteDataByIdentifier
    0x31,  # RoutineControl
    0x34,  # RequestDownload
    0x35,  # RequestUpload
    0x36,  # TransferData
    0x37,  # RequestTransferExit
    0x3D,  # WriteMemoryByAddress
    0x85,  # ControlDTCSetting
}


@dataclass(frozen=True)
class Decision:
    response: bytes | None
    classification: str
    detail: str = ""


def parse_single_frame(data: bytes) -> bytes | None:
    if not data:
        return None
    pci_type = data[0] >> 4
    if pci_type != 0:
        return None
    length = data[0] & 0x0F
    if length == 0 or length > 7 or len(data) < length + 1:
        return None
    return data[1 : 1 + length]


def encode_single_frame(payload: bytes) -> bytes:
    if not 1 <= len(payload) <= 7:
        raise ValueError("single-frame ISO-TP payload must be 1..7 bytes")
    return bytes((len(payload),)) + payload


def segment_isotp(payload: bytes) -> list[bytes]:
    """Return ISO-TP frames for a payload, excluding flow-control handling."""
    if not payload or len(payload) > 4095:
        raise ValueError("ISO-TP payload must be 1..4095 bytes")
    if len(payload) <= 7:
        return [encode_single_frame(payload)]
    length = len(payload)
    frames = [bytes((0x10 | ((length >> 8) & 0x0F), length & 0xFF)) + payload[:6]]
    offset = 6
    sequence = 1
    while offset < length:
        chunk = payload[offset : offset + 7]
        frames.append(bytes((0x20 | (sequence & 0x0F),)) + chunk)
        offset += len(chunk)
        sequence = (sequence + 1) & 0x0F
    return frames


def negative(service: int, nrc: int) -> bytes:
    return bytes((0x7F, service & 0xFF, nrc & 0xFF))


def decide_response(payload: bytes, *, vin: str = DEFAULT_VIN, dids=None) -> Decision:
    dids = DEFAULT_DIDS if dids is None else dids
    if not payload:
        return Decision(None, "malformed", "empty diagnostic payload")

    service = payload[0]

    if service in BLOCKED_SERVICES:
        nrc = 0x33 if service in {0x27, 0x2E, 0x31, 0x34, 0x35, 0x36, 0x37, 0x3D} else 0x11
        return Decision(negative(service, nrc), "blocked", f"service 0x{service:02X}")

    if service == 0x3E:  # TesterPresent
        if len(payload) < 2:
            return Decision(negative(service, 0x13), "malformed")
        subfunction = payload[1]
        if subfunction & 0x80:
            return Decision(None, "testerPresentSuppressed")
        return Decision(bytes((0x7E, subfunction & 0x7F)), "testerPresent")

    if service == 0x10:  # DiagnosticSessionControl
        if len(payload) < 2:
            return Decision(negative(service, 0x13), "malformed")
        subfunction = payload[1] & 0x7F
        if subfunction not in {0x01, 0x03}:
            return Decision(negative(service, 0x12), "unsupportedSession")
        # P2ServerMax=50 ms, P2*ServerMax=5 s (fixture values for bench behavior).
        return Decision(bytes((0x50, subfunction, 0x00, 0x32, 0x01, 0xF4)), "sessionControl")

    if service == 0x22:  # ReadDataByIdentifier
        if len(payload) < 3 or (len(payload) - 1) % 2:
            return Decision(negative(service, 0x13), "malformed")
        response = bytearray((0x62,))
        for offset in range(1, len(payload), 2):
            did = (payload[offset] << 8) | payload[offset + 1]
            if did == 0xF190:
                raw = vin.encode("ascii")
            else:
                raw = dids.get(did)
            if raw is None:
                return Decision(negative(service, 0x31), "unknownDid", f"0x{did:04X}")
            response.extend((payload[offset], payload[offset + 1]))
            response.extend(raw)
        return Decision(bytes(response), "readDid")

    if service == 0x19:  # ReadDTCInformation
        if len(payload) < 2:
            return Decision(negative(service, 0x13), "malformed")
        subfunction = payload[1]
        if subfunction == 0x01:  # reportNumberOfDTCByStatusMask
            return Decision(bytes((0x59, 0x01, 0xFF, 0x01, 0x00, 0x00)), "noDtcs")
        if subfunction == 0x02:  # reportDTCByStatusMask
            return Decision(bytes((0x59, 0x02, 0xFF)), "noDtcs")
        return Decision(negative(service, 0x12), "unsupportedDtcSubfunction")

    return Decision(negative(service, 0x11), "unsupportedService", f"0x{service:02X}")


def make_can_frame(can_id: int, data: bytes) -> VciCanObj:
    if len(data) > 8:
        raise ValueError("classic CAN frame payload exceeds 8 bytes")
    frame = VciCanObj()
    frame.ID = can_id
    frame.TimeStamp = 0
    frame.TimeFlag = 0
    frame.SendType = 0
    frame.RemoteFlag = 0
    frame.ExternFlag = 0
    frame.DataLen = len(data)
    for index, value in enumerate(data):
        frame.Data[index] = value
    return frame


def parse_stmin(value: int) -> float:
    if 0x00 <= value <= 0x7F:
        return value / 1000.0
    if 0xF1 <= value <= 0xF9:
        return (value - 0xF0) / 10000.0
    return 0.0


class JsonlLog:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("a", encoding="utf-8")

    def write(self, direction: str, can_id: int, data: bytes, **extra) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "direction": direction,
            "canId": f"0x{can_id:03X}",
            "data": data.hex().upper(),
            **extra,
        }
        self._handle.write(json.dumps(record, sort_keys=True) + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


def default_log_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path.home() / "Documents" / "OBD Atlas" / f"gds2_bench_{stamp}.jsonl"


def run_simulator(*, library_path: Path, device: int, channel: int, bitrate: int,
                  vin: str, timeout_seconds: float, log_path: Path) -> int:
    check_layouts()
    if len(vin) != 17 or not vin.isascii():
        raise ValueError("simulator VIN must contain exactly 17 ASCII characters")

    library = C.CDLL(str(library_path))
    u32 = C.c_uint32
    open_device = bind(library, "VCI_OpenDevice", [u32, u32, u32])
    close_device = bind(library, "VCI_CloseDevice", [u32, u32])
    init_can = bind(library, "VCI_InitCAN", [u32, u32, u32, C.POINTER(VciInitConfig)])
    start_can = bind(library, "VCI_StartCAN", [u32, u32, u32])
    reset_can = bind(library, "VCI_ResetCAN", [u32, u32, u32])
    receive = bind(library, "VCI_Receive", [u32, u32, u32, C.POINTER(VciCanObj), u32, C.c_int32])
    transmit = bind(library, "VCI_Transmit", [u32, u32, u32, C.POINTER(VciCanObj), u32])

    opened = False
    started = False
    logger = JsonlLog(log_path)
    unknown: dict[str, int] = {}
    deadline = None if timeout_seconds == 0 else time.monotonic() + timeout_seconds

    def tx(data: bytes) -> None:
        frame = make_can_frame(HPCM2_RESPONSE_ID, data)
        count = int(transmit(DEVICE_TYPE, device, channel, C.byref(frame), 1))
        if count != 1:
            raise RuntimeError(f"VCI_Transmit expected 1 frame, returned {count}")
        logger.write("tx", HPCM2_RESPONSE_ID, data)
        print(f"TX {HPCM2_RESPONSE_ID:03X}#{data.hex().upper()}", flush=True)

    def wait_for_flow_control() -> tuple[int, float]:
        frame = VciCanObj()
        fc_deadline = time.monotonic() + 1.0
        while time.monotonic() < fc_deadline:
            count = int(receive(DEVICE_TYPE, device, channel, C.byref(frame), 1, 100))
            if count == U32_ERROR:
                raise RuntimeError("VCI_Receive returned 0xFFFFFFFF while waiting for flow control")
            if count != 1:
                continue
            data = frame_bytes(frame)
            logger.write("rx", int(frame.ID), data)
            print(f"RX {frame.ID:03X}#{data.hex().upper()}", flush=True)
            if int(frame.ID) == HPCM2_REQUEST_ID and len(data) >= 3 and data[0] >> 4 == 3:
                flow_status = data[0] & 0x0F
                if flow_status != 0:
                    raise RuntimeError(f"unsupported ISO-TP flow status {flow_status}")
                return data[1], parse_stmin(data[2])
        raise RuntimeError("timed out waiting for ISO-TP flow control")

    def send_isotp(payload: bytes) -> None:
        frames = segment_isotp(payload)
        tx(frames[0])
        if len(frames) == 1:
            return
        block_size, delay = wait_for_flow_control()
        sent_in_block = 0
        for index, data in enumerate(frames[1:], start=1):
            if delay:
                time.sleep(delay)
            tx(data)
            sent_in_block += 1
            if block_size and sent_in_block >= block_size and index < len(frames) - 1:
                block_size, delay = wait_for_flow_control()
                sent_in_block = 0

    print("OBD Atlas GDS2 Bench Simulator", flush=True)
    print(f"UC2 device {device} CAN{channel} • {bitrate} bit/s • ACTIVE ISOLATED BENCH", flush=True)
    print(f"HPCM2 {HPCM2_REQUEST_ID:03X} -> {HPCM2_RESPONSE_ID:03X} • VIN {vin}", flush=True)
    print(f"Log: {log_path}", flush=True)
    print("Safe services: 10, 19, 22, 3E. Security/programming/write services are blocked.", flush=True)
    print("Start GDS2 now. Unknown requests will be logged for the next simulator revision.", flush=True)

    try:
        result = open_device(DEVICE_TYPE, device, 0)
        if result != 1:
            raise RuntimeError(f"VCI_OpenDevice failed: {result}")
        opened = True
        config = make_init_config(bitrate)
        result = init_can(DEVICE_TYPE, device, channel, C.byref(config))
        if result != 1:
            raise RuntimeError(f"VCI_InitCAN failed: {result}")
        result = start_can(DEVICE_TYPE, device, channel)
        if result != 1:
            raise RuntimeError(f"VCI_StartCAN failed: {result}")
        started = True

        frame = VciCanObj()
        while deadline is None or time.monotonic() < deadline:
            count = int(receive(DEVICE_TYPE, device, channel, C.byref(frame), 1, 100))
            if count == U32_ERROR:
                raise RuntimeError("VCI_Receive returned 0xFFFFFFFF")
            if count != 1:
                continue

            data = frame_bytes(frame)
            can_id = int(frame.ID)
            logger.write("rx", can_id, data)
            print(f"RX {can_id:03X}#{data.hex().upper()}", flush=True)

            if bool(frame.ExternFlag) or bool(frame.RemoteFlag) or can_id != HPCM2_REQUEST_ID:
                continue
            payload = parse_single_frame(data)
            if payload is None:
                key = f"{can_id:03X}#{data.hex().upper()}"
                unknown[key] = unknown.get(key, 0) + 1
                logger.write("event", can_id, data, classification="unsupportedRequestTransport")
                continue

            decision = decide_response(payload, vin=vin)
            logger.write(
                "decision",
                can_id,
                data,
                classification=decision.classification,
                detail=decision.detail,
                udsRequest=payload.hex().upper(),
                udsResponse=None if decision.response is None else decision.response.hex().upper(),
            )
            if decision.classification in {"unsupportedService", "unknownDid", "unsupportedDtcSubfunction"}:
                key = payload.hex().upper()
                unknown[key] = unknown.get(key, 0) + 1
            if decision.response is not None:
                send_isotp(decision.response)

    except KeyboardInterrupt:
        print("Simulator stopped by operator.", flush=True)
    finally:
        if unknown:
            print("Unknown/unsupported GDS2 requests observed:", flush=True)
            for request, count in sorted(unknown.items(), key=lambda item: (-item[1], item[0])):
                print(f"  {count:5d}  {request}", flush=True)
        if started:
            try:
                reset_can(DEVICE_TYPE, device, channel)
            except Exception:
                pass
        if opened:
            try:
                close_device(DEVICE_TYPE, device)
            except Exception:
                pass
        logger.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Isolated read-only GDS2 HPCM2 bench simulator.")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--channel", type=int, choices=(0, 1), default=1)
    parser.add_argument("--bitrate", type=int, choices=tuple(TIMING), default=500000)
    parser.add_argument("--vin", default=DEFAULT_VIN, help="Synthetic 17-character VIN returned for DID F190.")
    parser.add_argument("--timeout", type=float, default=0.0, help="Seconds to run; 0 means until Ctrl+C.")
    parser.add_argument("--log", type=Path, help="JSONL log destination.")
    parser.add_argument("--library")
    parser.add_argument("--confirm-isolated-bench", action="store_true")
    parser.add_argument("--check", action="store_true", help="Run simulator self-checks without hardware.")
    return parser


def self_check() -> None:
    check_layouts()
    assert parse_single_frame(bytes.fromhex("023E00")) == bytes.fromhex("3E00")
    assert decide_response(bytes.fromhex("3E00")).response == bytes.fromhex("7E00")
    assert decide_response(bytes.fromhex("22432D")).response == bytes.fromhex("62432D02DC")
    assert decide_response(bytes.fromhex("27 01")).classification == "blocked"
    assert len(segment_isotp(bytes.fromhex("62F190") + DEFAULT_VIN.encode("ascii"))) > 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check:
        self_check()
        print("GDS2 bench simulator self-check OK.")
        return 0
    if not args.confirm_isolated_bench:
        raise SystemExit(
            "refusing active simulator mode without --confirm-isolated-bench; keep the vehicle disconnected"
        )
    if sys.platform != "linux":
        raise SystemExit("GDS2 UC2 bench simulator requires Linux")
    if args.timeout < 0:
        raise SystemExit("--timeout must be >= 0")
    library_path = find_library(args.library)
    return run_simulator(
        library_path=library_path,
        device=args.device,
        channel=args.channel,
        bitrate=args.bitrate,
        vin=args.vin,
        timeout_seconds=args.timeout,
        log_path=args.log or default_log_path(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
