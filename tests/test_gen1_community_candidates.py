import csv
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "data" / "gen1" / "community" / "vehicle_can_community_candidates.csv"


class Gen1CommunityCandidateTests(unittest.TestCase):
    def test_ovms_candidates_remain_provenance_labelled(self):
        with CANDIDATES.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))

        ovms = {
            row["can_id_hex"]: row
            for row in rows
            if row["source"] == "Open Vehicle Monitoring System Volt/Ampera notes"
        }
        self.assertEqual(set(ovms), {"0x0BC", "0x4C1", "0x514", "0x4E1"})
        for row in ovms.values():
            self.assertEqual(row["confidence"], "community_derived")
            self.assertEqual(row["network"], "vehicle_high_speed")
            self.assertEqual(row["bitrate_kbps"], "500")

    def test_passive_vin_candidates_preserve_export_boundary(self):
        with CANDIDATES.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))

        vin_rows = [row for row in rows if row["can_id_hex"] in {"0x514", "0x4E1"}]
        self.assertEqual(len(vin_rows), 2)
        for row in vin_rows:
            self.assertIn("do not export the VIN", row["notes"])


if __name__ == "__main__":
    unittest.main()
