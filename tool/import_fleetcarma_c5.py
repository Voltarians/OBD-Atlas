#!/usr/bin/env python3
"""Import FleetCarma C5 binary logs into Atlas-friendly CSV/candump/JSON.

Supported C5 TLVs recovered from a Chevrolet Volt FleetCarma logger:
  0x01 len=5   configured CAN ID
  0x05 len=16  CAN frame
  0x24 len>=4  GPS/NMEA record

Input may be a single .BIN file, a directory containing .BIN files, or a ZIP
archive containing FleetCarma LOGS/*.BIN files. Malformed/truncated tails are
flagged while valid records before the tail are preserved.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import pathlib
import zipfile
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Iterator


@dataclass(frozen=True)
class CanRecord:
    source: str
    offset: int
    timestamp_ms: int
    bus: int
    can_id: int
    data: bytes


@dataclass(frozen=True)
class GpsRecord:
    source: str
    offset: int
    timestamp_ms: int
    sentence: str


@dataclass(frozen=True)
class ConfiguredId:
    source: str
    offset: int
    bus: int
    can_id: int
    config_value: int


@dataclass
class DecodeResult:
    can: list[CanRecord]
    gps: list[GpsRecord]
    configured_ids: list[ConfiguredId]
    malformed_tail: bool
    bytes_consumed: int


def decode_blob(blob: bytes, source: str = "<memory>") -> DecodeResult:
    can: list[CanRecord] = []
    gps: list[GpsRecord] = []
    configured: list[ConfiguredId] = []
    offset = 0
    malformed = False

    while offset + 2 <= len(blob):
        rec_type = blob[offset]
        length = blob[offset + 1]
        start = offset + 2
        end = start + length
        if end > len(blob):
            malformed = True
            break

        payload = blob[start:end]

        if rec_type == 0x01 and length == 5:
            configured.append(
                ConfiguredId(
                    source=source,
                    offset=offset,
                    bus=payload[0],
                    can_id=int.from_bytes(payload[1:3], "little"),
                    config_value=int.from_bytes(payload[3:5], "little", signed=True),
                )
            )

        elif rec_type == 0x05 and length == 16:
            bus = payload[0]
            can_id = int.from_bytes(payload[1:3], "little")
            dlc = payload[3]
            timestamp_ms = int.from_bytes(payload[4:8], "little")
            if 1 <= bus <= 5 and can_id <= 0x7FF and dlc <= 8:
                can.append(
                    CanRecord(
                        source=source,
                        offset=offset,
                        timestamp_ms=timestamp_ms,
                        bus=bus,
                        can_id=can_id,
                        data=bytes(payload[8:8 + dlc]),
                    )
                )

        elif rec_type == 0x24 and length >= 4:
            timestamp_ms = int.from_bytes(payload[:4], "little")
            sentence = payload[4:].decode("ascii", errors="replace").rstrip("\x00\r\n")
            if sentence:
                gps.append(
                    GpsRecord(
                        source=source,
                        offset=offset,
                        timestamp_ms=timestamp_ms,
                        sentence=sentence,
                    )
                )

        offset = end

    if offset != len(blob):
        malformed = True

    return DecodeResult(can, gps, configured, malformed, offset)


def iter_inputs(path: pathlib.Path) -> Iterator[tuple[str, bytes]]:
    if path.is_file() and path.suffix.lower() == ".bin":
        yield path.name, path.read_bytes()
        return

    if path.is_dir():
        for p in sorted(path.rglob("*.BIN")):
            yield p.name, p.read_bytes()
        return

    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            for name in sorted(
                n for n in zf.namelist()
                if n.upper().endswith(".BIN") and not n.endswith("/")
            ):
                yield pathlib.PurePosixPath(name).name, zf.read(name)
        return

    raise ValueError("input must be a .BIN file, directory, or ZIP archive")


def write_outputs(input_path: pathlib.Path, out_dir: pathlib.Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "fleetcarma_can.csv"
    candump_path = out_dir / "fleetcarma_candump.log"
    gps_path = out_dir / "fleetcarma_gps.csv"
    sessions_path = out_dir / "fleetcarma_sessions.csv"
    summary_path = out_dir / "fleetcarma_summary.json"

    id_counts: Counter[tuple[int, int]] = Counter()
    total_can = total_gps = malformed_files = file_count = 0

    with csv_path.open("w", newline="", encoding="utf-8") as csvf,          candump_path.open("w", encoding="utf-8") as logf,          gps_path.open("w", newline="", encoding="utf-8") as gpsf,          sessions_path.open("w", newline="", encoding="utf-8") as sesf:

        canw = csv.writer(csvf)
        canw.writerow([
            "source", "offset", "timestamp_ms", "timestamp_s",
            "bus", "can_id_hex", "can_id_dec", "dlc", "data_hex",
        ])
        gpsw = csv.writer(gpsf)
        gpsw.writerow(["source", "offset", "timestamp_ms", "timestamp_s", "sentence"])
        sesw = csv.writer(sesf)
        sesw.writerow([
            "source", "can_frames", "gps_records", "configured_ids",
            "malformed_tail", "bytes_consumed",
        ])

        for source, blob in iter_inputs(input_path):
            file_count += 1
            result = decode_blob(blob, source)
            malformed_files += int(result.malformed_tail)
            total_can += len(result.can)
            total_gps += len(result.gps)

            for rec in result.can:
                id_counts[(rec.bus, rec.can_id)] += 1
                canw.writerow([
                    rec.source,
                    rec.offset,
                    rec.timestamp_ms,
                    f"{rec.timestamp_ms / 1000.0:.6f}",
                    rec.bus,
                    f"{rec.can_id:03X}",
                    rec.can_id,
                    len(rec.data),
                    rec.data.hex().upper(),
                ])
                logf.write(
                    f"({rec.timestamp_ms / 1000.0:.6f}) "
                    f"can{rec.bus - 1} {rec.can_id:03X}#"
                    f"{rec.data.hex().upper()}\n"
                )

            for rec in result.gps:
                gpsw.writerow([
                    rec.source,
                    rec.offset,
                    rec.timestamp_ms,
                    f"{rec.timestamp_ms / 1000.0:.6f}",
                    rec.sentence,
                ])

            sesw.writerow([
                source,
                len(result.can),
                len(result.gps),
                len(result.configured_ids),
                int(result.malformed_tail),
                result.bytes_consumed,
            ])

    summary = {
        "schema": "atlas.fleetcarma-c5-import.v1",
        "input": str(input_path),
        "files": file_count,
        "can_frames": total_can,
        "gps_records": total_gps,
        "files_with_malformed_tail": malformed_files,
        "bus_id_counts": [
            {"bus": bus, "can_id_hex": f"{can_id:03X}", "frames": count}
            for (bus, can_id), count in sorted(id_counts.items())
        ],
        "outputs": {
            "csv": csv_path.name,
            "candump": candump_path.name,
            "gps": gps_path.name,
            "sessions": sessions_path.name,
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("fleetcarma_import"),
    )
    args = parser.parse_args()

    summary = write_outputs(args.input, args.output)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
