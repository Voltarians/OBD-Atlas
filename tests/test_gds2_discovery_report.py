import json
import pathlib
import sys
import tempfile
import unittest

TOOL_DIR = pathlib.Path(__file__).resolve().parents[1] / "tool"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import gds2_discovery_report as report


class Gds2DiscoveryReportTests(unittest.TestCase):
    def test_groups_discovery_only_requests_without_authorizing_transmit(self):
        rows = [
            {"timestamp": "2026-09-13T07:21:26+00:00", "direction": "marker", "label": "BECM live data"},
            {"timestamp": "2026-09-13T07:21:27+00:00", "direction": "rx", "canId": "0x259", "data": "013E000000000000"},
            {"timestamp": "2026-09-13T07:21:28+00:00", "direction": "rx", "canId": "0x259", "data": "0227010000000000"},
            {"timestamp": "2026-09-13T07:21:29+00:00", "direction": "rx", "canId": "0x7E4", "data": "013E000000000000"},
        ]
        result = report.build_report(rows)
        self.assertTrue(result["passiveOnly"])
        self.assertEqual(result["unknownModuleCount"], 1)
        module = result["modules"][0]
        self.assertEqual(module["requestCanId"], "0x259")
        self.assertEqual(module["services"], {"0x27": 1, "0x3E": 1})
        self.assertEqual(module["candidateNormalResponseCanId"], "0x659")
        self.assertEqual(module["candidateConfidence"], "hypothesisOnly")
        self.assertFalse(module["transmitAuthorized"])
        self.assertEqual(module["nearbyMarkers"][0]["label"], "BECM live data")

    def test_marker_is_durable_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "bench.jsonl"
            saved = report.append_marker(path, "HPCM2 identification")
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded, saved)
            self.assertEqual(loaded["direction"], "marker")

    def test_rejects_empty_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                report.append_marker(pathlib.Path(directory) / "bench.jsonl", "   ")


if __name__ == "__main__":
    unittest.main()
