#!/usr/bin/env python3
"""Read SAE Mode 01 PID 0x42 from a vLinker/ELM serial adapter.

This is the evidence-backed 12-V source for the Promethean Core development
HMI. PID 0x42 is "control module voltage". Multiple GM modules answer the
functional request, so PCG-1 publishes the median valid response as
bus12_voltage_v rather than selecting one ECU arbitrarily.

The reader never fabricates APM current, power, state, or output voltage.
Those fields remain absent until separately validated.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PORT = "/dev/rfcomm0"
DEFAULT_BAUD = 115200
DEFAULT_INTERVAL = 1.0
DEFAULT_STATE_FILE = Path("/run/promethean/vehicle_state.json")
PID0142_RE = re.compile(r"4142([0-9A-Fa-f]{4})")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_pid0142_voltages(text: str) -> list[float]:
    """Extract all valid Mode 01 PID 0x42 voltages from an ELM/STN response."""
    values: list[float] = []
    for match in PID0142_RE.finditer(text):
        millivolts = int(match.group(1), 16)
        volts = millivolts / 1000.0
        # Reject obvious garbage while preserving the automotive 12-V range.
        if 6.0 <= volts <= 18.0:
            values.append(volts)
    return values


def median_pid0142_voltage(text: str) -> tuple[float, list[float]]:
    values = parse_pid0142_voltages(text)
    if not values:
        raise ValueError("no valid Mode 01 PID 0142 responses")
    return float(statistics.median(values)), values


def _merge_state(path: Path, voltage: float, samples: list[float]) -> None:
    raw: dict[str, Any] = {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            raw = loaded
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        pass

    target = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    target["bus12_voltage_v"] = round(voltage, 3)
    target["bus12_voltage_source"] = "sae_mode01_pid_0142_median"
    target["bus12_pid0142_sample_count"] = len(samples)
    target["bus12_pid0142_samples_v"] = [round(value, 3) for value in samples]
    target["bus12_updated_utc"] = _utc_now()

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
        text=True,
    )
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


class ElmPid0142Reader:
    def __init__(self, port: str, baud: int) -> None:
        self.port = port
        self.baud = baud
        self.serial = None

    def close(self) -> None:
        if self.serial is not None:
            try:
                self.serial.close()
            except Exception:
                pass
            self.serial = None

    def _read_prompt(self, timeout: float) -> str:
        assert self.serial is not None
        deadline = time.monotonic() + timeout
        chunks: list[bytes] = []
        while time.monotonic() < deadline:
            chunk = self.serial.read(512)
            if chunk:
                chunks.append(chunk)
                if b">" in chunk or b">" in b"".join(chunks):
                    break
        return b"".join(chunks).decode("ascii", errors="replace")

    def _command(self, command: str, timeout: float = 2.0) -> str:
        assert self.serial is not None
        self.serial.reset_input_buffer()
        self.serial.write((command + "\r").encode("ascii"))
        self.serial.flush()
        response = self._read_prompt(timeout)
        upper = response.upper()
        if "?" in upper or "ERROR" in upper or "UNABLE TO CONNECT" in upper:
            raise RuntimeError(f"adapter rejected {command}: {response.strip()}")
        return response

    def open(self) -> None:
        if self.serial is not None:
            return
        import serial

        self.serial = serial.Serial(
            self.port,
            self.baud,
            timeout=0.20,
            write_timeout=1.0,
        )
        try:
            self._command("ATZ", timeout=4.0)
            self._command("ATE0")
            self._command("ATL0")
            self._command("ATS0")
            self._command("ATH1")
            self._command("ATSP6")
        except Exception:
            self.close()
            raise

    def read(self) -> tuple[float, list[float], str]:
        self.open()
        response = self._command("0142", timeout=3.0)
        voltage, samples = median_pid0142_voltage(response)
        return voltage, samples, response


def run_forever(
    port: str,
    baud: int,
    interval: float,
    state_file: Path,
) -> None:
    reader = ElmPid0142Reader(port, baud)
    while True:
        started = time.monotonic()
        try:
            voltage, samples, _ = reader.read()
            _merge_state(state_file, voltage, samples)
            print(
                f"PID 0142 bus voltage {voltage:.3f} V "
                f"from {len(samples)} module response(s)",
                flush=True,
            )
        except Exception as error:
            print(f"PID 0142 read failed: {error}", flush=True)
            reader.close()

        elapsed = time.monotonic() - started
        time.sleep(max(0.1, interval - elapsed))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish vLinker MS Mode 01 PID 0142 voltage to PCG-1 state"
    )
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.baud <= 0:
        raise SystemExit("baud must be > 0")
    if args.interval <= 0:
        raise SystemExit("interval must be > 0")
    try:
        run_forever(args.port, args.baud, args.interval, args.state_file)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
