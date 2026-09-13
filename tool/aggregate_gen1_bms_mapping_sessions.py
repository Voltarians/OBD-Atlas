#!/usr/bin/env python3
"""Aggregate independent Gen-1 BMS correlation reports.

Three or more independent sessions that agree on a cell-to-slot pairing may be
labeled repeatableCrossSessionCandidate. This tool never labels a mapping
confirmed; promotion remains an explicit evidence-review step.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def aggregate(results: list[dict]) -> dict:
    by_cell = defaultdict(list)
    for session_index, result in enumerate(results, start=1):
        for row in result.get("mapping", []):
            by_cell[row["cell"]].append(
                {
                    "session": session_index,
                    "slot": row["slot"],
                    "score": float(row["score"]),
                    "rmseV": float(row["rmseV"]),
                    "confidence": row["confidence"],
                }
            )

    rows = []
    for cell in sorted(by_cell):
        observations = by_cell[cell]
        slots = {item["slot"] for item in observations}
        same_slot = len(slots) == 1
        session_count = len(observations)
        mean_score = sum(item["score"] for item in observations) / session_count
        max_rmse = max(item["rmseV"] for item in observations)

        if (
            session_count >= 3
            and same_slot
            and mean_score >= 0.90
            and max_rmse <= 0.003
            and all(item["confidence"] == "strongCandidate" for item in observations)
        ):
            status = "repeatableCrossSessionCandidate"
        elif not same_slot:
            status = "inconsistentAcrossSessions"
        else:
            status = "needsMoreEvidence"

        rows.append(
            {
                "cell": cell,
                "slot": observations[0]["slot"] if same_slot else None,
                "sessions": session_count,
                "meanScore": round(mean_score, 6),
                "maxRmseV": round(max_rmse, 6),
                "status": status,
                "observations": observations,
            }
        )

    return {
        "sessionCount": len(results),
        "mappingStatus": "candidateOnly",
        "promotionRule": (
            "repeatableCrossSessionCandidate requires >=3 agreeing independent sessions, "
            "mean score >=0.90, max RMSE <=3 mV, and strongCandidate in every session"
        ),
        "evidenceBoundary": (
            "No result from this tool is automatically confirmed. "
            "Review capture provenance and operating conditions before registry promotion."
        ),
        "mapping": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path, nargs="+", help="per-session correlation JSON reports")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    results = [json.loads(path.read_text(encoding="utf-8")) for path in args.reports]
    output = aggregate(results)
    text = json.dumps(output, indent=2) + "\n"
    if args.json_out:
        args.json_out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
