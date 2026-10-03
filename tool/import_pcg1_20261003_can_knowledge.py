#!/usr/bin/env python3
"""Seed 106 PCG-1 Gen-1 Volt CAN observations from the 2026-10-03 capture."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path


CATALOG_ID = "chevrolet-volt-gen1-pcg1-20261003"
SOURCE_CAPTURE = "atlas_capture_20261003_045041.log"

SCHEMA = """
CREATE TABLE IF NOT EXISTS can_knowledge (
    catalog_id TEXT NOT NULL,
    vehicle_make TEXT NOT NULL,
    vehicle_model TEXT NOT NULL,
    vehicle_generation INTEGER NOT NULL,
    logged_bus TEXT NOT NULL,
    network TEXT NOT NULL,
    network_confidence TEXT NOT NULL,
    bitrate_kbps INTEGER NOT NULL,
    arbitration_id INTEGER NOT NULL,
    is_extended INTEGER NOT NULL,
    structural_class TEXT NOT NULL,
    semantic_status TEXT NOT NULL,
    evidence_status TEXT NOT NULL,
    source_capture TEXT NOT NULL,
    notes TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    PRIMARY KEY (catalog_id, network, bitrate_kbps, arbitration_id, source_capture)
);
CREATE INDEX IF NOT EXISTS idx_can_knowledge_network_id
    ON can_knowledge(network, bitrate_kbps, arbitration_id);
"""


def _entry(bus: str, network: str, can_id: int, structural: str,
           semantic: str, notes: str = "", confidence: str = "high") -> dict:
    return {
        "catalog_id": CATALOG_ID,
        "vehicle_make": "Chevrolet",
        "vehicle_model": "Volt",
        "vehicle_generation": 1,
        "logged_bus": bus,
        "network": network,
        "network_confidence": confidence,
        "bitrate_kbps": 500,
        "arbitration_id": can_id,
        "is_extended": 0,
        "structural_class": structural,
        "semantic_status": semantic,
        "evidence_status": "observed_and_structurally_characterized",
        "source_capture": SOURCE_CAPTURE,
        "notes": notes,
    }


def build_entries() -> list[dict]:
    rows: list[dict] = []

    # can0: Chassis Expansion candidate. Hardware-network assignment is not yet
    # promoted to high confidence, so preserve it explicitly as candidate.
    rows.extend([
        _entry("can0", "chassis_expansion_candidate", 0x121, "STATIC",
               "heartbeat_status_candidate", "DLC1 payload 0x06; ~10 Hz.",
               "candidate"),
        _entry("can0", "chassis_expansion_candidate", 0x122, "STATIC",
               "heartbeat_status_candidate", "DLC1 payload 0x0A; ~10 Hz.",
               "candidate"),
        _entry("can0", "chassis_expansion_candidate", 0x130,
               "STRUCTURALLY_DECODED", "candidate_signal_plus_integrity",
               "100 Hz; modulo-4 state; verified checksum; B1 strong yaw-rate "
               "candidate; B3:B4 signed10 stationary field.", "candidate"),
        _entry("can0", "chassis_expansion_candidate", 0x235,
               "STRUCTURALLY_DECODED", "alive_integrity",
               "100 Hz; four deterministic states; modulo-4 alive/integrity.",
               "candidate"),
    ])

    # can1: Primary Powertrain. These were NO_CURRENT_REFERENCE in the
    # network-aware audit. Group structural-only entries compactly.
    static_ids = [
        0x096,0x098,0x0B1,0x0BA,0x0BB,0x0C7,0x0D3,0x130,0x139,0x182,
        0x186,0x1A3,0x1C5,0x1DF,0x222,0x2C3,0x3C1,0x3C9,0x3CB,0x3DC,
        0x3ED,0x3F9,0x3FB,0x3FC,0x451,0x4C5,0x4CB,0x4D1,0x4D7,0x4D9,
        0x4F1,0x500,0x52A,0x530,0x770,0x772,0x773,0x77D,0x77F,0x787,
    ]
    for can_id in static_ids:
        rows.append(_entry("can1", "primary_powertrain", can_id,
                           "STATIC", "static_observed"))

    cycle_groups = {
        "EXACT_CYCLE_4": [0x0AA,0x0B9,0x0C1,0x0C5,0x1C6,0x1F3,0x1FB,0x236,0x287],
        "EXACT_CYCLE_20": [0x226],
        "EXACT_CYCLE_32": [0x224,0x2F1],
    }
    for structural, ids in cycle_groups.items():
        for can_id in ids:
            rows.append(_entry("can1", "primary_powertrain", can_id,
                               structural, "integrity_cycle"))

    can1_dynamic = {
        0x097: ("VERY_LOW_CARDINALITY_DYNAMIC", "low_cardinality_unknown",
                "B1/B5 change sparsely across four payload states."),
        0x0BC: ("LOW_CARDINALITY_DYNAMIC", "low_cardinality_unknown",
                "B3 only; 11 observed values."),
        0x137: ("MID_CARDINALITY_DYNAMIC", "timebase_candidate",
                "B0 advances once/minute and wraps 59->0; higher-order companion fields."),
        0x185: ("VERY_LOW_CARDINALITY_DYNAMIC", "low_cardinality_unknown",
                "B1 values 0xFC..0xFF."),
        0x1EB: ("VERY_LOW_CARDINALITY_DYNAMIC", "low_cardinality_unknown",
                "B1 values 0x4C..0x4E."),
        0x238: ("VERY_LOW_CARDINALITY_DYNAMIC", "low_cardinality_unknown",
                "B0 values 0x73..0x76; 12-V hypothesis not yet promoted."),
        0x3DD: ("MID_CARDINALITY_DYNAMIC", "minute_counter",
                "B4 increments exactly once per ~60 s."),
        0x3E3: ("LOW_CARDINALITY_DYNAMIC", "low_cardinality_unknown",
                "B2/B6 vary across five observed payload states."),
        0x4C7: ("MID_CARDINALITY_DYNAMIC", "thirty_second_counter",
                "(B0<<8)|B1 increments every ~30 s; observed 0x1DFF->0x1E00 carry."),
        0x4C9: ("VERY_LOW_CARDINALITY_DYNAMIC", "two_state_unknown",
                "B1 0x60/0x61."),
        0x4E9: ("MID_CARDINALITY_DYNAMIC", "minute_counter",
                "B4 increments once per ~60 s, phase shifted from 0x3DD."),
        0x589: ("STRUCTURALLY_DECODED", "mux_table",
                "32-slot table selected by B0[7:3]; 24 fixed slots, 8 sparse variable slots."),
    }
    for can_id, (structural, semantic, notes) in can1_dynamic.items():
        rows.append(_entry("can1", "primary_powertrain", can_id,
                           structural, semantic, notes))

    # can2: HV Energy Management.
    can2 = {
        0x208: ("EXACT_CYCLE_8", "integrity_cycle", "Exact deterministic 8-state cycle."),
        0x20A: ("STATIC", "static_observed", "DLC1 payload 0x40."),
        0x20C: ("STATIC", "static_observed", "DLC2 payload 0200."),
        0x20E: ("EXACT_CYCLE_3", "integrity_cycle", "Exact 3-state cycle."),
        0x264: ("STATIC", "static_observed", "DLC2 payload 1FFF."),
        0x266: ("EXACT_CYCLE_32", "integrity_table", "Deterministic 32-state table."),
        0x268: ("IDENTIFICATION_BROADCAST", "k57_software_identification",
                "48-frame mux; six populated K57 software/calibration identifiers."),
        0x270: ("EXACT_CYCLE_32", "integrity_table", "Deterministic 32-state table."),
        0x272: ("EXACT_CYCLE_32", "alive_counter", "Pure deterministic 32-state alive pattern."),
        0x274: ("EXACT_CYCLE_32", "integrity_table", "Deterministic 32-state companion."),
        0x300: ("STATIC", "static_observed", "Payload 8000000000000000."),
        0x303: ("STATIC", "static_observed", "Payload 0080000080002000."),
        0x400: ("STATIC", "static_observed", "DLC5 all zero."),
        0x500: ("STATIC", "static_observed", "DLC8 all zero."),
    }
    for can_id, (structural, semantic, notes) in can2.items():
        rows.append(_entry("can2", "hv_energy_management", can_id,
                           structural, semantic, notes))

    # can3: Powertrain Expansion. 0x1D4/0x1D6 and 0x184 are existing/reference
    # matches, so they are intentionally not part of these 24 new entries.
    can3 = {
        0x0A5: ("STATIC","static_observed","DLC8 07651A0000000000."),
        0x0A7: ("STATIC","static_observed","DLC8 07651A0000000000."),
        0x181: ("EXACT_CYCLE_4","integrity_cycle","Exact deterministic four-state cycle."),
        0x187: ("EXACT_CYCLE_8","integrity_cycle","Exact deterministic eight-state cycle."),
        0x18C: ("STATIC","static_observed","Static in stationary capture."),
        0x18D: ("VERY_LOW_CARDINALITY_DYNAMIC","transient_status_unknown",
                "B7 normally 0x33 with short 0x00 pulses."),
        0x1C2: ("STATIC","static_observed","Static in stationary capture."),
        0x1D1: ("MID_CARDINALITY_DYNAMIC","analog_like_unknown",
                "B2 has 13 adjacent values 0xA9..0xB5; no decoded can2 equivalent."),
        0x1D8: ("STATIC","static_observed","Static in stationary capture."),
        0x1E3: ("VERY_LOW_CARDINALITY_DYNAMIC","transient_status_unknown",
                "B1 mainly 0x01 with rare 0x02 pulses."),
        0x281: ("EXACT_CYCLE_4","integrity_cycle","Exact deterministic four-state cycle."),
        0x291: ("STATIC","static_observed","Static in stationary capture."),
        0x2E1: ("STATIC","static_observed","All zero in stationary capture."),
        0x3C4: ("VERY_LOW_CARDINALITY_DYNAMIC","step_state_unknown",
                "B3 0x42/0x43; one observed transition."),
        0x3C5: ("STATIC","static_observed","Static in stationary capture."),
        0x3D5: ("STATIC","static_observed","Static in stationary capture."),
        0x3D7: ("VERY_LOW_CARDINALITY_DYNAMIC","two_state_unknown",
                "B1 0xBB/0xBC; not supported as 12-V/pack-voltage duplicate."),
        0x3DA: ("LOW_CARDINALITY_DYNAMIC","coarse_step_state_unknown",
                "B7 0x0E/0x0F/0x10; two observed transitions."),
        0x3DB: ("STATIC","static_observed","Static in stationary capture."),
        0x3DF: ("VERY_LOW_CARDINALITY_DYNAMIC","late_event_state_unknown",
                "B0 0x41/0x42; activity concentrated late in capture."),
        0x3FF: ("STATIC","static_observed","Static in stationary capture."),
        0x489: ("STATIC","static_observed","Static in stationary capture."),
        0x495: ("EXACT_CYCLE_32","timebase_integrity_table",
                "B0 rolls 0..31; deterministic ~1 Hz 32-state table."),
        0x4C2: ("STATIC","static_observed","All-zero payload in stationary capture."),
    }
    for can_id, (structural, semantic, notes) in can3.items():
        rows.append(_entry("can3", "powertrain_expansion", can_id,
                           structural, semantic, notes))

    return rows


def validate_entries(rows: list[dict]) -> None:
    if len(rows) != 106:
        raise RuntimeError(f"Expected 106 entries, got {len(rows)}")
    counts = Counter(row["logged_bus"] for row in rows)
    expected = {"can0": 4, "can1": 64, "can2": 14, "can3": 24}
    if dict(counts) != expected:
        raise RuntimeError(f"Unexpected bus counts: {dict(counts)}")
    keys = {
        (row["network"], row["bitrate_kbps"], row["arbitration_id"])
        for row in rows
    }
    if len(keys) != len(rows):
        raise RuntimeError("Duplicate network-scoped CAN identity in seed data")


def import_entries(database: Path, replace: bool = False) -> int:
    rows = build_entries()
    validate_entries(rows)
    connection = sqlite3.connect(database)
    try:
        connection.executescript(SCHEMA)
        existing = connection.execute(
            "SELECT COUNT(*) FROM can_knowledge WHERE catalog_id = ?",
            (CATALOG_ID,),
        ).fetchone()[0]
        if existing and not replace:
            raise RuntimeError(
                f"{CATALOG_ID} already contains {existing} rows; use --replace"
            )
        with connection:
            if existing:
                connection.execute(
                    "DELETE FROM can_knowledge WHERE catalog_id = ?", (CATALOG_ID,)
                )
            for row in rows:
                evidence_json = json.dumps(row, sort_keys=True, separators=(",", ":"))
                connection.execute(
                    """
                    INSERT INTO can_knowledge (
                        catalog_id, vehicle_make, vehicle_model, vehicle_generation,
                        logged_bus, network, network_confidence, bitrate_kbps,
                        arbitration_id, is_extended, structural_class, semantic_status,
                        evidence_status, source_capture, notes, evidence_json
                    ) VALUES (
                        :catalog_id, :vehicle_make, :vehicle_model, :vehicle_generation,
                        :logged_bus, :network, :network_confidence, :bitrate_kbps,
                        :arbitration_id, :is_extended, :structural_class, :semantic_status,
                        :evidence_status, :source_capture, :notes, :evidence_json
                    )
                    """,
                    {**row, "evidence_json": evidence_json},
                )
        count = connection.execute(
            "SELECT COUNT(*) FROM can_knowledge WHERE catalog_id = ?", (CATALOG_ID,)
        ).fetchone()[0]
    finally:
        connection.close()
    if count != 106:
        raise RuntimeError(f"Expected 106 database rows, got {count}")
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import the 2026-10-03 PCG-1 Gen-1 Volt CAN knowledge set"
    )
    parser.add_argument("--database", type=Path, default=Path("obd_atlas.sqlite3"))
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    count = import_entries(args.database.resolve(), replace=args.replace)
    print(f"Imported {count} PCG-1 CAN knowledge entries into {args.database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
