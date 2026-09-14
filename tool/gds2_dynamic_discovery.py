#!/usr/bin/env python3
"""Experimental isolated-bench GDS2 dynamic-data discovery wrapper.

This wrapper extends the normal read-only HPCM2 bench simulator only for the
GM enhanced-diagnostic dynamic-data services observed from GDS2 Data Display:

* 0x2C DynamicallyDefineMessage -> 0x6C <DPID>
* 0xAA stopSending -> one raw UUDT 0x00 acknowledgement
* 0xAA read/schedule request for one DPID -> one immediate synthetic UUDT sample

The normal simulator remains unchanged and fail-closed. This wrapper is meant
only for an isolated VCX/UC2 bench with the vehicle disconnected. It does not
implement a periodic scheduler; periodic requests receive one immediate sample
so Atlas can learn the request/definition sequence without claiming ECU timing
behavior. Unknown dynamic PIDs remain rejected unless an explicit synthetic
fixture is added here.

Synthetic bytes are bench fixtures only. They are not vehicle measurements,
PID scaling claims, or confirmation of a signal meaning.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

import gds2_bench_simulator as base


# First directly observed from the 2026-09-14 isolated GDS2 HPCM2 Contactor
# Data session: 2C FE 43 0E. 0x00 is deliberately synthetic and carries no
# semantic claim. Related GM service literature associates PID 0x430E with a
# high-voltage contactor command/status parameter on another GM EV platform,
# but Atlas does not promote that mapping from this fixture alone.
OBSERVED_DYNAMIC_FIXTURES: dict[int, bytes] = {
    0x430E: b"\x00",
}


@dataclass
class DynamicDiscoveryState:
    definitions: dict[int, tuple[int, ...]] = field(default_factory=dict)

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

    def control(self, payload: bytes) -> base.Decision:
        if len(payload) < 2:
            return base.Decision(base.negative(0xAA, 0x12), "dynamicControlInvalidFormat")

        level = payload[1]
        if level == 0x00:
            # GMW3110 uses raw UUDT message number 0x00 as the positive response
            # to stopSending. The production simulator still remains unchanged.
            return base.Decision(
                b"\x00",
                "dynamicStop",
                "stopSending acknowledgement",
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

        mode = {
            0x01: "oneShot",
            0x02: "slowScheduleOneSample",
            0x03: "mediumScheduleOneSample",
            0x04: "fastScheduleOneSample",
        }[level]
        return base.Decision(
            sample,
            "dynamicSample",
            f"{mode} syntheticBenchData; periodic scheduler not emulated",
            transport="raw",
            response_channel="uudt",
        )


_ORIGINAL_DECIDE_RESPONSE = base.decide_response
_STATE = DynamicDiscoveryState()


def decide_response(payload: bytes, *, vin: str = base.DEFAULT_VIN, dids=None) -> base.Decision:
    if payload:
        if payload[0] == 0x2C:
            return _STATE.define(payload)
        if payload[0] == 0xAA:
            return _STATE.control(payload)
    return _ORIGINAL_DECIDE_RESPONSE(payload, vin=vin, dids=dids)


def main(argv: list[str] | None = None) -> int:
    base.decide_response = decide_response
    return base.main(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
