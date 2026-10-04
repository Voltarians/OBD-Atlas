#!/usr/bin/env python3
"""PCG-1 -> Promethean Core newline-delimited JSON gateway.

The gateway deliberately does not invent vehicle values.  It always publishes
link/heartbeat state and only includes vehicle fields that have been written by
an evidence-backed local decoder to the configured JSON state file.
"""

from __future__ import annotations

import argparse
import json
import selectors
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "promethean.pcg1.gateway.v1"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 47001
DEFAULT_INTERVAL = 1.0

FLOAT_FIELDS = {
    "direct_can_warmup_remaining_s",
    "direct_can_uptime_s",
    # 12-V / APM
    "bus12_voltage_v",
    "apm_output_voltage_v",
    "apm_requested_voltage_v",
    "apm_current_a",
    "apm_power_w",
    "apm_temperature_c",
    "apm_hv_input_current_a",
    "apm_temperature_1_c",
    "apm_temperature_2_c",

    # High-voltage battery
    "hv_pack_voltage_v",
    "hv_pack_current_a",
    "hv_pack_power_kw",
    "hv_soc_pct",
    "hv_cell_min_v",
    "hv_cell_max_v",
    "hv_cell_delta_mv",
    "hv_temp_min_c",
    "hv_temp_max_c",
    "isolation_kohm",

    # Energy / charging
    "drive_power_kw",
    "regen_power_kw",
    "charger_power_kw",

    # Thermal
    "battery_coolant_temp_c",
    "power_electronics_coolant_temp_c",
    "engine_coolant_temp_c",

    # Drive unit / vehicle
    "motor_a_rpm",
    "motor_b_rpm",
    "drive_torque_nm",
    "inverter_temperature_c",
    "vehicle_speed_mph",
}
INT_FIELDS = {
    "bus_can5_unique_ids",
    "bus_can4_unique_ids",
    "bus_can3_unique_ids",
    "bus_can2_unique_ids",
    "bus_can1_unique_ids",
    "bus_can0_unique_ids",
    "dtc_count",
    "network_modules_online",
    "network_modules_expected",
    "direct_can_interfaces_online",
    "direct_can_interfaces_available",
    "direct_can_interfaces_configured",
    "current_vehicle_can_networks_configured",
    "physical_vehicle_buses_expected",
    "physical_500k_buses_expected",
    "physical_swcan_buses_expected",
    "known_hidden_internal_buses",
    "total_known_vehicle_buses",
    "hidden_internal_bus_bitrate",
    "physical_vehicle_buses_with_traffic",
    "bicm_bus_bitrate",
    "unclassified_can_frames",
    "logical_network_primary_powertrain_frames",
    "logical_network_hv_energy_management_frames",
    "logical_network_swcan_frames",
    "logical_network_bicm_internal_125k_frames",
    "future_lin_interfaces_configured",
    "future_lin_interfaces_online",
    "apm_status_raw",
    "apm_counter_raw",
    "hv_cell_measurement_slots_complete",
}
STRING_FIELDS = {
    "physical_bus_role_can4",
    "physical_bus_role_can3",
    "physical_bus_role_can2",
    "physical_bus_role_can1",
    "physical_bus_role_can0",
    "apm_state",
    "dc_dc_state",
    "hvil_state",
    "contactor_state",
    "charging_state",
    "drive_state",
    "apm_command_source_bus",
    "apm_stats_source_bus",
    "hv_pack_voltage_source_bus",
    "hv_cell_slots_source_bus",
    "hv_temperature_slots_source_bus",
    "bus12_voltage_source",
    "future_lin_status",
    "reserved_can_channel",
    "reserved_can_channel_status",
    "bicm_bus_location",
    "bicm_bus_connector",
    "bicm_bus_status",
    "logical_network_classifier",
    "physical_vehicle_bus_health",
    "hidden_internal_bus_name",
    "hidden_internal_bus_status",
    "uc2_open_strategy",
    "uc2_open_order",
    "validated_primary_bus",
    "validated_hv_bus",
    "validated_signal_bus_health",
    "apm_command_source_network",
    "apm_stats_source_network",
    "hv_pack_voltage_source_network",
    "hv_cell_slots_source_network",
    "hv_temperature_slots_source_network",
}
STRING_LIST_FIELDS = {
    "bus_can5_top_ids",
    "bus_can4_top_ids",
    "bus_can3_top_ids",
    "bus_can2_top_ids",
    "bus_can1_top_ids",
    "bus_can0_top_ids",
    "active_dtcs",
    "offline_modules",
    "validated_id_source_evidence",
}
BOOL_FIELDS = {
    "direct_can_warmup_active",
    "validated_primary_bus_receiving",
    "validated_hv_bus_receiving",
    "validated_primary_signal_evidence",
    "validated_hv_signal_evidence",
}

FLOAT_LIST_FIELDS = {
    "hv_cell_slots_v",
    "hv_temperature_slots_c",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_state(raw: Any) -> dict[str, Any]:
    """Return only gateway fields with the expected primitive types."""
    if not isinstance(raw, dict):
        return {}

    source = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    out: dict[str, Any] = {}

    for key in FLOAT_FIELDS:
        value = source.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out[key] = float(value)

    for key in INT_FIELDS:
        value = source.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            out[key] = value

    for key in STRING_FIELDS:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()

    for key in BOOL_FIELDS:
        value = source.get(key)
        if isinstance(value, bool):
            out[key] = value

    for key in STRING_LIST_FIELDS:
        value = source.get(key)
        if isinstance(value, list):
            cleaned = [
                item.strip()
                for item in value
                if isinstance(item, str) and item.strip()
            ]
            if cleaned:
                out[key] = cleaned

    for key in FLOAT_LIST_FIELDS:
        value = source.get(key)
        if isinstance(value, list):
            cleaned_numbers = [
                float(item)
                for item in value
                if isinstance(item, (int, float)) and not isinstance(item, bool)
            ]
            if len(cleaned_numbers) == len(value):
                out[key] = cleaned_numbers

    apm = source.get("apm")
    if isinstance(apm, dict):
        apm_out: dict[str, Any] = {}
        for key in ("output_voltage_v", "voltage_v",
                    "output_current_a", "current_a",
                    "output_power_w", "power_w"):
            value = apm.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                apm_out[key] = float(value)
        for key in ("state", "dc_dc_state"):
            value = apm.get(key)
            if isinstance(value, str) and value.strip():
                apm_out[key] = value.strip()
        if apm_out:
            out["apm"] = apm_out

    return out


class StateFile:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._mtime_ns: int | None = None
        self._state: dict[str, Any] = {}

    def read(self) -> dict[str, Any]:
        if self.path is None:
            return self._state

        try:
            stat = self.path.stat()
        except FileNotFoundError:
            self._mtime_ns = None
            self._state = {}
            return self._state

        if self._mtime_ns == stat.st_mtime_ns:
            return self._state

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Keep the last valid state rather than replacing evidence with
            # malformed or partially-written data.
            return self._state

        self._state = normalize_state(raw)
        self._mtime_ns = stat.st_mtime_ns
        return self._state


class GatewayServer:
    def __init__(
        self,
        host: str,
        port: int,
        interval: float,
        state_file: StateFile,
    ) -> None:
        self.host = host
        self.port = port
        self.interval = interval
        self.state_file = state_file
        self.selector = selectors.DefaultSelector()
        self.clients: dict[socket.socket, tuple[str, int]] = {}
        self.sequence = 0

    def _accept(self, server: socket.socket) -> None:
        client, address = server.accept()
        client.setblocking(False)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.clients[client] = (str(address[0]), int(address[1]))
        self.selector.register(client, selectors.EVENT_READ, self._read_client)
        print(f"Promethean Core client connected: {address[0]}:{address[1]}",
              flush=True)

    def _drop_client(self, client: socket.socket) -> None:
        address = self.clients.pop(client, None)
        try:
            self.selector.unregister(client)
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass
        if address is not None:
            print(f"Promethean Core client disconnected: "
                  f"{address[0]}:{address[1]}", flush=True)

    def _read_client(self, client: socket.socket) -> None:
        try:
            data = client.recv(4096)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self._drop_client(client)
            return
        if not data:
            self._drop_client(client)

    def _message(self) -> bytes:
        self.sequence += 1
        data = self.state_file.read()
        message = {
            "schema": SCHEMA,
            "source": "PCG-1",
            "type": "vehicle_state",
            "status": "online",
            "sequence": self.sequence,
            "timestamp_utc": _utc_now(),
            "data_valid": bool(data),
            "data": data,
        }
        return (json.dumps(message, separators=(",", ":"), sort_keys=True)
                + "\n").encode("utf-8")

    def _broadcast(self) -> None:
        payload = self._message()
        for client in list(self.clients):
            try:
                client.sendall(payload)
            except (BrokenPipeError, ConnectionResetError, OSError):
                self._drop_client(client)

    def serve_forever(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen(8)
        server.setblocking(False)
        self.selector.register(server, selectors.EVENT_READ, self._accept)

        print(
            f"PCG-1 Promethean Core gateway listening on "
            f"{self.host}:{self.port}",
            flush=True,
        )

        next_broadcast = time.monotonic()
        try:
            while True:
                timeout = max(0.0, next_broadcast - time.monotonic())
                for key, _ in self.selector.select(timeout):
                    callback = key.data
                    callback(key.fileobj)

                now = time.monotonic()
                if now >= next_broadcast:
                    self._broadcast()
                    next_broadcast = now + self.interval
        finally:
            for client in list(self.clients):
                self._drop_client(client)
            try:
                self.selector.unregister(server)
            except Exception:
                pass
            server.close()
            self.selector.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve PCG-1 vehicle state to Promethean Core"
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help="Broadcast interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path("/run/promethean/vehicle_state.json"),
        help="Evidence-backed live state JSON produced by the local decoder",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.port < 1 or args.port > 65535:
        raise SystemExit("port must be in 1..65535")
    if args.interval <= 0:
        raise SystemExit("interval must be > 0")

    GatewayServer(
        host=args.host,
        port=args.port,
        interval=args.interval,
        state_file=StateFile(args.state_file),
    ).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
