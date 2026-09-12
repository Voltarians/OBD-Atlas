import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tool" / "extract_gm_simulation_reference.py"
spec = importlib.util.spec_from_file_location("extract_gm_simulation_reference", TOOL)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)


class GmSimulationReferenceExtractorTests(unittest.TestCase):
    def test_parses_legacy_line_with_and_without_delay_column(self):
        frames = module.parse([
            "0 10 0x07E3 0x3E\n",
            "0 0x07E3 0x2C 0xFE 0x30\n",
        ])
        self.assertEqual(frames[0].delay_ms, 10)
        self.assertEqual(frames[0].can_id, 0x7E3)
        self.assertEqual(frames[1].delay_ms, None)
        self.assertEqual(frames[1].data, (0x2C, 0xFE, 0x30))

    def test_ecm_heading_is_normalized_even_when_prefixed_with_more(self):
        frames = module.parse([
            ";ECM Start Comm\n",
            "0 10 0x07E0 0x3E\n",
            ";More ECM read IAT and RPM\n",
            "0 10 0x07E0 0xAA 0x04 0xF2\n",
            "1 10 0x05E8 0xF2 0 0 0 0 0 0 0\n",
        ])
        self.assertEqual({frame.module for frame in frames}, {"ECM"})

    def test_builds_bcm_request_response_and_data_addresses(self):
        frames = module.parse([
            ";BCM Start Comm\n",
            "0 10 0x0244 0x3E\n",
            "1 10 0x0644 0x7E\n",
            ";BCM Read DTCs\n",
            "5 10 0x0244 0xA9 0x81 0x1A\n",
            "1 10 0x0544 0x81 0 0 0 0 0 0 0\n",
            ";BCM Clear Codes\n",
            "0 10 0x0244 0x04\n",
            "0 10 0x0644 0x44\n",
        ])
        result = module.analyze(frames)
        bcm = next(row for row in result["modules"] if row["module"] == "BCM")
        self.assertEqual(bcm["requestCanIds"], ["0x244"])
        self.assertEqual(bcm["normalResponseCanIds"], ["0x644"])
        self.assertEqual(bcm["dataCanIds"], ["0x544"])
        self.assertIn("0x3E", bcm["services"])
        self.assertIn("0xA9", bcm["services"])

    def test_ecm_tracks_functional_clear_and_dynamic_data_id(self):
        frames = module.parse([
            ";ECM Start Comm\n",
            "0 10 0x07E0 0x3E\n",
            "1 10 0x07E8 0x7E\n",
            ";ECM Read Codes\n",
            "5 10 0x07E0 0xA9 0x81 0x1A\n",
            "1 10 0x05E8 0x81 0 0 0 0 0 0 0\n",
            ";ECM Clear Codes\n",
            "0 10 0x07DF 0x04\n",
            "1 10 0x07E8 0x44\n",
        ])
        result = module.analyze(frames)
        ecm = next(row for row in result["modules"] if row["module"] == "ECM")
        self.assertEqual(ecm["requestCanIds"], ["0x7E0"])
        self.assertEqual(ecm["normalResponseCanIds"], ["0x7E8"])
        self.assertEqual(ecm["dataCanIds"], ["0x5E8"])
        self.assertEqual(ecm["functionalRequestCanIds"], ["0x7DF"])

    def test_response_pending_is_attributed_to_requested_service(self):
        frames = module.parse([
            ";ECM Read IAT and RPM\n",
            "5 10 0x07E0 0x36 0x80 0x40 0x3B\n",
            "2 10 0x07E8 0x7F 0x36 0x78\n",
            "1 600 0x07E8 0x76 0x80\n",
        ])
        result = module.analyze(frames)
        self.assertGreaterEqual(result["serviceHistogram"]["0x36 TransferData"], 3)
        self.assertEqual(result["evidenceClass"], "legacyReference")


if __name__ == "__main__":
    unittest.main()
