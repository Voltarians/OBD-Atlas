#!/usr/bin/env python3
"""Receive-only five-bus radio/audio characterization for PCG-1.

Captures all five directly acquired Volt buses at once:
  can0 = UC2 device 0 CAN0
  can1 = UC2 device 0 CAN1
  can2 = UC2 device 1 CAN0
  can3 = UC2 device 1 CAN1
  can4 = RH02 SocketCAN SWCAN (Linux interface can0 by default)

The UC2 adapters are opened in the project-required order: device 1 then 0,
with CAN1 initialized/started before CAN0 on each device.

This utility never calls VCI_Transmit and never sends a SocketCAN frame.

IMPORTANT: the normal PCG-1 direct-state publisher owns the UC2 adapters.
Stop promethean-pcg1-direct-state.service before running this tool, then start
it again afterward.
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import os
import socket
import struct
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEVICE_TYPE = 4
U32_ERROR = 0xFFFFFFFF
TIMING_500K = (0x00, 0x1C)
CAN_EFF_MASK = 0x1FFFFFFF
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000

UC2_CHANNELS = (
    ("can3", 1, 1),
    ("can2", 1, 0),
    ("can1", 0, 1),
    ("can0", 0, 0),
)
DEVICE_OPEN_ORDER = (1, 0)
PER_DEVICE_CHANNEL_ORDER = (1, 0)

DEFAULT_SECONDS = 8.0
DEFAULT_SWCAN_INTERFACE = "can0"

SUGGESTED_LABELS = (
    "volume_up",
    "volume_down",
    "mute",
    "source",
    "seek_up",
    "seek_down",
    "tune_up",
    "tune_down",
    "preset_1",
    "preset_2",
    "steering_volume_up",
    "steering_volume_down",
    "steering_seek",
    "power",
)


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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def find_library(explicit: str | None) -> str:
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
            return candidate
    raise FileNotFoundError("ARM64 libusbcan.so not found; use --library PATH")


def bind(lib: C.CDLL, name: str, args: list[Any], result: Any = C.c_uint32):
    fn = getattr(lib, name)
    fn.argtypes = args
    fn.restype = result
    return fn


class FiveBusCapture:
    def __init__(self, library_path: str, swcan_interface: str):
        self.lib = C.CDLL(library_path)
        u32 = C.c_uint32
        self.open_device = bind(self.lib, "VCI_OpenDevice", [u32, u32, u32])
        self.close_device = bind(self.lib, "VCI_CloseDevice", [u32, u32])
        self.init_can = bind(
            self.lib,
            "VCI_InitCAN",
            [u32, u32, u32, C.POINTER(VciInitConfig)],
        )
        self.start_can = bind(self.lib, "VCI_StartCAN", [u32, u32, u32])
        self.reset_can = bind(self.lib, "VCI_ResetCAN", [u32, u32, u32])
        self.receive_num = bind(
            self.lib,
            "VCI_GetReceiveNum",
            [u32, u32, u32],
        )
        self.receive = bind(
            self.lib,
            "VCI_Receive",
            [u32, u32, u32, C.POINTER(VciCanObj), u32, C.c_int32],
        )
        self.swcan_interface = swcan_interface
        self.swcan: socket.socket | None = None
        self.opened: list[int] = []
        self.started: list[tuple[int, int]] = []

    def open(self) -> None:
        timing0, timing1 = TIMING_500K

        # Match the proven direct-state publisher sequence exactly:
        # 1) open BOTH native devices in required order 1 -> 0
        # 2) init CAN1 then CAN0 for each device
        # 3) start CAN1 then CAN0 for each device
        for device in DEVICE_OPEN_ORDER:
            result = self.open_device(DEVICE_TYPE, device, 0)
            if result != 1:
                raise RuntimeError(
                    f"VCI_OpenDevice(device={device}) returned {result}. "
                    "Stop promethean-pcg1-direct-state.service before running."
                )
            self.opened.append(device)

        init_sequence = [
            (device, channel)
            for device in DEVICE_OPEN_ORDER
            for channel in PER_DEVICE_CHANNEL_ORDER
        ]

        for device, channel in init_sequence:
            cfg = VciInitConfig(
                0,
                0xFFFFFFFF,
                0,
                1,
                timing0,
                timing1,
                1,  # listen-only
            )
            result = self.init_can(
                DEVICE_TYPE, device, channel, C.byref(cfg)
            )
            if result != 1:
                raise RuntimeError(
                    f"VCI_InitCAN(device={device}, channel={channel}) "
                    f"returned {result}"
                )

        for device, channel in init_sequence:
            result = self.start_can(DEVICE_TYPE, device, channel)
            if result != 1:
                raise RuntimeError(
                    f"VCI_StartCAN(device={device}, channel={channel}) "
                    f"returned {result}"
                )
            self.started.append((device, channel))

        self.swcan = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        self.swcan.bind((self.swcan_interface,))
        self.swcan.setblocking(False)

    def close(self) -> None:
        if self.swcan is not None:
            try:
                self.swcan.close()
            finally:
                self.swcan = None

        for device, channel in reversed(self.started):
            try:
                self.reset_can(DEVICE_TYPE, device, channel)
            except Exception:
                pass
        self.started.clear()

        for device in reversed(self.opened):
            try:
                self.close_device(DEVICE_TYPE, device)
            except Exception:
                pass
        self.opened.clear()

    def capture(self, seconds: float) -> dict[str, dict[int, list[bytes]]]:
        frames: dict[str, dict[int, list[bytes]]] = {
            name: defaultdict(list)
            for name in ("can0", "can1", "can2", "can3", "can4")
        }

        buffer = (VciCanObj * 1)()
        deadline = time.monotonic() + seconds

        while time.monotonic() < deadline:
            activity = False

            for logical, device, channel in UC2_CHANNELS:
                drained = 0
                while drained < 64:
                    pending = self.receive_num(
                        DEVICE_TYPE, device, channel
                    )
                    if pending == U32_ERROR:
                        raise RuntimeError(
                            f"VCI_GetReceiveNum failed on {logical} "
                            f"(device={device}, channel={channel})"
                        )
                    if pending == 0:
                        break

                    # Match the proven PCG-1 publisher receive path exactly:
                    # one frame per native call with a positive timeout.
                    received = self.receive(
                        DEVICE_TYPE,
                        device,
                        channel,
                        buffer,
                        1,
                        100,
                    )
                    if received == U32_ERROR:
                        raise RuntimeError(
                            f"VCI_Receive failed on {logical} "
                            f"(device={device}, channel={channel})"
                        )
                    if received != 1:
                        break

                    frame = buffer[0]
                    drained += 1
                    if frame.RemoteFlag or frame.ExternFlag or frame.DataLen > 8:
                        continue

                    dlc = min(int(frame.DataLen), 8)
                    frames[logical][int(frame.ID) & 0x7FF].append(
                        bytes(frame.Data[:dlc])
                    )
                    activity = True

            if self.swcan is not None:
                while True:
                    try:
                        raw = self.swcan.recv(16)
                    except BlockingIOError:
                        break
                    if len(raw) < 16:
                        continue
                    can_id_raw, dlc, data = struct.unpack("=IB3x8s", raw)
                    if can_id_raw & (CAN_RTR_FLAG | CAN_ERR_FLAG):
                        continue
                    can_id = can_id_raw & CAN_EFF_MASK
                    frames["can4"][can_id].append(
                        bytes(data[: min(int(dlc), 8)])
                    )
                    activity = True

            if not activity:
                time.sleep(0.001)

        return {
            bus: dict(values)
            for bus, values in frames.items()
        }


def summarize(samples: list[bytes]) -> dict[str, Any]:
    counts = Counter(samples)
    most_common, most_common_count = counts.most_common(1)[0]
    return {
        "count": len(samples),
        "unique_payloads": len(counts),
        "most_common": most_common,
        "most_common_count": most_common_count,
        "variants": [
            {"payload": payload.hex().upper(), "count": count}
            for payload, count in counts.most_common(8)
        ],
    }


def byte_diffs(a: bytes, b: bytes) -> list[dict[str, int]]:
    out: list[dict[str, int]] = []
    for i in range(max(len(a), len(b))):
        av = a[i] if i < len(a) else -1
        bv = b[i] if i < len(b) else -1
        if av != bv:
            out.append({
                "byte": i,
                "baseline": av,
                "action": bv,
                "xor": (av ^ bv) & 0xFF if av >= 0 and bv >= 0 else -1,
            })
    return out


def compare(
    baseline: dict[str, dict[int, list[bytes]]],
    action: dict[str, dict[int, list[bytes]]],
) -> list[dict[str, Any]]:
    changed: list[dict[str, Any]] = []

    for bus in ("can0", "can1", "can2", "can3", "can4"):
        ids = sorted(set(baseline[bus]) | set(action[bus]))

        for can_id in ids:
            before = baseline[bus].get(can_id)
            after = action[bus].get(can_id)

            if before is None:
                a = summarize(after or [])
                changed.append({
                    "bus": bus,
                    "can_id": f"0x{can_id:08X}",
                    "status": "appeared",
                    "action_count": a["count"],
                    "action_variants": a["variants"],
                })
                continue

            if after is None:
                b = summarize(before)
                changed.append({
                    "bus": bus,
                    "can_id": f"0x{can_id:08X}",
                    "status": "disappeared",
                    "baseline_count": b["count"],
                    "baseline_variants": b["variants"],
                })
                continue

            b = summarize(before)
            a = summarize(after)
            diffs = byte_diffs(b["most_common"], a["most_common"])
            count_delta = a["count"] - b["count"]
            unique_delta = a["unique_payloads"] - b["unique_payloads"]

            if diffs or count_delta or unique_delta:
                changed.append({
                    "bus": bus,
                    "can_id": f"0x{can_id:08X}",
                    "status": "changed",
                    "baseline_payload": b["most_common"].hex().upper(),
                    "action_payload": a["most_common"].hex().upper(),
                    "baseline_count": b["count"],
                    "action_count": a["count"],
                    "count_delta": count_delta,
                    "baseline_unique_payloads": b["unique_payloads"],
                    "action_unique_payloads": a["unique_payloads"],
                    "unique_payload_delta": unique_delta,
                    "byte_diffs": diffs,
                    "baseline_variants": b["variants"],
                    "action_variants": a["variants"],
                })

    changed.sort(
        key=lambda item: (
            -len(item.get("byte_diffs", [])),
            -abs(item.get("unique_payload_delta", 0)),
            -abs(item.get("count_delta", 0)),
            item["bus"],
            item["can_id"],
        )
    )
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    ap.add_argument("--label", default="radio_action")
    ap.add_argument("--library")
    ap.add_argument("--swcan-interface", default=DEFAULT_SWCAN_INTERFACE)
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=Path("evidence/radio"),
    )
    ap.add_argument("--show-labels", action="store_true")
    args = ap.parse_args()

    if args.show_labels:
        print("\n".join(SUGGESTED_LABELS))
        return 0
    if args.seconds <= 0:
        ap.error("--seconds must be positive")

    library_path = find_library(args.library)
    rig = FiveBusCapture(library_path, args.swcan_interface)

    try:
        print("Opening UC2 devices in required order 1 -> 0...")
        print("Initializing CAN1 before CAN0 on each UC2 device...")
        print("Receive-only: no transmit functions are bound or called.")
        rig.open()

        print(f"Capturing five-bus RADIO BASELINE for {args.seconds:.1f}s...")
        baseline = rig.capture(args.seconds)

        for bus in ("can0", "can1", "can2", "can3", "can4"):
            count = sum(len(v) for v in baseline[bus].values())
            print(f"  {bus}: {count} frames / {len(baseline[bus])} IDs")

        input(
            "\nPerform ONE physical radio/audio action, then press Enter "
            "to capture the changed state..."
        )

        print(f"Capturing five-bus RADIO ACTION for {args.seconds:.1f}s...")
        action = rig.capture(args.seconds)

        for bus in ("can0", "can1", "can2", "can3", "can4"):
            count = sum(len(v) for v in action[bus].values())
            print(f"  {bus}: {count} frames / {len(action[bus])} IDs")

    finally:
        rig.close()

    changed = compare(baseline, action)

    print("\n===== FIVE-BUS RADIO CHARACTERIZATION RESULT =====")
    if not changed:
        print("No changed CAN IDs detected.")
    else:
        for item in changed[:80]:
            print(f"{item['bus']} {item['can_id']} {item['status']}")
            if item["status"] == "changed":
                print(f"  baseline: {item['baseline_payload']}")
                print(f"  action:   {item['action_payload']}")
                for d in item["byte_diffs"]:
                    print(
                        f"  byte {d['byte']}: "
                        f"{d['baseline']:02X} -> {d['action']:02X} "
                        f"(xor {d['xor']:02X})"
                    )
                if item["unique_payload_delta"]:
                    print(
                        f"  unique-payload delta: "
                        f"{item['unique_payload_delta']:+d}"
                    )
                if item["count_delta"]:
                    print(f"  frame-count delta: {item['count_delta']:+d}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = args.output_dir / f"{stamp}_{args.label}_five_bus.json"
    doc = {
        "schema": "promethean.radio.characterization.five_bus.v1",
        "created_utc": utc_now(),
        "capture_seconds": args.seconds,
        "label": args.label,
        "receive_only": True,
        "buses": {
            "can0": "uc2_device0_can0",
            "can1": "uc2_device0_can1",
            "can2": "uc2_device1_can0",
            "can3": "uc2_device1_can1",
            "can4": f"socketcan_{args.swcan_interface}_swcan",
        },
        "uc2_open_order": "1->0",
        "uc2_channel_init_order": "CAN1->CAN0 per device",
        "changed": changed,
    }
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"\nSaved evidence: {out}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
    except (OSError, RuntimeError, AttributeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
