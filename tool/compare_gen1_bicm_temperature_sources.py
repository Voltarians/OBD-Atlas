#!/usr/bin/env python3
"""Offline comparison of Gen-1 internal BICM temperature interpretations.

Reads passive candump logs, never transmits. Does not claim either formula is
verified. Requires frames captured from the *125 kbit/s internal bus*, not
same-numbered IDs from other vehicle networks.
"""
import argparse
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decode_gen1_internal_bms as dbc

YS_FIRST = {0x7E0, 0x7E1, 0x7E8, 0x7EC, 0x7ED}
YS_SECOND = {0x7E2, 0x7E5, 0x7E9}

def compare(lines, registry):
    output = []
    for frame in dbc.parse_frames(lines):
        if not 0x7E0 <= frame.can_id <= 0x7EF:
            continue
        defs = [d for d in registry.get(frame.can_id, []) if d.unit == "C"]
        for pair_index, allowed in enumerate((YS_FIRST, YS_SECOND)):
            start = pair_index * 2
            if frame.can_id not in allowed or len(frame.data) < start + 2:
                continue
            raw = ((frame.data[start] & 15) << 8) | frame.data[start + 1]
            yasko_c = 110.7 - raw * 0.0294
            for definition in defs:
                try:
                    dbc_c = dbc.decode_signal(frame.data, definition)
                except ValueError:
                    continue
                output.append({
                    "timestamp": frame.timestamp, "bus": frame.bus,
                    "can_id": f"0x{frame.can_id:03X}", "payload": frame.data.hex().upper(),
                    "dbc_signal": definition.signal_name,
                    "tom_evnut_c": round(dbc_c, 4),
                    "yasko_c": round(yasko_c, 4),
                    "difference_c": round(dbc_c - yasko_c, 4),
                    "status": "experimental_unverified",
                })
    return output

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("internal_125k_log", type=Path)
    p.add_argument("--registry", type=Path, default=dbc.DEFAULT_REGISTRY)
    p.add_argument("--csv-out", type=Path)
    p.add_argument("--json-out", type=Path)
    args = p.parse_args()
    with args.internal_125k_log.open(encoding="utf-8", errors="replace") as f:
        rows = compare(f, dbc.load_registry(args.registry))
    report = {
        "network": "internal_becm_bicm", "bitrateKbps": 125,
        "status": "experimental_unverified",
        "warning": "CAN IDs alone do not identify a network; only supply a verified internal 125k capture.",
        "comparisonRows": len(rows), "rows": rows,
    }
    if args.csv_out:
        with args.csv_out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["timestamp","bus","can_id","payload","dbc_signal","tom_evnut_c","yasko_c","difference_c","status"])
            w.writeheader()
            w.writerows(rows)
    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    else:
        print(json.dumps(report, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
