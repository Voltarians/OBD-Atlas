#!/usr/bin/env python3
"""Publish evidence-backed direct PCG-1 CAN values for Promethean Core.

This process reads SocketCAN directly from the vehicle networks already wired to
PCG-1. It does not use an ELM/STN/vLinker adapter and it does not transmit CAN.

Validated/currently accepted inputs:
- Primary HS GMLAN: APM command/status 0x1D4 and APM stats 0x1D6.
- HV Energy Management: 0x210 pack voltage, 0x200/202/204/206 96 passive
  battery-voltage measurement slots, and 0x302 nine battery temperatures.

Candidate pack current, ambiguous charger fields, and unvalidated semantics are
deliberately not promoted into the Core state file.
"""

from __future__ import annotations

import argparse
import json
import os
import selectors
import socket
import struct
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_STATE_FILE = Path("/run/promethean/vehicle_state.json")
DEFAULT_PRIMARY = "can3"
DEFAULT_HV = "can0"

CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_SFF_MASK = 0x000007FF

CELL_IDS = {0x200: 0, 0x202: 1, 0x204: 2, 0x206: 3}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _motorola(data: bytes, start_bit: int, length: int, *, signed: bool = False) -> int:
    bit = start_bit
    value = 0
    for _ in range(length):
        byte_index = bit // 8
        bit_index = bit % 8
        if byte_index >= len(data):
            raise ValueError("signal exceeds payload")
        value = (value << 1) | ((data[byte_index] >> bit_index) & 1)
        bit = bit + 15 if bit_index == 0 else bit - 1
    if signed and value & (1 << (length - 1)):
        value -= 1 << length
    return value


def _signed8(value: int) -> int:
    return value - 256 if value & 0x80 else value


def decode_apm_command(data: bytes) -> dict[str, Any]:
    if len(data) < 2:
        return {}
    requested_v = data[1] * (10.0 / 127.0)
    return {
        "apm_status_raw": int(data[0]),
        "apm_requested_voltage_v": round(requested_v, 3),
        "apm_command_updated_utc": _utc_now(),
    }


def decode_apm_stats(data: bytes) -> dict[str, Any]:
    if len(data) < 7:
        return {}
    # Project-validated DBC candidates from the primary DLC 6/14 path.
    hv_input_current_a = _signed8(data[1]) * 0.1 - 5.0
    lv_sensed_voltage_v = float(data[2])
    temp1_c = float(data[3]) - 40.0
    temp2_c = float(data[4]) - 40.0
    lv_output_current_a = float(_signed8(data[5]))
    return {
        "apm_status_raw": int(data[0]),
        "apm_hv_input_current_a": round(hv_input_current_a, 3),
        "apm_output_voltage_v": round(lv_sensed_voltage_v, 3),
        "apm_current_a": round(lv_output_current_a, 3),
        "apm_temperature_c": round(max(temp1_c, temp2_c), 3),
        "apm_temperature_1_c": round(temp1_c, 3),
        "apm_temperature_2_c": round(temp2_c, 3),
        "apm_counter_raw": int(data[6]),
        "apm_stats_updated_utc": _utc_now(),
    }


def decode_pack_voltage(data: bytes) -> dict[str, Any]:
    if len(data) < 2:
        return {}
    voltage = _motorola(data, 7, 12) * 0.125
    return {
        "hv_pack_voltage_v": round(voltage, 3),
        "hv_pack_voltage_updated_utc": _utc_now(),
    }


def decode_cell_block(can_id: int, data: bytes) -> dict[int, float]:
    if can_id not in CELL_IDS or len(data) < 8:
        return {}
    bank = _motorola(data, 55, 3)
    block = CELL_IDS[can_id]
    values = (
        _motorola(data, 4, 12) * 0.00125,
        _motorola(data, 20, 12) * 0.00125,
        _motorola(data, 39, 12) * 0.00125,
    )
    slot_base = block * 24 + bank * 3
    return {slot_base + i: round(v, 5) for i, v in enumerate(values)}


def decode_battery_temps(data: bytes) -> dict[str, float]:
    if len(data) < 8:
        return {}
    mux = (data[0] >> 2) & 0x01
    raw = data[1:7] if mux == 0 else data[1:4]
    offset = 0 if mux == 0 else 6
    return {
        f"battery_temp_slot_{offset + i + 1}_c": round(byte * 0.5 - 40.0, 3)
        for i, byte in enumerate(raw)
    }


def _read_existing(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _atomic_write(path: Path, updates: dict[str, Any]) -> None:
    raw = _read_existing(path)
    target = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    target.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(raw, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


class DirectStatePublisher:
    def __init__(self, primary: str, hv: str, state_file: Path) -> None:
        self.primary_name = primary
        self.hv_name = hv
        self.state_file = state_file
        self.selector = selectors.DefaultSelector()
        self.cells: dict[int, float] = {}
        self.temps: dict[str, float] = {}
        self.sockets: list[socket.socket] = []

    def _open_can(self, interface: str, role: str) -> None:
        sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        sock.bind((interface,))
        sock.setblocking(False)
        self.selector.register(sock, selectors.EVENT_READ, role)
        self.sockets.append(sock)

    def start(self) -> None:
        self._open_can(self.primary_name, "primary")
        if self.hv_name != self.primary_name:
            self._open_can(self.hv_name, "hv")

    def close(self) -> None:
        for sock in self.sockets:
            try:
                self.selector.unregister(sock)
            except Exception:
                pass
            sock.close()
        self.selector.close()

    def _publish_battery_summary(self) -> None:
        updates: dict[str, Any] = {}
        if len(self.cells) == 96:
            values = list(self.cells.values())
            lo = min(values)
            hi = max(values)
            updates.update({
                "hv_cell_measurement_slots_complete": 96,
                "hv_cell_min_v": round(lo, 5),
                "hv_cell_max_v": round(hi, 5),
                "hv_cell_delta_mv": round((hi - lo) * 1000.0, 2),
                "hv_cell_slots_v": [self.cells[i] for i in range(96)],
                "hv_cell_slots_updated_utc": _utc_now(),
            })
        if len(self.temps) == 9:
            vals = list(self.temps.values())
            updates.update({
                "hv_temp_min_c": round(min(vals), 3),
                "hv_temp_max_c": round(max(vals), 3),
                "hv_temperature_slots_c": [self.temps[f"battery_temp_slot_{i}_c"] for i in range(1, 10)],
                "hv_temperature_slots_updated_utc": _utc_now(),
            })
        if updates:
            _atomic_write(self.state_file, updates)

    def _handle(self, role: str, can_id: int, data: bytes) -> None:
        updates: dict[str, Any] = {}
        if role == "primary":
            if can_id == 0x1D4:
                updates.update(decode_apm_command(data))
            elif can_id == 0x1D6:
                updates.update(decode_apm_stats(data))
        elif role == "hv":
            if can_id == 0x210:
                updates.update(decode_pack_voltage(data))
            elif can_id in CELL_IDS:
                self.cells.update(decode_cell_block(can_id, data))
                self._publish_battery_summary()
            elif can_id == 0x302:
                self.temps.update(decode_battery_temps(data))
                self._publish_battery_summary()
        if updates:
            updates["direct_can_updated_utc"] = _utc_now()
            _atomic_write(self.state_file, updates)

    def run_forever(self) -> None:
        self.start()
        print(
            f"PCG-1 direct state publisher: primary={self.primary_name} hv={self.hv_name}",
            flush=True,
        )
        try:
            while True:
                for key, _ in self.selector.select(timeout=1.0):
                    sock = key.fileobj
                    role = key.data
                    try:
                        frame = sock.recv(16)
                    except BlockingIOError:
                        continue
                    if len(frame) < 16:
                        continue
                    can_id_raw, dlc, payload = struct.unpack("=IB3x8s", frame)
                    if can_id_raw & (CAN_EFF_FLAG | CAN_RTR_FLAG | CAN_ERR_FLAG):
                        continue
                    can_id = can_id_raw & CAN_SFF_MASK
                    data = payload[: min(int(dlc), 8)]
                    self._handle(role, can_id, data)
        finally:
            self.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-interface", default=DEFAULT_PRIMARY)
    parser.add_argument("--hv-interface", default=DEFAULT_HV)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    args = parser.parse_args(argv)

    DirectStatePublisher(
        primary=args.primary_interface,
        hv=args.hv_interface,
        state_file=args.state_file,
    ).run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
