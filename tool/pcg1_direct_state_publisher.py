#!/usr/bin/env python3
"""Publish evidence-backed direct PCG-1 vehicle values for Promethean Core.

PCG-1 uses a mixed receive backend:
- Atlas logical can0..can3: two dual-channel LYS/UC2 USBCAN2 adapters through
  the verified ARM64 libusbcan.so receive API.
- Atlas logical can4: RH02/candleLight SWCAN through Linux SocketCAN can0.
- Five physical vehicle buses are directly acquired by PCG-1: four 500 kbit/s
  classic CAN buses plus one 33,333 bit/s SWCAN bus.
- A sixth known vehicle bus exists internally: the 125 kbit/s BICM/BECM
  internal CAN. It is hidden from the current five-bus PCG-1 acquisition path
  and is not counted as a sixth directly acquired interface.
- PCG-1 also retains a reserved CAN-capable channel in the hardware
  architecture; that reserved channel is not the hidden BICM bus.

This process is receive-only. It never calls VCI_Transmit and never sends a
SocketCAN frame.
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import os
import socket
import struct
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_STATE_FILE = Path("/run/promethean/vehicle_state.json")
DEFAULT_UC2_LIBRARY = Path.home() / "promethean/rust-can-zlg-lib/library/linux/aarch64/libusbcan.so"
DEFAULT_SWCAN_INTERFACE = "can0"

# Atlas logical names are retained so existing evidence, captures and signal
# mappings do not change when the acquisition backend changes.
UC2_LOGICAL_CHANNELS = (
    ("can0", 0, 0),
    ("can1", 0, 1),
    ("can2", 1, 0),
    ("can3", 1, 1),
)
SWCAN_LOGICAL_CHANNEL = "can4"
RESERVED_CAN_CHANNEL = "can5"
CURRENT_PHYSICAL_VEHICLE_BUSES_EXPECTED = 5
CURRENT_500K_PHYSICAL_BUSES_EXPECTED = 4
CURRENT_SWCAN_PHYSICAL_BUSES_EXPECTED = 1
KNOWN_HIDDEN_INTERNAL_BUSES = 1
TOTAL_KNOWN_VEHICLE_BUSES = 6
HIDDEN_INTERNAL_BUS_NAME = "bicm_internal_125k"
CAN_CAPABLE_CHANNEL_COUNT = 6
FUTURE_LIN_INTERFACES = ("lin0", "lin1", "lin2")
PHYSICAL_BUS_ROLES = {
    "can0": "high_voltage_energy_management",
    "can1": "high_voltage_powertrain_expansion",
    "can2": "chassis_expansion",
    "can3": "primary_powertrain",
    "can4": "body_electrical_swcan",
}

DEFAULT_PRIMARY_INTERFACE = "can3"
DEFAULT_HV_INTERFACE = "can2"

DEVICE_TYPE = 4  # ZLG/LYS USBCAN2
U32_ERROR = 0xFFFFFFFF
UC2_RECEIVE_BURST_LIMIT = 64
UC2_RECEIVE_WAIT_MS = 100
TIMING_500K = (0x00, 0x1C)
UC2_OPEN_ORDERS = ((0, 1), (1, 0))
HEALTH_WARMUP_SECONDS = 15.0
UC2_RUNTIME_RECOVERY_LIMIT = 1


class PartialUc2TrafficError(RuntimeError):
    """Raised when in-process UC2 recovery cannot restore all four channels."""

CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_SFF_MASK = 0x000007FF

CELL_IDS = {0x200: 0, 0x202: 1, 0x204: 2, 0x206: 3}

# Logical-network classification is intentionally independent of the physical
# acquisition channel. Only ID families already validated by this project are
# classified here. The hidden 125 kbit/s BICM/BECM internal CAN is modeled
# separately from the five directly acquired physical buses.
PRIMARY_POWERTRAIN_IDS = frozenset({0x1D4, 0x1D6})
HV_ENERGY_MANAGEMENT_IDS = frozenset({0x200, 0x202, 0x204, 0x206, 0x210, 0x302})
SOURCE_EVIDENCE_IDS = tuple(sorted(PRIMARY_POWERTRAIN_IDS | HV_ENERGY_MANAGEMENT_IDS))
LOGICAL_NETWORKS = (
    "primary_powertrain",
    "hv_energy_management",
    "swcan",
    "bicm_internal_125k",
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


def classify_logical_network(interface: str, can_id: int) -> str | None:
    """Return only evidence-backed logical-network classifications."""
    if interface == SWCAN_LOGICAL_CHANNEL:
        return "swcan"
    if can_id in PRIMARY_POWERTRAIN_IDS:
        return "primary_powertrain"
    if can_id in HV_ENERGY_MANAGEMENT_IDS:
        return "hv_energy_management"
    return None


def decode_apm_command(data: bytes) -> dict[str, Any]:
    if len(data) < 2:
        return {}
    requested_v = data[1] * 0.0787402
    state_raw = int(data[0])
    state = "OFF" if state_raw == 0 else "ON" if state_raw == 160 else f"RAW_0x{state_raw:02X}"
    return {
        "apm_status_raw": state_raw,
        "apm_state": state,
        "apm_requested_voltage_v": round(requested_v, 3),
        "apm_command_updated_utc": _utc_now(),
    }


def decode_apm_stats(data: bytes) -> dict[str, Any]:
    if len(data) < 7:
        return {}
    hv_input_current_a = _signed8(data[1]) * 0.15 - 7.0
    lv_sensed_voltage_v = data[2] * 0.0787402
    temp1_c = float(data[3]) - 40.0
    temp2_c = float(data[4]) - 40.0
    lv_output_current_a = float(_signed8(data[5]))
    return {
        "apm_status_raw": int(data[0]),
        "apm_hv_input_current_a": round(hv_input_current_a, 3),
        "apm_output_voltage_v": round(lv_sensed_voltage_v, 3),
        "bus12_voltage_v": round(lv_sensed_voltage_v, 3),
        "bus12_voltage_source": "apm_0x1d6_low_voltage_sensed",
        "apm_current_a": round(lv_output_current_a, 3),
        "apm_power_w": round(lv_sensed_voltage_v * lv_output_current_a, 3),
        "apm_temperature_c": round(max(temp1_c, temp2_c), 3),
        "apm_temperature_1_c": round(temp1_c, 3),
        "apm_temperature_2_c": round(temp2_c, 3),
        "apm_counter_raw": int(data[6]),
        "apm_stats_updated_utc": _utc_now(),
    }


def decode_legacy_accelerator(data: bytes) -> dict[str, Any]:
    if len(data) < 5:
        return {}
    raw = int(data[4])
    rpm_raw = ((int(data[1]) << 8) | int(data[2])) >> 2
    return {
        "accelerator_raw": raw,
        "accelerator_pct": round(raw * 100.0 / 254.0, 3),
        "vehicle_on": (int(data[0]) & 0xC0) != 0,
        "motor_rpm": rpm_raw,
        "accelerator_updated_utc": _utc_now(),
        "vehicle_on_updated_utc": _utc_now(),
        "motor_rpm_updated_utc": _utc_now(),
    }


def decode_legacy_brake(data: bytes) -> dict[str, Any]:
    if len(data) < 2:
        return {}
    return {
        "brake_raw": int(data[1]),
        "brake_updated_utc": _utc_now(),
    }


def decode_legacy_drive_position(data: bytes) -> dict[str, Any]:
    if len(data) < 1:
        return {}
    raw = int(data[0])
    state = {
        0: "PARK",
        1: "NEUTRAL",
        2: "DRIVE_OR_LOW",
        3: "REVERSE",
    }.get(raw, f"RAW_0x{raw:02X}")
    return {
        "drive_position_raw": raw,
        "drive_position": state,
        "drive_position_updated_utc": _utc_now(),
    }


def decode_legacy_shift_position(data: bytes) -> dict[str, Any]:
    if len(data) < 4:
        return {}
    raw = int(data[3])
    state = {
        1: "PARK",
        2: "REVERSE",
        3: "NEUTRAL",
        4: "DRIVE",
        5: "LOW",
    }.get(raw, f"RAW_0x{raw:02X}")
    return {
        "shift_position_raw": raw,
        "shift_position": state,
        "shift_position_updated_utc": _utc_now(),
    }


def decode_legacy_vehicle_speed(data: bytes) -> dict[str, Any]:
    if len(data) < 2:
        return {}
    raw = (int(data[0]) << 8) | int(data[1])
    return {
        "vehicle_speed_raw": raw,
        "vehicle_speed_mph": round(raw / 100.0, 2),
        "vehicle_speed_updated_utc": _utc_now(),
    }


def decode_legacy_odometer(data: bytes) -> dict[str, Any]:
    if len(data) < 4:
        return {}
    raw = (
        (int(data[0]) << 24)
        | (int(data[1]) << 16)
        | (int(data[2]) << 8)
        | int(data[3])
    )
    return {
        "odometer_raw": raw,
        "odometer_miles": round(raw / 64.0, 3),
        "odometer_updated_utc": _utc_now(),
    }


def decode_legacy_ambient_coolant(data: bytes) -> dict[str, Any]:
    if len(data) < 5:
        return {}
    return {
        "ambient_temperature_c": round(int(data[4]) / 2.0 - 40.0, 3),
        "coolant_temperature_c": round(float(int(data[2]) - 40), 3),
        "ambient_coolant_updated_utc": _utc_now(),
    }


def decode_pack_voltage(data: bytes) -> dict[str, Any]:
    if len(data) < 2:
        return {}
    return {
        "hv_pack_voltage_v": round(_motorola(data, 7, 12) * 0.125, 3),
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
    return {slot_base + i: round(value, 5) for i, value in enumerate(values)}


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


def _bind(library: C.CDLL, name: str, args: list[Any], result: Any = C.c_uint32):
    fn = getattr(library, name)
    fn.argtypes = args
    fn.restype = result
    return fn


class DirectStatePublisher:
    def __init__(
        self,
        state_file: Path,
        uc2_library: Path,
        swcan_interface: str = DEFAULT_SWCAN_INTERFACE,
        primary_interface: str = DEFAULT_PRIMARY_INTERFACE,
        hv_interface: str = DEFAULT_HV_INTERFACE,
    ) -> None:
        self.state_file = state_file
        self.uc2_library_path = uc2_library
        self.swcan_interface = swcan_interface
        self.primary_interface = primary_interface
        self.hv_interface = hv_interface
        self.cells: dict[int, float] = {}
        self.temps: dict[str, float] = {}
        self.pending: dict[str, Any] = {}

        logical = [name for name, _, _ in UC2_LOGICAL_CHANNELS] + [SWCAN_LOGICAL_CHANNEL]
        self.bus_frames = {name: 0 for name in logical}
        self.bus_ids = {name: set() for name in logical}
        self.bus_id_frames = {name: {} for name in logical}
        self.bus_last_seen: dict[str, str] = {}
        self.bus_available = {name: False for name in logical}
        self.bus_available[RESERVED_CAN_CHANNEL] = False
        self.logical_network_frames = {name: 0 for name in LOGICAL_NETWORKS}
        self.logical_network_last_seen: dict[str, str] = {}
        self.unclassified_frames = 0
        self.id_source_frames = {
            can_id: {name: 0 for name in logical}
            for can_id in SOURCE_EVIDENCE_IDS
        }

        self.library: C.CDLL | None = None
        self.opened_devices: list[int] = []
        self.uc2_open_order: tuple[int, int] | None = None
        self.uc2_runtime_recovery_count = 0
        self.uc2_runtime_recovery_reason: str | None = None
        self.uc2_buffers = {
            name: VciCanObj()
            for name, _, _ in UC2_LOGICAL_CHANNELS
        }
        self.swcan_socket: socket.socket | None = None
        self.started_monotonic = time.monotonic()

    def _open_uc2(
        self,
        open_orders: tuple[tuple[int, int], ...] = UC2_OPEN_ORDERS,
    ) -> None:
        if not self.uc2_library_path.is_file():
            raise RuntimeError(f"UC2 library not found: {self.uc2_library_path}")

        if C.sizeof(VciInitConfig) != 16 or C.sizeof(VciCanObj) != 24:
            raise RuntimeError("unexpected ControlCAN ctypes layout")

        self.library = C.CDLL(str(self.uc2_library_path))
        u32 = C.c_uint32
        self.open_device = _bind(self.library, "VCI_OpenDevice", [u32, u32, u32])
        self.close_device = _bind(self.library, "VCI_CloseDevice", [u32, u32])
        self.init_can = _bind(
            self.library,
            "VCI_InitCAN",
            [u32, u32, u32, C.POINTER(VciInitConfig)],
        )
        self.start_can = _bind(self.library, "VCI_StartCAN", [u32, u32, u32])
        self.reset_can = _bind(self.library, "VCI_ResetCAN", [u32, u32, u32])
        self.receive_num = _bind(self.library, "VCI_GetReceiveNum", [u32, u32, u32])
        self.receive = _bind(
            self.library,
            "VCI_Receive",
            [u32, u32, u32, C.POINTER(VciCanObj), u32, C.c_int32],
        )

        # The vendor library's native device indices are not stable enough to
        # assume that device 0 must always be opened first. Atlas has recovered
        # a five-bus session after device 0 failed and device 1 was selected.
        # Keep the physical/logical mapping fixed, but try both native open
        # orders before giving up.
        last_error: RuntimeError | None = None
        for open_order in open_orders:
            self.opened_devices.clear()
            try:
                for device in open_order:
                    if self.open_device(DEVICE_TYPE, device, 0) != 1:
                        raise RuntimeError(
                            f"VCI_OpenDevice failed for UC2 device {device} "
                            f"using order {open_order[0]}->{open_order[1]}"
                        )
                    self.opened_devices.append(device)

                timing0, timing1 = TIMING_500K
                for _name, device, channel in UC2_LOGICAL_CHANNELS:
                    config = VciInitConfig(
                        0, 0xFFFFFFFF, 0, 1, timing0, timing1, 1
                    )
                    if (
                        self.init_can(
                            DEVICE_TYPE, device, channel, C.byref(config)
                        )
                        != 1
                    ):
                        raise RuntimeError(
                            f"VCI_InitCAN failed for UC2 device {device} "
                            f"CAN{channel} using order "
                            f"{open_order[0]}->{open_order[1]}"
                        )

                for name, device, channel in UC2_LOGICAL_CHANNELS:
                    if self.start_can(DEVICE_TYPE, device, channel) != 1:
                        raise RuntimeError(
                            f"VCI_StartCAN failed for UC2 device {device} "
                            f"CAN{channel} using order "
                            f"{open_order[0]}->{open_order[1]}"
                        )
                    self.bus_available[name] = True

                self.uc2_open_order = open_order
                print(
                    "PCG-1 direct state publisher: UC2 native open order "
                    f"{open_order[0]}->{open_order[1]} succeeded",
                    flush=True,
                )
                return
            except RuntimeError as error:
                last_error = error
                for device in reversed(self.opened_devices):
                    for channel in (1, 0):
                        try:
                            self.reset_can(DEVICE_TYPE, device, channel)
                        except Exception:
                            pass
                    try:
                        self.close_device(DEVICE_TYPE, device)
                    except Exception:
                        pass
                self.opened_devices.clear()
                for name, _device, _channel in UC2_LOGICAL_CHANNELS:
                    self.bus_available[name] = False
                print(
                    f"PCG-1 direct state publisher: {error}; retrying alternate UC2 order",
                    flush=True,
                )
                time.sleep(0.25)

        raise last_error or RuntimeError("unable to open UC2 pair")

    def _open_swcan(self) -> None:
        sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        try:
            sock.bind((self.swcan_interface,))
        except OSError as error:
            sock.close()
            print(
                f"PCG-1 direct state publisher: SWCAN {self.swcan_interface} unavailable: {error}",
                flush=True,
            )
            return
        sock.setblocking(False)
        self.swcan_socket = sock
        self.bus_available[SWCAN_LOGICAL_CHANNEL] = True

    def start(self) -> None:
        # This publisher is the authoritative writer for its state file. Start
        # each process with a fresh snapshot so per-run fields such as
        # bus_*_last_seen_utc cannot survive from a previous process.
        try:
            self.state_file.unlink()
        except FileNotFoundError:
            pass

        self._open_uc2()
        self._open_swcan()
        self.started_monotonic = time.monotonic()

    def _close_uc2(self) -> None:
        if self.library is not None:
            for device in reversed(self.opened_devices):
                for channel in (1, 0):
                    try:
                        self.reset_can(DEVICE_TYPE, device, channel)
                    except Exception:
                        pass
                try:
                    self.close_device(DEVICE_TYPE, device)
                except Exception:
                    pass
        self.opened_devices.clear()
        for name, _device, _channel in UC2_LOGICAL_CHANNELS:
            self.bus_available[name] = False

    def _reset_uc2_runtime_telemetry(self) -> None:
        for name, _device, _channel in UC2_LOGICAL_CHANNELS:
            self.bus_frames[name] = 0
            self.bus_ids[name].clear()
            self.bus_id_frames[name].clear()
            self.bus_last_seen.pop(name, None)
        for can_id in SOURCE_EVIDENCE_IDS:
            for name, _device, _channel in UC2_LOGICAL_CHANNELS:
                self.id_source_frames[can_id][name] = 0

    def _recover_partial_uc2(self) -> bool:
        uc2_names = [name for name, _device, _channel in UC2_LOGICAL_CHANNELS]
        active = [name for name in uc2_names if self.bus_frames.get(name, 0) > 0]
        silent = [name for name in uc2_names if self.bus_frames.get(name, 0) == 0]
        if not active or not silent:
            return False

        if self.uc2_runtime_recovery_count >= UC2_RUNTIME_RECOVERY_LIMIT:
            reason = (
                "partial UC2 traffic persisted after in-process recovery; "
                f"active={active} silent={silent}"
            )
            self.uc2_runtime_recovery_reason = reason
            print(
                "PCG-1 direct state publisher: "
                f"{reason}; exiting for clean systemd restart",
                flush=True,
            )
            raise PartialUc2TrafficError(reason)

        current = self.uc2_open_order
        alternate_first = (
            (1, 0) if current == (0, 1) else (0, 1)
        )
        alternate_orders = (
            alternate_first,
            (0, 1) if alternate_first == (1, 0) else (1, 0),
        )

        self.uc2_runtime_recovery_count += 1
        self.uc2_runtime_recovery_reason = (
            "partial_uc2_traffic:"
            + ",".join(f"active={name}" for name in active)
            + ";"
            + ",".join(f"silent={name}" for name in silent)
        )
        print(
            "PCG-1 direct state publisher: partial UC2 traffic detected; "
            f"active={active} silent={silent}; retrying with alternate open order",
            flush=True,
        )

        self._close_uc2()
        self._reset_uc2_runtime_telemetry()
        time.sleep(0.25)
        self._open_uc2(alternate_orders)
        self.started_monotonic = time.monotonic()
        return True

    def close(self) -> None:
        if self.swcan_socket is not None:
            self.swcan_socket.close()
            self.swcan_socket = None
        self._close_uc2()
        self.library = None

    def _battery_summary(self) -> dict[str, Any]:
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
            values = list(self.temps.values())
            updates.update({
                "hv_temp_min_c": round(min(values), 3),
                "hv_temp_max_c": round(max(values), 3),
                "hv_temperature_slots_c": [
                    self.temps[f"battery_temp_slot_{i}_c"] for i in range(1, 10)
                ],
                "hv_temperature_slots_updated_utc": _utc_now(),
            })
        return updates

    def _queue(self, updates: dict[str, Any]) -> None:
        if updates:
            self.pending.update(updates)

    def _flush(self) -> None:
        if self.pending:
            payload = dict(self.pending)
            self.pending.clear()
            _atomic_write(self.state_file, payload)

    def _handle(self, interface: str, can_id: int, data: bytes) -> None:
        updates: dict[str, Any] = {}
        now = _utc_now()
        self.bus_frames[interface] = self.bus_frames.get(interface, 0) + 1
        if interface in self.bus_ids:
            self.bus_ids[interface].add(can_id)
            counts = self.bus_id_frames[interface]
            counts[can_id] = counts.get(can_id, 0) + 1
        self.bus_last_seen[interface] = now

        if can_id in self.id_source_frames and interface in self.id_source_frames[can_id]:
            self.id_source_frames[can_id][interface] += 1

        logical_network = classify_logical_network(interface, can_id)
        if logical_network is None:
            self.unclassified_frames += 1
        else:
            self.logical_network_frames[logical_network] = (
                self.logical_network_frames.get(logical_network, 0) + 1
            )
            self.logical_network_last_seen[logical_network] = now

        # Decode only on the validated physical bus. CAN IDs are reused across
        # multiple Volt networks, so ID-family matches alone are not sufficient
        # evidence for a signal decoder. UC2 native *open order* may vary, but
        # the vendor device index/channel mapping remains the established Atlas
        # logical bus mapping.
        if interface == self.primary_interface and can_id == 0x1D4:
            updates.update(decode_apm_command(data))
            updates["apm_command_source_bus"] = interface
            updates["apm_command_source_network"] = "primary_powertrain"
        elif interface == self.primary_interface and can_id == 0x1D6:
            updates.update(decode_apm_stats(data))
            updates["apm_stats_source_bus"] = interface
            updates["apm_stats_source_network"] = "primary_powertrain"
        elif interface == "can1" and can_id == 0x0C9:
            updates.update(decode_legacy_accelerator(data))
            updates["accelerator_source_bus"] = interface
            updates["accelerator_source_reference"] = "ovms_voltampera_0x0c9"
            updates["vehicle_on_source_bus"] = interface
            updates["vehicle_on_source_reference"] = "ovms_voltampera_0x0c9"
            updates["motor_rpm_source_bus"] = interface
            updates["motor_rpm_source_reference"] = "ovms_voltampera_0x0c9"
        elif interface == "can1" and can_id == 0x0F1:
            updates.update(decode_legacy_brake(data))
            updates["brake_source_bus"] = interface
            updates["brake_source_reference"] = "evtools_primary_105_id_stream"
        elif interface == "can1" and can_id == 0x135:
            updates.update(decode_legacy_drive_position(data))
            updates["drive_position_source_bus"] = interface
            updates["drive_position_source_reference"] = "evtools_primary_105_id_stream"
        elif interface == "can1" and can_id == 0x1F5:
            updates.update(decode_legacy_shift_position(data))
            updates["shift_position_source_bus"] = interface
            updates["shift_position_source_reference"] = "evtools_primary_105_id_stream"
        elif interface == "can1" and can_id == 0x120:
            updates.update(decode_legacy_odometer(data))
            updates["odometer_source_bus"] = interface
            updates["odometer_source_reference"] = "ovms_voltampera_0x120"
        elif interface == "can1" and can_id == 0x3E9:
            updates.update(decode_legacy_vehicle_speed(data))
            updates["vehicle_speed_source_bus"] = interface
            updates["vehicle_speed_source_reference"] = "evtools_primary_105_id_stream"
        elif interface == "can1" and can_id == 0x4C1:
            updates.update(decode_legacy_ambient_coolant(data))
            updates["ambient_temperature_source_bus"] = interface
            updates["ambient_temperature_source_reference"] = "ovms_voltampera_0x4c1"
            updates["coolant_temperature_source_bus"] = interface
            updates["coolant_temperature_source_reference"] = "ovms_voltampera_0x4c1"
        elif interface == self.hv_interface and can_id == 0x210:
            updates.update(decode_pack_voltage(data))
            updates["hv_pack_voltage_source_bus"] = interface
            updates["hv_pack_voltage_source_network"] = "hv_energy_management"
        elif interface == self.hv_interface and can_id in CELL_IDS:
            self.cells.update(decode_cell_block(can_id, data))
            summary = self._battery_summary()
            if summary:
                summary["hv_cell_slots_source_bus"] = interface
                summary["hv_cell_slots_source_network"] = "hv_energy_management"
                updates.update(summary)
        elif interface == self.hv_interface and can_id == 0x302:
            self.temps.update(decode_battery_temps(data))
            summary = self._battery_summary()
            if summary:
                summary["hv_temperature_slots_source_bus"] = interface
                summary["hv_temperature_slots_source_network"] = "hv_energy_management"
                updates.update(summary)

        if updates:
            updates["direct_can_updated_utc"] = now
            self._queue(updates)

    def _poll_uc2(self) -> bool:
        got_any = False
        for name, device, channel in UC2_LOGICAL_CHANNELS:
            buffer = self.uc2_buffers[name]
            drained = 0
            while drained < UC2_RECEIVE_BURST_LIMIT:
                pending = self.receive_num(DEVICE_TYPE, device, channel)
                if pending == U32_ERROR or pending == 0:
                    break

                # Match the PCG-1 receive policy already validated in Atlas:
                # request exactly one frame with a positive timeout. Larger
                # zero-timeout reads have been observed to return zero while
                # the native queue continues to grow.
                received = self.receive(
                    DEVICE_TYPE,
                    device,
                    channel,
                    C.byref(buffer),
                    1,
                    UC2_RECEIVE_WAIT_MS,
                )
                if received == U32_ERROR or received == 0:
                    break
                if received != 1:
                    break

                frame = buffer
                drained += 1
                if frame.RemoteFlag or frame.ExternFlag or frame.DataLen > 8:
                    continue

                self._handle(
                    name,
                    int(frame.ID) & CAN_SFF_MASK,
                    bytes(frame.Data[: int(frame.DataLen)]),
                )
                got_any = True
        return got_any

    def _poll_swcan(self) -> bool:
        if self.swcan_socket is None:
            return False
        got_any = False
        while True:
            try:
                frame = self.swcan_socket.recv(16)
            except BlockingIOError:
                break
            if len(frame) < 16:
                break
            can_id_raw, dlc, payload = struct.unpack("=IB3x8s", frame)
            if can_id_raw & (CAN_EFF_FLAG | CAN_RTR_FLAG | CAN_ERR_FLAG):
                continue
            self._handle(
                SWCAN_LOGICAL_CHANNEL,
                can_id_raw & CAN_SFF_MASK,
                payload[: min(int(dlc), 8)],
            )
            got_any = True
        return got_any

    def _queue_health(self) -> None:
        uptime_s = max(0.0, time.monotonic() - self.started_monotonic)
        warmup_active = uptime_s < HEALTH_WARMUP_SECONDS
        warmup_remaining_s = max(0.0, HEALTH_WARMUP_SECONDS - uptime_s)
        all_physical_live = (
            len(self.bus_last_seen) >= CURRENT_PHYSICAL_VEHICLE_BUSES_EXPECTED
        )
        primary_signal_evidence = (
            self.id_source_frames[0x1D4].get(self.primary_interface, 0) > 0
            and self.id_source_frames[0x1D6].get(self.primary_interface, 0) > 0
        )
        hv_signal_evidence = (
            self.id_source_frames[0x210].get(self.hv_interface, 0) > 0
            and self.id_source_frames[0x302].get(self.hv_interface, 0) > 0
            and all(
                self.id_source_frames[can_id].get(self.hv_interface, 0) > 0
                for can_id in CELL_IDS
            )
        )

        health: dict[str, Any] = {
            "direct_can_interfaces_online": len(self.bus_last_seen),
            "direct_can_uptime_s": round(uptime_s, 3),
            "direct_can_warmup_active": warmup_active,
            "direct_can_warmup_remaining_s": round(warmup_remaining_s, 3),
            "direct_can_interfaces_available": sum(
                1 for value in self.bus_available.values() if value
            ),
            "direct_can_interfaces_configured": CAN_CAPABLE_CHANNEL_COUNT,
            "current_vehicle_can_networks_configured": CURRENT_PHYSICAL_VEHICLE_BUSES_EXPECTED,
            "physical_vehicle_buses_expected": CURRENT_PHYSICAL_VEHICLE_BUSES_EXPECTED,
            "physical_500k_buses_expected": CURRENT_500K_PHYSICAL_BUSES_EXPECTED,
            "physical_swcan_buses_expected": CURRENT_SWCAN_PHYSICAL_BUSES_EXPECTED,
            "known_hidden_internal_buses": KNOWN_HIDDEN_INTERNAL_BUSES,
            "total_known_vehicle_buses": TOTAL_KNOWN_VEHICLE_BUSES,
            "hidden_internal_bus_name": HIDDEN_INTERNAL_BUS_NAME,
            "hidden_internal_bus_bitrate": 125000,
            "hidden_internal_bus_status": "known_internal_not_directly_acquired",
            "physical_vehicle_buses_with_traffic": len(self.bus_last_seen),
            "physical_vehicle_bus_health": (
                "all_expected_buses_live"
                if all_physical_live
                else (
                    "starting_waiting_for_bus_traffic"
                    if warmup_active
                    else "missing_expected_bus_traffic"
                )
            ),
            "uc2_open_strategy": "auto_0_1_then_1_0",
            "uc2_runtime_recovery_count": self.uc2_runtime_recovery_count,
            "uc2_runtime_recovery_reason": self.uc2_runtime_recovery_reason,
            "uc2_open_order": (
                None
                if self.uc2_open_order is None
                else f"{self.uc2_open_order[0]}->{self.uc2_open_order[1]}"
            ),
            "reserved_can_channel": RESERVED_CAN_CHANNEL,
            "reserved_can_channel_status": "assignable_not_independent_volt_bus",
            "bicm_bus_bitrate": 125000,
            "bicm_bus_location": "becm_x2_internal_can",
            "bicm_bus_connector": "BECM_X2_pins_11_12_CAN_L_CAN_H",
            "bicm_bus_status": "community_documented_internal_can_route_to_secondary_dlc_pending_validation",
            "logical_network_classifier": "id_family_v1",
            "unclassified_can_frames": self.unclassified_frames,
            "future_lin_interfaces_configured": len(FUTURE_LIN_INTERFACES),
            "future_lin_interfaces_online": 0,
            "future_lin_status": "reserved_not_installed",
            "physical_bus_role_can0": PHYSICAL_BUS_ROLES["can0"],
            "physical_bus_role_can1": PHYSICAL_BUS_ROLES["can1"],
            "physical_bus_role_can2": PHYSICAL_BUS_ROLES["can2"],
            "physical_bus_role_can3": PHYSICAL_BUS_ROLES["can3"],
            "physical_bus_role_can4": PHYSICAL_BUS_ROLES["can4"],
            "validated_primary_bus": self.primary_interface,
            "validated_hv_bus": self.hv_interface,
            "validated_primary_bus_receiving": self.primary_interface in self.bus_last_seen,
            "validated_hv_bus_receiving": self.hv_interface in self.bus_last_seen,
            "validated_primary_signal_evidence": primary_signal_evidence,
            "validated_hv_signal_evidence": hv_signal_evidence,
            "validated_signal_bus_health": (
                "validated_sources_live"
                if primary_signal_evidence and hv_signal_evidence
                else (
                    "starting_waiting_for_signal_evidence"
                    if warmup_active
                    else "validated_source_missing"
                )
            ),
        }
        for name in [n for n, _, _ in UC2_LOGICAL_CHANNELS] + [SWCAN_LOGICAL_CHANNEL]:
            health[f"bus_{name}_available"] = self.bus_available.get(name, False)
            health[f"bus_{name}_frames"] = self.bus_frames.get(name, 0)
            health[f"bus_{name}_unique_ids"] = len(self.bus_ids.get(name, set()))
            top_ids = sorted(
                self.bus_id_frames.get(name, {}).items(),
                key=lambda item: (-item[1], item[0]),
            )[:20]
            health[f"bus_{name}_top_ids"] = [
                f"0x{can_id:03X}={count}" for can_id, count in top_ids
            ]
            if name in self.bus_last_seen:
                health[f"bus_{name}_last_seen_utc"] = self.bus_last_seen[name]
        health[f"bus_{RESERVED_CAN_CHANNEL}_available"] = False
        health[f"bus_{RESERVED_CAN_CHANNEL}_frames"] = 0
        health[f"bus_{RESERVED_CAN_CHANNEL}_unique_ids"] = 0
        health[f"bus_{RESERVED_CAN_CHANNEL}_top_ids"] = []

        source_evidence: list[str] = []
        for can_id in SOURCE_EVIDENCE_IDS:
            counts = self.id_source_frames[can_id]
            parts = [
                f"{bus}={count}"
                for bus, count in counts.items()
                if count > 0
            ]
            if parts:
                source_evidence.append(
                    f"0x{can_id:03X}:" + ",".join(parts)
                )
        if source_evidence:
            health["validated_id_source_evidence"] = source_evidence

        for network in LOGICAL_NETWORKS:
            health[f"logical_network_{network}_frames"] = self.logical_network_frames.get(
                network, 0
            )
            if network in self.logical_network_last_seen:
                health[f"logical_network_{network}_last_seen_utc"] = (
                    self.logical_network_last_seen[network]
                )
        self._queue(health)

    def run_forever(self) -> None:
        self.start()
        print(
            "PCG-1 direct state publisher: "
            "UC2 can0..can3 @500k + "
            f"{self.swcan_interface}->can4 SWCAN; "
            f"primary={self.primary_interface} hv={self.hv_interface}; "
            "can5 reserved",
            flush=True,
        )
        next_flush = time.monotonic()
        next_health = time.monotonic()
        try:
            while True:
                got_any = self._poll_uc2()
                got_any = self._poll_swcan() or got_any
                now = time.monotonic()

                if (
                    now - self.started_monotonic >= HEALTH_WARMUP_SECONDS
                    and self._recover_partial_uc2()
                ):
                    next_health = time.monotonic()
                    next_flush = time.monotonic()

                if now >= next_health:
                    self._queue_health()
                    next_health = now + 1.0
                if now >= next_flush:
                    self._flush()
                    next_flush = now + 0.25
                if not got_any:
                    time.sleep(0.002)
        finally:
            self._flush()
            self.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--uc2-library", type=Path, default=DEFAULT_UC2_LIBRARY)
    parser.add_argument("--swcan-interface", default=DEFAULT_SWCAN_INTERFACE)
    parser.add_argument("--primary-interface", default=DEFAULT_PRIMARY_INTERFACE)
    parser.add_argument("--hv-interface", default=DEFAULT_HV_INTERFACE)
    args = parser.parse_args(argv)

    DirectStatePublisher(
        state_file=args.state_file,
        uc2_library=args.uc2_library,
        swcan_interface=args.swcan_interface,
        primary_interface=args.primary_interface,
        hv_interface=args.hv_interface,
    ).run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
