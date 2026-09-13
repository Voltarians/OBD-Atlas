#!/usr/bin/env python3
"""Read-only Chevrolet Volt Gen-1 ECU simulator for an isolated GDS2 bench.

Architecture:
    GDS2 -> J2534 provider -> VCX -> isolated 500 kbit/s CAN bench
         -> UC2 device 0 CAN1 -> this simulator

Atlas keeps module addressing in a machine-readable registry. Only registry
entries explicitly marked ``simulationStatus=implemented`` may transmit.
Observed-but-unconfirmed modules remain discovery-only and fail closed.

The vehicle MUST remain disconnected while simulator mode is active.
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

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

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = (
    REPO_ROOT / "assets" / "diagnostics" / "chevrolet_volt_gen1_bench_modules.json"
)
DEFAULT_MODULE_KEY = "hpcm2"
DEFAULT_VIN = "1G1RA6E40DU100001"

# Backward-compatible aliases for scripts/tests that referenced the original
# single-module implementation. Runtime addressing comes from the registry.
HPCM2_REQUEST_ID = 0x7E4
HPCM2_RESPONSE_ID = 0x7EC
HPCM2_UUDT_RESPONSE_ID = 0x5EC

# Synthetic GMLAN $1A identification fixtures. These values are deliberately
# obvious bench identities and are not claims about a real Chevrolet module.
LEGACY_1A_DIDS: dict[int, bytes] = {
    0xB4: b"OBDATLASBENCH001",       # Manufacturer traceability, 16 ASCII
    0xC1: bytes.fromhex("05E69EC1"), # GDS2 displays decimal 99000001
    0xC2: bytes.fromhex("05E69EC2"), # GDS2 displays decimal 99000002
    0xCB: bytes.fromhex("05E69EC3"), # GDS2 displays decimal 99000003
    0xCC: bytes.fromhex("05E69EC4"), # GDS2 displays decimal 99000004
}

# Plausible, static read-only values. Candidate DID meanings come from Atlas's
# Gen-1 HPCM2 evidence catalog. These bytes are simulator fixtures, not claims
# about exact physical values on a real vehicle.
DEFAULT_DIDS: dict[int, bytes] = {
    0x40E9: bytes.fromhex("0800"),
    0x41B0: bytes.fromhex("05DC"),
    0x41C4: bytes.fromhex("0096"),
    0x4329: bytes.fromhex("0094"),
    0x432B: bytes.fromhex("0098"),
    0x432C: bytes.fromhex("18"),
    0x433B: bytes.fromhex("02BC"),
    0x433C: bytes.fromhex("0320"),
    0x432D: bytes.fromhex("02DC"),
    0x4356: bytes.fromhex("0000"),
    0x43AF: bytes.fromhex("3200"),
    0x4369: bytes.fromhex("00"),
    0x4368: bytes.fromhex("00"),
    0x434F: bytes.fromhex("82"),
    0x801F: bytes.fromhex("82"),
}

BLOCKED_SERVICES = {
    0x14, 0x27, 0x28, 0x2E, 0x31, 0x34, 0x35, 0x36, 0x37, 0x3D, 0x85,
}


@dataclass(frozen=True)
class ModuleProfile:
    key: str
    name: str | None
    request_id: int
    normal_response_id: int | None
    uudt_response_id: int | None
    bitrate: int
    confidence: str
    simulation_status: str

    @property
    def implemented(self) -> bool:
        return self.simulation_status == "implemented"


@dataclass(frozen=True)
class Decision:
    response: bytes | None
    classification: str
    detail: str = ""
    transport: str = "isotp"
    response_channel: str = "normal"


def parse_can_id(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return int(value, 0)


def load_module_registry(path: Path = DEFAULT_REGISTRY_PATH) -> dict[str, ModuleProfile]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    modules: dict[str, ModuleProfile] = {}
    for item in raw.get("modules", []):
        profile = ModuleProfile(
            key=item["key"],
            name=item.get("module"),
            request_id=parse_can_id(item["requestCanId"]),
            normal_response_id=parse_can_id(item.get("normalResponseCanId")),
            uudt_response_id=parse_can_id(item.get("uudtResponseCanId")),
            bitrate=int(item.get("bitrate", 500000)),
            confidence=item.get("confidence", "unknown"),
            simulation_status=item.get("simulationStatus", "discoveryOnly"),
        )
        modules[profile.key] = profile
    if not modules:
        raise ValueError(f"module registry contains no modules: {path}")
    return modules


def select_module(
    key: str = DEFAULT_MODULE_KEY,
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    require_implemented: bool = True,
) -> ModuleProfile:
    modules = load_module_registry(registry_path)
    try:
        profile = modules[key]
    except KeyError as error:
        raise ValueError(f"unknown simulator module {key!r}") from error
    if require_implemented and not profile.implemented:
        raise ValueError(
            f"module {key!r} is {profile.simulation_status}; Atlas will not transmit for it"
        )
    if require_implemented and profile.normal_response_id is None:
        raise ValueError(f"implemented module {key!r} has no normal response CAN ID")
    return profile


def parse_single_frame(data: bytes) -> bytes | None:
    if not data or data[0] >> 4 != 0:
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
    """Return the safe HPCM2 bench response for one decoded diagnostic payload."""
    dids = DEFAULT_DIDS if dids is None else dids
    if not payload:
        return Decision(None, "malformed", "empty diagnostic payload")

    service = payload[0]
    if service in BLOCKED_SERVICES:
        nrc = 0x33 if service in {0x27, 0x2E, 0x31, 0x34, 0x35, 0x36, 0x37, 0x3D} else 0x11
        return Decision(negative(service, nrc), "blocked", f"service 0x{service:02X}")

    if service == 0x3E:
        if len(payload) == 1:
            return Decision(bytes((0x7E,)), "testerPresentLegacy")
        subfunction = payload[1]
        if subfunction & 0x80:
            return Decision(None, "testerPresentSuppressed")
        return Decision(bytes((0x7E, subfunction & 0x7F)), "testerPresent")

    if service == 0x10:
        if len(payload) < 2:
            return Decision(negative(service, 0x13), "malformed")
        subfunction = payload[1] & 0x7F
        if subfunction not in {0x01, 0x03}:
            return Decision(negative(service, 0x12), "unsupportedSession")
        return Decision(bytes((0x50, subfunction, 0x00, 0x32, 0x01, 0xF4)), "sessionControl")

    if service == 0x1A:
        if len(payload) != 2:
            return Decision(negative(service, 0x13), "malformed")
        did = payload[1]
        raw = vin.encode("ascii") if did == 0x90 else LEGACY_1A_DIDS.get(did)
        if raw is None:
            return Decision(negative(service, 0x31), "unknownLegacyDid", f"0x{did:02X}")
        return Decision(bytes((0x5A, did)) + raw, "readLegacyDid", f"0x{did:02X}")

    if service == 0x22:
        if len(payload) < 3 or (len(payload) - 1) % 2:
            return Decision(negative(service, 0x13), "malformed")
        response = bytearray((0x62,))
        for offset in range(1, len(payload), 2):
            did = (payload[offset] << 8) | payload[offset + 1]
            raw = vin.encode("ascii") if did == 0xF190 else dids.get(did)
            if raw is None:
                return Decision(negative(service, 0x31), "unknownDid", f"0x{did:04X}")
            response.extend((payload[offset], payload[offset + 1]))
            response.extend(raw)
        return Decision(bytes(response), "readDid")

    if service == 0x19:
        if len(payload) < 2:
            return Decision(negative(service, 0x13), "malformed")
        subfunction = payload[1]
        if subfunction == 0x01:
            return Decision(bytes((0x59, 0x01, 0xFF, 0x01, 0x00, 0x00)), "noDtcs")
        if subfunction == 0x02:
            return Decision(bytes((0x59, 0x02, 0xFF)), "noDtcs")
        return Decision(negative(service, 0x12), "unsupportedDtcSubfunction")

    if payload == bytes.fromhex("A9811A"):
        return Decision(
            bytes.fromhex("81000000FF"),
            "gmlanNoDtcs",
            "A9/81 endOfDTCReport",
            transport="raw",
            response_channel="uudt",
        )

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
                  vin: str, timeout_seconds: float, log_path: Path,
                  profile: ModuleProfile) -> int:
    check_layouts()
    if len(vin) != 17 or not vin.isascii():
        raise ValueError("simulator VIN must contain exactly 17 ASCII characters")
    if not profile.implemented:
        raise ValueError(f"refusing transmit for discovery-only module {profile.key}")
    if profile.normal_response_id is None:
        raise ValueError(f"module {profile.key} has no normal response CAN ID")

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

    def tx(can_id: int, data: bytes) -> None:
        frame = make_can_frame(can_id, data)
        count = int(transmit(DEVICE_TYPE, device, channel, C.byref(frame), 1))
        if count != 1:
            raise RuntimeError(f"VCI_Transmit expected 1 frame, returned {count}")
        logger.write("tx", can_id, data, module=profile.key)
        print(f"TX {can_id:03X}#{data.hex().upper()}", flush=True)

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
            if int(frame.ID) == profile.request_id and len(data) >= 3 and data[0] >> 4 == 3:
                flow_status = data[0] & 0x0F
                if flow_status != 0:
                    raise RuntimeError(f"unsupported ISO-TP flow status {flow_status}")
                return data[1], parse_stmin(data[2])
        raise RuntimeError("timed out waiting for ISO-TP flow control")

    def send_isotp(payload: bytes, response_can_id: int) -> None:
        frames = segment_isotp(payload)
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

    print("OBD Atlas GDS2 Bench Simulator", flush=True)
    print(f"UC2 device {device} CAN{channel} • {bitrate} bit/s • ACTIVE ISOLATED BENCH", flush=True)
    print(
        f"Module {profile.key}: {profile.name or 'unidentified'} • "
        f"request {profile.request_id:03X} -> response {profile.normal_response_id:03X}",
        flush=True,
    )
    if profile.uudt_response_id is not None:
        print(f"UUDT/data response {profile.uudt_response_id:03X}", flush=True)
    print(f"VIN {vin} • Log: {log_path}", flush=True)
    print("Safe services: 10, 19, 1A, 22, 3E, A9/81. Security/programming/write services are blocked.", flush=True)
    print("Unknown and discovery-only module requests are logged and never answered.", flush=True)

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

            if bool(frame.ExternFlag) or bool(frame.RemoteFlag) or can_id != profile.request_id:
                continue
            payload = parse_single_frame(data)
            if payload is None:
                key = f"{can_id:03X}#{data.hex().upper()}"
                unknown[key] = unknown.get(key, 0) + 1
                logger.write("event", can_id, data, classification="unsupportedRequestTransport")
                continue

            decision = decide_response(payload, vin=vin)
            logger.write(
                "decision", can_id, data, module=profile.key,
                classification=decision.classification, detail=decision.detail,
                transport=decision.transport, responseChannel=decision.response_channel,
                udsRequest=payload.hex().upper(),
                udsResponse=None if decision.response is None else decision.response.hex().upper(),
            )
            if decision.classification in {
                "unsupportedService", "unknownDid", "unknownLegacyDid", "unsupportedDtcSubfunction",
            }:
                key = payload.hex().upper()
                unknown[key] = unknown.get(key, 0) + 1
            if decision.response is None:
                continue

            if decision.response_channel == "uudt":
                if profile.uudt_response_id is None:
                    raise RuntimeError(f"module {profile.key} has no UUDT response CAN ID")
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


def print_module_registry(path: Path) -> None:
    for profile in load_module_registry(path).values():
        normal = "---" if profile.normal_response_id is None else f"0x{profile.normal_response_id:03X}"
        uudt = "---" if profile.uudt_response_id is None else f"0x{profile.uudt_response_id:03X}"
        name = profile.name or "unidentified"
        print(
            f"{profile.key:18s} request=0x{profile.request_id:03X} response={normal} "
            f"uudt={uudt} status={profile.simulation_status} confidence={profile.confidence} {name}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Atlas isolated read-only GDS2 ECU bench simulator.")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--channel", type=int, choices=(0, 1), default=1)
    parser.add_argument("--bitrate", type=int, choices=tuple(TIMING), default=500000)
    parser.add_argument("--vin", default=DEFAULT_VIN, help="Synthetic 17-character VIN returned by the simulated ECU.")
    parser.add_argument("--timeout", type=float, default=0.0, help="Seconds to run; 0 means until Ctrl+C.")
    parser.add_argument("--log", type=Path, help="JSONL log destination.")
    parser.add_argument("--library")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--module", default=DEFAULT_MODULE_KEY, help="Module key from the Atlas bench registry.")
    parser.add_argument("--list-modules", action="store_true", help="List registry modules and exit.")
    parser.add_argument("--confirm-isolated-bench", action="store_true")
    parser.add_argument("--check", action="store_true", help="Run simulator self-checks without hardware.")
    return parser


def self_check(registry_path: Path = DEFAULT_REGISTRY_PATH) -> None:
    check_layouts()
    profile = select_module(DEFAULT_MODULE_KEY, registry_path=registry_path)
    assert profile.request_id == HPCM2_REQUEST_ID
    assert profile.normal_response_id == HPCM2_RESPONSE_ID
    assert profile.uudt_response_id == HPCM2_UUDT_RESPONSE_ID
    assert parse_single_frame(bytes.fromhex("013E000000000000")) == bytes.fromhex("3E")
    assert decide_response(bytes.fromhex("3E")).response == bytes.fromhex("7E")
    assert decide_response(bytes.fromhex("3E00")).response == bytes.fromhex("7E00")
    assert decide_response(bytes.fromhex("1A90")).response == bytes.fromhex("5A90") + DEFAULT_VIN.encode("ascii")
    assert decide_response(bytes.fromhex("1ACC")).response == bytes.fromhex("5ACC05E69EC4")
    a9 = decide_response(bytes.fromhex("A9811A"))
    assert a9.classification == "gmlanNoDtcs"
    assert a9.response == bytes.fromhex("81000000FF")
    assert a9.transport == "raw" and a9.response_channel == "uudt"
    assert decide_response(bytes.fromhex("22432D")).response == bytes.fromhex("62432D02DC")
    assert decide_response(bytes.fromhex("27 01")).classification == "blocked"
    assert len(segment_isotp(bytes.fromhex("62F190") + DEFAULT_VIN.encode("ascii"))) > 1
    discovery = select_module("observed-0x259", registry_path=registry_path, require_implemented=False)
    assert not discovery.implemented
    assert discovery.normal_response_id is None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_modules:
        print_module_registry(args.registry)
        return 0
    if args.check:
        self_check(args.registry)
        print("GDS2 bench simulator self-check OK.")
        return 0
    try:
        profile = select_module(args.module, registry_path=args.registry)
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
    library_path = find_library(args.library)
    return run_simulator(
        library_path=library_path,
        device=args.device,
        channel=args.channel,
        bitrate=args.bitrate,
        vin=args.vin,
        timeout_seconds=args.timeout,
        log_path=args.log or default_log_path(),
        profile=profile,
    )


if __name__ == "__main__":
    raise SystemExit(main())
