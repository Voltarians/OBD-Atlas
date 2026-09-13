#!/usr/bin/env python3
"""Isolated UC2 <-> VCX J2534 bench validation for PCG-1.

This is an intentionally narrow active-CAN test. It is NOT a vehicle-side
transmit utility. The tool opens one UC2 CAN controller in normal/active mode
so it can acknowledge valid CAN traffic, waits for the exact VCX probe

    CAN ID 0x7E4  data 02 3E 00

and replies once with

    CAN ID 0x7EC  data 02 7E 00

The probe/reply pair is UDS TesterPresent and its positive response. The exact
matching requirement and explicit --confirm-isolated-bench gate keep the tool
from becoming a general-purpose transmitter.

Keep the vehicle disconnected while using this tool.
"""

from __future__ import annotations

import argparse
import ctypes as C
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEVICE_TYPE = 4  # ZLG/LYS USBCAN2
U32_ERROR = 0xFFFFFFFF

TIMING = {
    125000: (0x03, 0x1C),
    250000: (0x01, 0x1C),
    500000: (0x00, 0x1C),
    800000: (0x00, 0x16),
    1000000: (0x00, 0x14),
}

VCX_REQUEST_ID = 0x7E4
VCX_REQUEST_DATA = bytes((0x02, 0x3E, 0x00))
ATLAS_RESPONSE_ID = 0x7EC
ATLAS_RESPONSE_DATA = bytes((0x02, 0x7E, 0x00))


class VciInitConfig(C.Structure):
    _fields_ = [
        ("AccCode", C.c_uint32),
        ("AccMask", C.c_uint32),
        ("Reserved", C.c_uint32),
        ("Filter", C.c_uint8),
        ("Timing0", C.c_uint8),
        ("Timing1", C.c_uint8),
        ("Mode", C.c_uint8),
    ]


class VciCanObj(C.Structure):
    _fields_ = [
        ("ID", C.c_uint32),
        ("TimeStamp", C.c_uint32),
        ("TimeFlag", C.c_uint8),
        ("SendType", C.c_uint8),
        ("RemoteFlag", C.c_uint8),
        ("ExternFlag", C.c_uint8),
        ("DataLen", C.c_uint8),
        ("Data", C.c_uint8 * 8),
        ("Reserved", C.c_uint8 * 3),
    ]


@dataclass(frozen=True)
class BenchResult:
    request_seen: bool
    response_sent: bool
    elapsed_seconds: float
    request_id: int | None = None
    request_data: bytes = b""

    @property
    def passed(self) -> bool:
        return self.request_seen and self.response_sent


def check_layouts() -> None:
    expected = (
        (VciInitConfig, 16, {"AccCode": 0, "Mode": 15}),
        (
            VciCanObj,
            24,
            {"ID": 0, "DataLen": 12, "Data": 13, "Reserved": 21},
        ),
    )
    for structure, size, offsets in expected:
        actual = C.sizeof(structure)
        if actual != size:
            raise RuntimeError(
                f"{structure.__name__}: unexpected size {actual}; expected {size}."
            )
        for field, offset in offsets.items():
            actual_offset = getattr(structure, field).offset
            if actual_offset != offset:
                raise RuntimeError(
                    f"{structure.__name__}.{field}: offset {actual_offset}; "
                    f"expected {offset}."
                )


def find_library(explicit: str | None = None) -> Path:
    home = Path.home()
    candidates = [
        explicit,
        os.environ.get("OBD_ATLAS_USBCAN_LIB"),
        str(home / "promethean/rust-can-zlg-lib/library/linux/aarch64/libusbcan.so"),
        "/usr/local/lib/libusbcan.so",
        "/usr/lib/aarch64-linux-gnu/libusbcan.so",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise FileNotFoundError(
        "ARM64 libusbcan.so not found; set OBD_ATLAS_USBCAN_LIB or use --library."
    )


def bind(library: C.CDLL, name: str, arguments: list[object], result=C.c_uint32):
    function = getattr(library, name)
    function.argtypes = arguments
    function.restype = result
    return function


def frame_bytes(frame: VciCanObj) -> bytes:
    length = min(int(frame.DataLen), 8)
    return bytes(frame.Data[:length])


def matches_vcx_probe(
    can_id: int,
    data: bytes | bytearray | Iterable[int],
    *,
    extended: bool = False,
    remote: bool = False,
) -> bool:
    return (
        not extended
        and not remote
        and can_id == VCX_REQUEST_ID
        and bytes(data) == VCX_REQUEST_DATA
    )


def make_response_frame() -> VciCanObj:
    frame = VciCanObj()
    frame.ID = ATLAS_RESPONSE_ID
    frame.TimeStamp = 0
    frame.TimeFlag = 0
    frame.SendType = 0
    frame.RemoteFlag = 0
    frame.ExternFlag = 0
    frame.DataLen = len(ATLAS_RESPONSE_DATA)
    for index, value in enumerate(ATLAS_RESPONSE_DATA):
        frame.Data[index] = value
    return frame


def make_init_config(bitrate: int) -> VciInitConfig:
    try:
        timing0, timing1 = TIMING[bitrate]
    except KeyError as error:
        raise ValueError(f"Unsupported UC2 bitrate: {bitrate}") from error

    config = VciInitConfig()
    config.AccCode = 0
    config.AccMask = 0xFFFFFFFF
    config.Reserved = 0
    config.Filter = 1
    config.Timing0 = timing0
    config.Timing1 = timing1
    config.Mode = 0  # normal/active CAN controller so the VCX receives ACKs
    return config


def run_bench(
    *,
    library_path: Path,
    device: int,
    channel: int,
    bitrate: int,
    timeout_seconds: float,
) -> BenchResult:
    check_layouts()
    if channel not in (0, 1):
        raise ValueError("UC2 physical channel must be 0 or 1.")
    if timeout_seconds <= 0:
        raise ValueError("Timeout must be greater than zero.")

    library = C.CDLL(str(library_path))
    u32 = C.c_uint32

    open_device = bind(library, "VCI_OpenDevice", [u32, u32, u32])
    close_device = bind(library, "VCI_CloseDevice", [u32, u32])
    init_can = bind(
        library,
        "VCI_InitCAN",
        [u32, u32, u32, C.POINTER(VciInitConfig)],
    )
    start_can = bind(library, "VCI_StartCAN", [u32, u32, u32])
    reset_can = bind(library, "VCI_ResetCAN", [u32, u32, u32])
    receive = bind(
        library,
        "VCI_Receive",
        [u32, u32, u32, C.POINTER(VciCanObj), u32, C.c_int32],
    )
    transmit = bind(
        library,
        "VCI_Transmit",
        [u32, u32, u32, C.POINTER(VciCanObj), u32],
    )

    opened = False
    started = False
    start = time.monotonic()

    print(
        f"UC2 device {device} CAN{channel} • {bitrate} bit/s • ACTIVE isolated bench",
        flush=True,
    )
    print(
        f"Waiting for VCX: {VCX_REQUEST_ID:03X}#"
        f"{VCX_REQUEST_DATA.hex().upper()}",
        flush=True,
    )
    print(
        f"Atlas reply:     {ATLAS_RESPONSE_ID:03X}#"
        f"{ATLAS_RESPONSE_DATA.hex().upper()}",
        flush=True,
    )

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

        print("ARMED — send the VCX J2534 probe now.", flush=True)

        frame = VciCanObj()
        deadline = start + timeout_seconds
        while time.monotonic() < deadline:
            count = int(
                receive(
                    DEVICE_TYPE,
                    device,
                    channel,
                    C.byref(frame),
                    1,
                    100,
                )
            )
            if count == U32_ERROR:
                raise RuntimeError("VCI_Receive returned 0xFFFFFFFF")
            if count != 1:
                continue

            data = frame_bytes(frame)
            print(
                f"RX {frame.ID:03X}#" + data.hex().upper(),
                flush=True,
            )
            if not matches_vcx_probe(
                int(frame.ID),
                data,
                extended=bool(frame.ExternFlag),
                remote=bool(frame.RemoteFlag),
            ):
                continue

            response = make_response_frame()
            tx_count = int(
                transmit(
                    DEVICE_TYPE,
                    device,
                    channel,
                    C.byref(response),
                    1,
                )
            )
            elapsed = time.monotonic() - start
            if tx_count != 1:
                raise RuntimeError(f"VCI_Transmit expected 1 frame, returned {tx_count}")

            print(
                f"TX {response.ID:03X}#"
                f"{frame_bytes(response).hex().upper()}",
                flush=True,
            )
            print("PASS — VCX -> UC2 receive/ACK and UC2 -> VCX response path verified.", flush=True)
            return BenchResult(
                request_seen=True,
                response_sent=True,
                elapsed_seconds=elapsed,
                request_id=int(frame.ID),
                request_data=data,
            )

        elapsed = time.monotonic() - start
        print("FAIL — timed out without the exact VCX probe.", flush=True)
        return BenchResult(
            request_seen=False,
            response_sent=False,
            elapsed_seconds=elapsed,
        )
    finally:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Atlas isolated UC2/VCX J2534 round-trip bench test."
    )
    parser.add_argument("--device", type=int, default=0, help="UC2 device index (default: 0).")
    parser.add_argument(
        "--channel",
        type=int,
        choices=(0, 1),
        default=1,
        help="UC2 physical CAN channel (default: CAN1 for the current PCG-1 passthrough bench).",
    )
    parser.add_argument(
        "--bitrate",
        type=int,
        choices=tuple(TIMING),
        default=500000,
        help="CAN bitrate (default: 500000).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Seconds to wait for the exact VCX probe (default: 60).",
    )
    parser.add_argument("--library", help="Explicit libusbcan.so path.")
    parser.add_argument(
        "--confirm-isolated-bench",
        action="store_true",
        help="Required safety gate confirming the UC2/VCX harness is disconnected from the vehicle.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate native structure layouts and exit without opening hardware.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.check:
        check_layouts()
        print("ControlCAN layouts OK.")
        return 0

    if not args.confirm_isolated_bench:
        parser.error(
            "refusing active CAN mode without --confirm-isolated-bench; "
            "disconnect the vehicle before running this test"
        )

    if sys.platform != "linux":
        parser.error("this UC2 bench test requires Linux")

    path = find_library(args.library)
    print(f"Library: {path}", flush=True)
    result = run_bench(
        library_path=path,
        device=args.device,
        channel=args.channel,
        bitrate=args.bitrate,
        timeout_seconds=args.timeout,
    )
    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
