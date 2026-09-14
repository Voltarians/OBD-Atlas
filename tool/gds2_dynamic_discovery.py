#!/usr/bin/env python3
"""Experimental isolated-bench GDS2 dynamic-data discovery wrapper.

This wrapper extends the normal read-only HPCM2 bench simulator only for the
GM enhanced-diagnostic dynamic-data services observed from GDS2 Data Display:

* 0x2C DynamicallyDefineMessage -> 0x6C <DPID>
* 0xAA stopSending -> one raw UUDT 0x00 acknowledgement
* 0xAA sendOneResponse -> one immediate synthetic UUDT sample
* 0xAA periodic levels -> immediate first sample plus scheduled UUDT samples

The production simulator remains unchanged and fail-closed. This wrapper is
meant only for an isolated VCX/UC2 bench with the vehicle disconnected.

GMW3110 defines 0xAA levels 02/03/04 as slow/medium/fast periodic scheduling,
but the actual rate counts are ECU/CTS-specific. The discovery wrapper therefore
uses explicit synthetic bench cadences. Defaults are 300 ms for medium and
25 ms for fast because those values appear in GMW3110 examples; they are NOT
claims about the Gen-1 Volt HPCM2. Slow scheduling remains disabled unless an
operator explicitly supplies --aa-slow-ms.

Synthetic bytes and timing are bench fixtures only. They are not vehicle
measurements, PID scaling claims, or confirmation of a signal meaning/timing.
"""

from __future__ import annotations

import argparse
import ctypes as C
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import gds2_bench_simulator as base


# First directly observed from the 2026-09-14 isolated GDS2 HPCM2 Contactor
# Data session: 2C FE 43 0E. 0x00 is deliberately synthetic and carries no
# semantic claim. Related GM service literature associates PID 0x430E with a
# high-voltage contactor command/status parameter on another GM EV platform,
# but Atlas does not promote that mapping from this fixture alone.
OBSERVED_DYNAMIC_FIXTURES: dict[int, bytes] = {
    0x430E: b"\x00",
}

# Synthetic bench scheduler defaults. GMW3110 examples demonstrate 25 ms fast
# and both 200/300 ms medium configurations; actual ECU values are CTS-specific.
DEFAULT_MEDIUM_MS = 300.0
DEFAULT_FAST_MS = 25.0


@dataclass
class ScheduledDpid:
    period_seconds: float
    next_due: float
    level: int


@dataclass
class DynamicDiscoveryState:
    definitions: dict[int, tuple[int, ...]] = field(default_factory=dict)
    scheduled: dict[int, ScheduledDpid] = field(default_factory=dict)
    schedule_periods: dict[int, float] = field(
        default_factory=lambda: {
            0x03: DEFAULT_MEDIUM_MS / 1000.0,
            0x04: DEFAULT_FAST_MS / 1000.0,
        }
    )

    def _value_for_pid(self, pid: int) -> bytes | None:
        if pid in OBSERVED_DYNAMIC_FIXTURES:
            return OBSERVED_DYNAMIC_FIXTURES[pid]
        return base.DEFAULT_DIDS.get(pid)

    @staticmethod
    def _valid_dpid(dpid: int) -> bool:
        # GMW3110 dynamic DPIDs are FE..90 or 7F..01. 80..8F are reserved for
        # diagnostic trouble-code UUDT messages and therefore excluded.
        return (0x90 <= dpid <= 0xFE) or (0x01 <= dpid <= 0x7F)

    def define(self, payload: bytes) -> base.Decision:
        if len(payload) < 4 or (len(payload) - 2) % 2:
            return base.Decision(base.negative(0x2C, 0x12), "dynamicDefineInvalidFormat")

        dpid = payload[1]
        if not self._valid_dpid(dpid):
            return base.Decision(base.negative(0x2C, 0x31), "dynamicDefineOutOfRange")

        pids = tuple(
            (payload[offset] << 8) | payload[offset + 1]
            for offset in range(2, len(payload), 2)
        )
        values: list[bytes] = []
        unknown: list[int] = []
        for pid in pids:
            value = self._value_for_pid(pid)
            if value is None:
                unknown.append(pid)
            else:
                values.append(value)

        if unknown:
            detail = "unknownDynamicPid=" + ",".join(f"0x{pid:04X}" for pid in unknown)
            return base.Decision(base.negative(0x2C, 0x31), "unknownDynamicPid", detail)

        total_length = sum(len(value) for value in values)
        if total_length > 7:
            return base.Decision(
                base.negative(0x2C, 0x12),
                "dynamicDefinitionTooLarge",
                f"dpid=0x{dpid:02X} dataBytes={total_length}",
            )

        # A redefinition must not silently continue an old schedule with new
        # packet contents. Require GDS2 to schedule the newly defined DPID.
        self.scheduled.pop(dpid, None)
        self.definitions[dpid] = pids
        detail = f"dpid=0x{dpid:02X} pids=" + ",".join(f"0x{pid:04X}" for pid in pids)
        return base.Decision(bytes((0x6C, dpid)), "dynamicDefine", detail)

    def packet_bytes(self, dpid: int) -> bytes | None:
        pids = self.definitions.get(dpid)
        if pids is None:
            return None
        data = bytearray((dpid,))
        for pid in pids:
            value = self._value_for_pid(pid)
            if value is None:
                return None
            data.extend(value)
        if len(data) > 8:
            return None
        return bytes(data)

    def control(self, payload: bytes, *, now: float | None = None) -> base.Decision:
        if len(payload) < 2:
            return base.Decision(base.negative(0xAA, 0x12), "dynamicControlInvalidFormat")

        now = time.monotonic() if now is None else now
        level = payload[1]
        if level == 0x00:
            if len(payload) == 2:
                stopped = tuple(sorted(self.scheduled))
                self.scheduled.clear()
                detail = "stopSending all"
                if stopped:
                    detail += " dpids=" + ",".join(f"0x{dpid:02X}" for dpid in stopped)
            else:
                stopped = []
                for dpid in payload[2:]:
                    if dpid in self.scheduled:
                        stopped.append(dpid)
                        self.scheduled.pop(dpid, None)
                detail = "stopSending requested=" + ",".join(
                    f"0x{dpid:02X}" for dpid in payload[2:]
                )
                if stopped:
                    detail += " stopped=" + ",".join(f"0x{dpid:02X}" for dpid in stopped)
            # GMW3110 uses raw UUDT message number 0x00 as the positive response
            # to stopSending. The production simulator remains unchanged.
            return base.Decision(
                b"\x00",
                "dynamicStop",
                detail,
                transport="raw",
                response_channel="uudt",
            )

        if level not in {0x01, 0x02, 0x03, 0x04}:
            return base.Decision(base.negative(0xAA, 0x12), "dynamicControlUnsupportedLevel")
        if len(payload) != 3:
            return base.Decision(
                base.negative(0xAA, 0x12),
                "dynamicControlDiscoveryLimit",
                "discovery wrapper supports exactly one DPID per 0xAA request",
            )

        dpid = payload[2]
        sample = self.packet_bytes(dpid)
        if sample is None:
            return base.Decision(
                base.negative(0xAA, 0x31),
                "dynamicControlUndefinedDpid",
                f"dpid=0x{dpid:02X}",
            )

        if level == 0x01:
            return base.Decision(
                sample,
                "dynamicSample",
                "oneShot syntheticBenchData",
                transport="raw",
                response_channel="uudt",
            )

        period = self.schedule_periods.get(level)
        if period is None or period <= 0:
            return base.Decision(
                base.negative(0xAA, 0x12),
                "dynamicScheduleRateUnconfigured",
                f"level=0x{level:02X}; configure an explicit synthetic bench cadence",
            )

        self.scheduled[dpid] = ScheduledDpid(
            period_seconds=period,
            next_due=now + period,
            level=level,
        )
        label = {0x02: "slow", 0x03: "medium", 0x04: "fast"}[level]
        return base.Decision(
            sample,
            "dynamicSchedule",
            f"{label} syntheticBenchCadence={period * 1000.0:g}ms dpid=0x{dpid:02X}",
            transport="raw",
            response_channel="uudt",
        )

    def poll_due(self, now: float | None = None) -> list[tuple[int, bytes, int, float]]:
        """Return due scheduled packets and advance their next deadlines.

        Each tuple is (DPID, raw UUDT bytes, level, configured period seconds).
        Missed periods are collapsed instead of emitted as a burst.
        """
        now = time.monotonic() if now is None else now
        due: list[tuple[int, bytes, int, float]] = []
        for dpid, schedule in sorted(self.scheduled.items()):
            if schedule.next_due > now:
                continue
            sample = self.packet_bytes(dpid)
            if sample is None:
                continue
            due.append((dpid, sample, schedule.level, schedule.period_seconds))
            while schedule.next_due <= now:
                schedule.next_due += schedule.period_seconds
        return due

    def seconds_until_next(self, now: float | None = None) -> float | None:
        if not self.scheduled:
            return None
        now = time.monotonic() if now is None else now
        return max(0.0, min(item.next_due for item in self.scheduled.values()) - now)


_STATE = DynamicDiscoveryState()


def decide_response(payload: bytes, *, vin: str = base.DEFAULT_VIN, dids=None) -> base.Decision:
    if payload:
        if payload[0] == 0x2C:
            return _STATE.define(payload)
        if payload[0] == 0xAA:
            return _STATE.control(payload)
    return base.decide_response(payload, vin=vin, dids=dids)


def run_dynamic_simulator(*, library_path: Path, device: int, channel: int, bitrate: int,
                          vin: str, timeout_seconds: float, log_path: Path,
                          profile: base.ModuleProfile) -> int:
    """Run the isolated simulator with wrapper-owned periodic UUDT scheduling."""
    base.check_layouts()
    if len(vin) != 17 or not vin.isascii():
        raise ValueError("simulator VIN must contain exactly 17 ASCII characters")
    if not profile.implemented:
        raise ValueError(f"refusing transmit for discovery-only module {profile.key}")
    if profile.normal_response_id is None:
        raise ValueError(f"module {profile.key} has no normal response CAN ID")
    if profile.uudt_response_id is None:
        raise ValueError(f"module {profile.key} has no UUDT response CAN ID")

    library = C.CDLL(str(library_path))
    u32 = C.c_uint32
    open_device = base.bind(library, "VCI_OpenDevice", [u32, u32, u32])
    close_device = base.bind(library, "VCI_CloseDevice", [u32, u32])
    init_can = base.bind(library, "VCI_InitCAN", [u32, u32, u32, C.POINTER(base.VciInitConfig)])
    start_can = base.bind(library, "VCI_StartCAN", [u32, u32, u32])
    reset_can = base.bind(library, "VCI_ResetCAN", [u32, u32, u32])
    receive = base.bind(
        library,
        "VCI_Receive",
        [u32, u32, u32, C.POINTER(base.VciCanObj), u32, C.c_int32],
    )
    transmit = base.bind(
        library,
        "VCI_Transmit",
        [u32, u32, u32, C.POINTER(base.VciCanObj), u32],
    )

    opened = False
    started = False
    logger = base.JsonlLog(log_path)
    unknown: dict[str, int] = {}
    deadline = None if timeout_seconds == 0 else time.monotonic() + timeout_seconds

    def tx(can_id: int, data: bytes, **extra) -> None:
        frame = base.make_can_frame(can_id, data)
        count = int(transmit(base.DEVICE_TYPE, device, channel, C.byref(frame), 1))
        if count != 1:
            raise RuntimeError(f"VCI_Transmit expected 1 frame, returned {count}")
        logger.write("tx", can_id, data, module=profile.key, **extra)
        print(f"TX {can_id:03X}#{data.hex().upper()}", flush=True)

    def wait_for_flow_control() -> tuple[int, float]:
        frame = base.VciCanObj()
        fc_deadline = time.monotonic() + 1.0
        while time.monotonic() < fc_deadline:
            count = int(receive(base.DEVICE_TYPE, device, channel, C.byref(frame), 1, 100))
            if count == base.U32_ERROR:
                raise RuntimeError("VCI_Receive returned 0xFFFFFFFF while waiting for flow control")
            if count != 1:
                continue
            data = base.frame_bytes(frame)
            logger.write("rx", int(frame.ID), data)
            print(f"RX {frame.ID:03X}#{data.hex().upper()}", flush=True)
            if int(frame.ID) == profile.request_id and len(data) >= 3 and data[0] >> 4 == 3:
                flow_status = data[0] & 0x0F
                if flow_status != 0:
                    raise RuntimeError(f"unsupported ISO-TP flow status {flow_status}")
                return data[1], base.parse_stmin(data[2])
        raise RuntimeError("timed out waiting for ISO-TP flow control")

    def send_isotp(payload: bytes, response_can_id: int) -> None:
        frames = base.segment_isotp(payload)
        tx(response_can_id, frames[0])
        if len(frames) == 1:
            return
        block_size, delay = wait_for_flow_control()
        sent_in_block = 0
        for index, data in enumerate(frames[1:], start=1):
            if delay:
                time.sleep(delay)
            tx(response_can_id, data)
            sent_in_block += 1
            if block_size and sent_in_block >= block_size and index < len(frames) - 1:
                block_size, delay = wait_for_flow_control()
                sent_in_block = 0

    print("OBD Atlas GDS2 Dynamic Discovery Simulator", flush=True)
    print(f"UC2 device {device} CAN{channel} • {bitrate} bit/s • ACTIVE ISOLATED BENCH", flush=True)
    print(
        f"Module {profile.key}: {profile.name or 'unidentified'} • "
        f"request {profile.request_id:03X} -> response {profile.normal_response_id:03X} • "
        f"UUDT {profile.uudt_response_id:03X}",
        flush=True,
    )
    print(f"VIN {vin} • Log: {log_path}", flush=True)
    configured = ", ".join(
        f"0x{level:02X}={period * 1000.0:g}ms"
        for level, period in sorted(_STATE.schedule_periods.items())
        if period > 0
    )
    print(f"Synthetic periodic bench cadences: {configured or 'none'}", flush=True)
    print("Cadences are discovery fixtures, not confirmed Gen-1 HPCM2 timing.", flush=True)
    print("Security/programming/write services remain blocked by the base simulator.", flush=True)

    try:
        result = open_device(base.DEVICE_TYPE, device, 0)
        if result != 1:
            raise RuntimeError(f"VCI_OpenDevice failed: {result}")
        opened = True
        config = base.make_init_config(bitrate)
        result = init_can(base.DEVICE_TYPE, device, channel, C.byref(config))
        if result != 1:
            raise RuntimeError(f"VCI_InitCAN failed: {result}")
        result = start_can(base.DEVICE_TYPE, device, channel)
        if result != 1:
            raise RuntimeError(f"VCI_StartCAN failed: {result}")
        started = True

        frame = base.VciCanObj()
        while deadline is None or time.monotonic() < deadline:
            now = time.monotonic()
            for dpid, sample, level, period in _STATE.poll_due(now):
                tx(
                    profile.uudt_response_id,
                    sample,
                    classification="dynamicPeriodicSample",
                    dpid=f"0x{dpid:02X}",
                    aaLevel=f"0x{level:02X}",
                    syntheticPeriodMs=period * 1000.0,
                )

            wait_ms = 100
            delay = _STATE.seconds_until_next(time.monotonic())
            if delay is not None:
                wait_ms = max(1, min(wait_ms, int(delay * 1000.0) or 1))

            count = int(receive(base.DEVICE_TYPE, device, channel, C.byref(frame), 1, wait_ms))
            if count == base.U32_ERROR:
                raise RuntimeError("VCI_Receive returned 0xFFFFFFFF")
            if count != 1:
                continue

            data = base.frame_bytes(frame)
            can_id = int(frame.ID)
            logger.write("rx", can_id, data)
            print(f"RX {can_id:03X}#{data.hex().upper()}", flush=True)

            if bool(frame.ExternFlag) or bool(frame.RemoteFlag) or can_id != profile.request_id:
                continue
            payload = base.parse_single_frame(data)
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
                module=profile.key,
                classification=decision.classification,
                detail=decision.detail,
                transport=decision.transport,
                responseChannel=decision.response_channel,
                udsRequest=payload.hex().upper(),
                udsResponse=None if decision.response is None else decision.response.hex().upper(),
            )
            if decision.classification in {
                "unsupportedService",
                "unknownDid",
                "unknownLegacyDid",
                "unsupportedDtcSubfunction",
                "unknownDynamicPid",
            }:
                key = payload.hex().upper()
                unknown[key] = unknown.get(key, 0) + 1
            if decision.response is None:
                continue

            if decision.response_channel == "uudt":
                if decision.transport != "raw":
                    raise RuntimeError("UUDT decision must use raw transport")
                tx(profile.uudt_response_id, decision.response)
            else:
                if decision.transport != "isotp":
                    raise RuntimeError("normal response decision must use ISO-TP transport")
                send_isotp(decision.response, profile.normal_response_id)

    except KeyboardInterrupt:
        print("Simulator stopped by operator.", flush=True)
    finally:
        if unknown:
            print("Unknown/unsupported GDS2 requests observed:", flush=True)
            for request, count in sorted(unknown.items(), key=lambda item: (-item[1], item[0])):
                print(f"  {count:5d}  {request}", flush=True)
        if started:
            try:
                reset_can(base.DEVICE_TYPE, device, channel)
            except Exception:
                pass
        if opened:
            try:
                close_device(base.DEVICE_TYPE, device)
            except Exception:
                pass
        logger.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = base.build_parser()
    parser.description = "Atlas isolated GDS2 dynamic-data discovery simulator."
    parser.add_argument(
        "--aa-slow-ms",
        type=float,
        default=0.0,
        help="Synthetic slow periodic bench cadence; 0 disables level 0x02.",
    )
    parser.add_argument(
        "--aa-medium-ms",
        type=float,
        default=DEFAULT_MEDIUM_MS,
        help="Synthetic medium periodic bench cadence; default 300 ms from a GMW3110 example, not an HPCM2 claim.",
    )
    parser.add_argument(
        "--aa-fast-ms",
        type=float,
        default=DEFAULT_FAST_MS,
        help="Synthetic fast periodic bench cadence; default 25 ms from a GMW3110 example, not an HPCM2 claim.",
    )
    return parser


def dynamic_self_check() -> None:
    state = DynamicDiscoveryState()
    assert state.define(bytes.fromhex("2CFE430E")).response == bytes.fromhex("6CFE")
    scheduled = state.control(bytes.fromhex("AA03FE"), now=10.0)
    assert scheduled.classification == "dynamicSchedule"
    assert scheduled.response == bytes.fromhex("FE00")
    assert state.poll_due(10.299) == []
    assert state.poll_due(10.300)[0][1] == bytes.fromhex("FE00")
    assert state.control(bytes.fromhex("AA00FE"), now=10.301).response == bytes.fromhex("00")
    assert not state.scheduled


def main(argv: list[str] | None = None) -> int:
    global _STATE
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)

    if args.list_modules:
        base.print_module_registry(args.registry)
        return 0
    if args.check:
        base.self_check(args.registry)
        dynamic_self_check()
        print("GDS2 dynamic discovery simulator self-check OK.")
        return 0

    for name, value in {
        "--aa-slow-ms": args.aa_slow_ms,
        "--aa-medium-ms": args.aa_medium_ms,
        "--aa-fast-ms": args.aa_fast_ms,
    }.items():
        if value < 0:
            raise SystemExit(f"{name} must be >= 0")

    periods: dict[int, float] = {}
    if args.aa_slow_ms > 0:
        periods[0x02] = args.aa_slow_ms / 1000.0
    if args.aa_medium_ms > 0:
        periods[0x03] = args.aa_medium_ms / 1000.0
    if args.aa_fast_ms > 0:
        periods[0x04] = args.aa_fast_ms / 1000.0
    _STATE = DynamicDiscoveryState(schedule_periods=periods)

    try:
        profile = base.select_module(args.module, registry_path=args.registry)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    if not args.confirm_isolated_bench:
        raise SystemExit("refusing active simulator mode without --confirm-isolated-bench; keep the vehicle disconnected")
    if sys.platform != "linux":
        raise SystemExit("GDS2 UC2 bench simulator requires Linux")
    if args.timeout < 0:
        raise SystemExit("--timeout must be >= 0")
    if args.bitrate != profile.bitrate:
        raise SystemExit(f"module {profile.key} registry bitrate is {profile.bitrate}; requested {args.bitrate}")

    library_path = base.find_library(args.library)
    log_path = args.log or base.default_log_path()
    return run_dynamic_simulator(
        library_path=library_path,
        device=args.device,
        channel=args.channel,
        bitrate=args.bitrate,
        vin=args.vin,
        timeout_seconds=args.timeout,
        log_path=log_path,
        profile=profile,
    )


if __name__ == "__main__":
    raise SystemExit(main())
