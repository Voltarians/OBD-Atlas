#!/usr/bin/env python3
"""OBD Atlas passive CAN capture importer."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, Iterator


CANDUMP_RE = re.compile(
    r"^\((?P<timestamp>\d+(?:\.\d+)?)\)\s+"
    r"(?P<interface>\S+)\s+"
    r"(?P<can_id>[0-9A-Fa-f]{1,8})#(?P<data>[0-9A-Fa-f]*)$"
)

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    schema_name TEXT NOT NULL,
    capture_type TEXT NOT NULL,
    vehicle_platform TEXT,
    vehicle_model TEXT,
    vehicle_generation INTEGER,
    metadata_started_utc TEXT,
    first_can_frame_utc TEXT,
    last_can_frame_utc TEXT,
    can_duration_seconds REAL,
    audio_duration_seconds REAL,
    host TEXT,
    total_frames INTEGER NOT NULL,
    termination_reason TEXT,
    manifest_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS buses (
    session_id TEXT NOT NULL,
    logged_interface TEXT NOT NULL,
    atlas_bus TEXT NOT NULL,
    adapter TEXT,
    adapter_channel INTEGER,
    bitrate INTEGER,
    mode TEXT,
    frames INTEGER NOT NULL,
    unique_arbitration_ids INTEGER NOT NULL,
    captured INTEGER NOT NULL,
    details_json TEXT NOT NULL,
    PRIMARY KEY (session_id, logged_interface),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS capture_files (
    session_id TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    format TEXT,
    size_bytes INTEGER,
    sha256 TEXT,
    verified INTEGER NOT NULL,
    PRIMARY KEY (session_id, name),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS frames (
    session_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    logged_interface TEXT NOT NULL,
    arbitration_id INTEGER NOT NULL,
    is_extended INTEGER NOT NULL,
    dlc INTEGER NOT NULL,
    data BLOB NOT NULL,
    PRIMARY KEY (session_id, sequence),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_frames_session_interface_time
    ON frames(session_id, logged_interface, timestamp);
CREATE INDEX IF NOT EXISTS idx_frames_session_interface_id
    ON frames(session_id, logged_interface, arbitration_id);
"""


class AtlasError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AtlasError(f"Cannot read manifest {path}: {exc}") from exc

    required = ("schema", "session_id", "capture_type", "buses", "files")
    missing = [key for key in required if key not in manifest]
    if missing:
        raise AtlasError(f"Manifest is missing required field(s): {', '.join(missing)}")
    if manifest["schema"] != "voltec-atlas.capture-session.v1":
        raise AtlasError(f"Unsupported manifest schema: {manifest['schema']}")
    if not isinstance(manifest["buses"], list) or not manifest["buses"]:
        raise AtlasError("Manifest buses must be a non-empty list")
    if not isinstance(manifest["files"], list) or not manifest["files"]:
        raise AtlasError("Manifest files must be a non-empty list")
    return manifest


def resolve_capture_files(manifest: dict, source_dir: Path, verify: bool) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    for item in manifest["files"]:
        name = item.get("name")
        role = item.get("role")
        if not name or not role:
            raise AtlasError("Every file entry requires name and role")
        path = source_dir / name
        if not path.is_file():
            raise AtlasError(f"Required capture file is missing: {path}")
        expected_size = item.get("size_bytes")
        if expected_size is not None and path.stat().st_size != expected_size:
            raise AtlasError(
                f"Size mismatch for {name}: expected {expected_size}, got {path.stat().st_size}"
            )
        if verify and item.get("sha256"):
            actual = sha256_file(path)
            if actual.lower() != str(item["sha256"]).lower():
                raise AtlasError(f"SHA-256 mismatch for {name}")
        resolved[role] = path
    if "candump_log" not in resolved:
        raise AtlasError("Manifest does not identify a candump_log file")
    return resolved


def iter_candump(path: Path) -> Iterator[tuple[int, float, str, int, int, int, bytes]]:
    with path.open("rt", encoding="utf-8", errors="strict") as handle:
        for sequence, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            match = CANDUMP_RE.match(line)
            if not match:
                raise AtlasError(f"Malformed candump line {sequence}: {line[:160]}")
            can_id_text = match.group("can_id")
            data_text = match.group("data")
            if len(data_text) % 2:
                raise AtlasError(f"Odd-length CAN data at line {sequence}")
            data = bytes.fromhex(data_text)
            if len(data) > 8:
                raise AtlasError(f"Classic CAN payload exceeds 8 bytes at line {sequence}")
            yield (
                sequence,
                float(match.group("timestamp")),
                match.group("interface"),
                int(can_id_text, 16),
                int(len(can_id_text) > 3),
                len(data),
                data,
            )


def batched(rows: Iterable[tuple], size: int = 10_000) -> Iterator[list[tuple]]:
    batch: list[tuple] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def open_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.executescript(SCHEMA_SQL)
    connection.commit()
    return connection


def ingest(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    source_dir = (args.source_dir or manifest_path.parent).resolve()
    manifest = load_manifest(manifest_path)
    files = resolve_capture_files(manifest, source_dir, not args.skip_hash_check)
    session_id = str(manifest["session_id"])

    connection = open_database(args.database.resolve())
    try:
        exists = connection.execute(
            "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if exists and not args.replace:
            raise AtlasError(
                f"Session {session_id} already exists; use --replace to re-import it"
            )

        with connection:
            if exists:
                connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

            vehicle = manifest.get("vehicle", {})
            time = manifest.get("time", {})
            status = manifest.get("capture_status", {})
            connection.execute(
                """
                INSERT INTO sessions (
                    session_id, schema_name, capture_type, vehicle_platform,
                    vehicle_model, vehicle_generation, metadata_started_utc,
                    first_can_frame_utc, last_can_frame_utc, can_duration_seconds,
                    audio_duration_seconds, host, total_frames, termination_reason,
                    manifest_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    manifest["schema"],
                    manifest["capture_type"],
                    vehicle.get("platform"),
                    vehicle.get("model"),
                    vehicle.get("generation"),
                    time.get("metadata_started_utc"),
                    time.get("first_can_frame_utc"),
                    time.get("last_can_frame_utc"),
                    time.get("can_duration_seconds"),
                    time.get("audio_duration_seconds"),
                    manifest.get("host"),
                    status.get("total_frames", 0),
                    status.get("termination_reason"),
                    json.dumps(manifest, separators=(",", ":"), sort_keys=True),
                ),
            )

            for bus in manifest["buses"]:
                connection.execute(
                    """
                    INSERT INTO buses (
                        session_id, logged_interface, atlas_bus, adapter,
                        adapter_channel, bitrate, mode, frames,
                        unique_arbitration_ids, captured, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        bus["logged_interface"],
                        bus["atlas_bus"],
                        bus.get("adapter"),
                        bus.get("adapter_channel"),
                        bus.get("bitrate"),
                        bus.get("mode"),
                        bus.get("frames", 0),
                        bus.get("unique_arbitration_ids", 0),
                        int(bool(bus.get("captured"))),
                        json.dumps(bus, separators=(",", ":"), sort_keys=True),
                    ),
                )

            for item in manifest["files"]:
                connection.execute(
                    """
                    INSERT INTO capture_files (
                        session_id, name, role, format, size_bytes, sha256, verified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        item["name"],
                        item["role"],
                        item.get("format"),
                        item.get("size_bytes"),
                        item.get("sha256"),
                        int(not args.skip_hash_check),
                    ),
                )

            inserted = 0
            rows = (
                (session_id, *frame)
                for frame in iter_candump(files["candump_log"])
            )
            for batch in batched(rows):
                connection.executemany(
                    """
                    INSERT INTO frames (
                        session_id, sequence, timestamp, logged_interface,
                        arbitration_id, is_extended, dlc, data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    batch,
                )
                inserted += len(batch)

            expected = int(status.get("total_frames", inserted))
            if inserted != expected:
                raise AtlasError(
                    f"Frame-count mismatch: manifest says {expected}, parsed {inserted}"
                )

        # Success means a reader can observe the entire session after commit.
        connection.commit()
        persisted_session = connection.execute(
            "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        persisted_frames = connection.execute(
            "SELECT COUNT(*) FROM frames WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        if not persisted_session or persisted_frames != inserted:
            raise AtlasError(
                "Post-commit verification failed: "
                f"expected {inserted} frames, found {persisted_frames}"
            )

        print(f"Imported session: {session_id}")
        print(f"Database: {args.database.resolve()}")
        print(f"Frames: {inserted}")
        return 0
    finally:
        connection.close()


def summary(args: argparse.Namespace) -> int:
    if not args.database.is_file():
        raise AtlasError(f"Database does not exist: {args.database}")
    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    try:
        sessions = connection.execute(
            """
            SELECT session_id, vehicle_model, vehicle_generation,
                   can_duration_seconds, audio_duration_seconds, total_frames,
                   termination_reason
            FROM sessions
            ORDER BY metadata_started_utc
            """
        ).fetchall()
        if not sessions:
            print("Atlas database contains no sessions.")
            return 0
        for session in sessions:
            print(f"Session: {session['session_id']}")
            print(
                f"  Vehicle: {session['vehicle_model']} Gen {session['vehicle_generation']}"
            )
            print(
                f"  Frames: {session['total_frames']}  "
                f"CAN duration: {session['can_duration_seconds']:.3f}s  "
                f"Audio: {session['audio_duration_seconds']:.3f}s"
            )
            buses = connection.execute(
                """
                SELECT logged_interface, atlas_bus, frames, unique_arbitration_ids,
                       captured
                FROM buses WHERE session_id = ? ORDER BY logged_interface
                """,
                (session["session_id"],),
            ).fetchall()
            for bus in buses:
                state = "captured" if bus["captured"] else "no frames"
                print(
                    f"  {bus['logged_interface']}: {bus['atlas_bus']} — "
                    f"{bus['frames']} frames, {bus['unique_arbitration_ids']} IDs ({state})"
                )
            if session["termination_reason"]:
                print(f"  Ended: {session['termination_reason']}")
        return 0
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OBD Atlas passive CAN capture tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Import a capture session")
    ingest_parser.add_argument("manifest", type=Path)
    ingest_parser.add_argument(
        "--database", type=Path, default=Path("obd_atlas.sqlite3")
    )
    ingest_parser.add_argument("--source-dir", type=Path)
    ingest_parser.add_argument("--replace", action="store_true")
    ingest_parser.add_argument("--skip-hash-check", action="store_true")
    ingest_parser.set_defaults(func=ingest)

    summary_parser = subparsers.add_parser("summary", help="Summarize imported sessions")
    summary_parser.add_argument(
        "--database", type=Path, default=Path("obd_atlas.sqlite3")
    )
    summary_parser.set_defaults(func=summary)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except AtlasError as exc:
        print(f"Atlas error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
