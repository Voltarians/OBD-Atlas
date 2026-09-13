import csv
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMUNITY = ROOT / "data" / "gen1" / "community"


class Gen1CommunityDatasetTest(unittest.TestCase):
    def test_internal_bms_registry_is_complete_and_namespaced(self):
        path = COMMUNITY / "internal_bms_known_signals.csv"
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        self.assertTrue(rows)
        self.assertEqual({"internal_becm_bicm"}, {row["network"] for row in rows})
        self.assertEqual({"125"}, {row["bitrate_kbps"] for row in rows})

        cells = {
            int(row["signal_name"].split("_")[1])
            for row in rows
            if row["signal_name"].startswith("Cell_")
        }
        temperatures = {
            int(row["signal_name"].split("_")[1])
            for row in rows
            if row["signal_name"].startswith("Temp_")
        }

        self.assertEqual(set(range(1, 97)), cells)
        self.assertEqual(set(range(1, 17)), temperatures)

        internal_460 = {
            (row["network"], int(row["bitrate_kbps"]), row["can_id_hex"])
            for row in rows
            if row["can_id_hex"] == "0x460"
        }
        self.assertEqual({("internal_becm_bicm", 125, "0x460")}, internal_460)

    def test_same_can_id_on_different_networks_remains_distinct(self):
        evidence_path = (
            ROOT
            / "assets"
            / "evidence"
            / "chevrolet_volt_gen1_hv_passive_observations.json"
        )
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

        hv_namespace = (
            "hv_energy_management",
            evidence["network"]["bitrate"] // 1000,
            "0x460",
        )
        internal_namespace = ("internal_becm_bicm", 125, "0x460")

        coolant = next(
            observation
            for observation in evidence["observations"]
            if observation.get("canId") == "0x460"
        )

        self.assertEqual("battery coolant temperature pair", coolant["label"])
        self.assertEqual(500, hv_namespace[1])
        self.assertNotEqual(internal_namespace, hv_namespace)

    def test_pack_voltage_target_reflects_confirmed_registry_status(self):
        path = COMMUNITY / "car_facing_hv_targets.csv"
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        pack_voltage = next(row for row in rows if row["target"] == "pack_voltage")
        self.assertEqual("confirmed", pack_voltage["confidence"])
        self.assertIn("0x210", pack_voltage["source_or_reason"])
        self.assertIn("available", pack_voltage["status"])


if __name__ == "__main__":
    unittest.main()
