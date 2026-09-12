import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tool" / "extract_gm_tool_session.py"

spec = importlib.util.spec_from_file_location("extract_gm_tool_session", TOOL)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)


class GmToolSessionExtractorTests(unittest.TestCase):
    def _events(self, lines):
        frames = list(module.parse_frames(lines))
        messages = list(module.reassemble_isotp(frames))
        return module.extract_diagnostic_events(messages)

    def test_read_data_by_identifier(self):
        events = self._events(
            [
                "(1.000000) can1 7E4#0322435600000000\n",
                "(1.010000) can1 7EC#05624356FFFA0000\n",
            ]
        )
        self.assertEqual(events[0]["service"], "ReadDataByIdentifier")
        self.assertEqual(events[0]["did"], "0x4356")
        self.assertEqual(events[1]["direction"], "positiveResponse")
        self.assertEqual(events[1]["data"], "FFFA")

    def test_security_access_seed_and_key(self):
        events = self._events(
            [
                "(2.000000) can1 7E0#0227010000000000\n",
                "(2.010000) can1 7E8#0667010102030400\n",
                "(2.020000) can1 7E0#0627021122334400\n",
                "(2.030000) can1 7E8#0267020000000000\n",
            ]
        )
        self.assertEqual(events[0]["securityOperation"], "requestSeed")
        self.assertEqual(events[1]["securityData"], "01020304")
        self.assertEqual(events[2]["securityOperation"], "sendKey")
        self.assertEqual(events[2]["securityData"], "11223344")

    def test_programming_sequence_summary(self):
        lines = [
            "(3.000000) can1 7E0#0210020000000000\n",
            "(3.010000) can1 7E8#0650020064177000\n",
            "(3.020000) can1 7E0#0227010000000000\n",
            "(3.030000) can1 7E8#0667010102030400\n",
            "(3.040000) can1 7E0#0634050001020300\n",
            "(3.050000) can1 7E8#04742003E4000000\n",
            "(3.060000) can1 7E0#043601AABB000000\n",
            "(3.070000) can1 7E8#0276010000000000\n",
            "(3.080000) can1 7E0#0137000000000000\n",
            "(3.090000) can1 7E8#0177000000000000\n",
        ]
        events = self._events(lines)
        summary = module.build_summary(events)
        self.assertTrue(summary["programmingTrafficObserved"])
        self.assertIn("RequestDownload", summary["programmingServicesObserved"])
        self.assertIn("TransferData", summary["programmingServicesObserved"])
        transfer = next(e for e in events if e["service"] == "TransferData" and e["direction"] == "request")
        self.assertEqual(transfer["blockSequenceCounter"], 1)
        self.assertEqual(transfer["transferData"], "AABB")

    def test_multiframe_transfer_data(self):
        # Payload is 36 80 followed by 8 data bytes = 10 bytes total.
        lines = [
            "(4.000000) can1 7E0#100A368001020304\n",
            "(4.001000) can1 7E8#3000000000000000\n",
            "(4.002000) can1 7E0#2105060708000000\n",
        ]
        events = self._events(lines)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["service"], "TransferData")
        self.assertEqual(events[0]["blockSequenceCounter"], 0x80)
        self.assertEqual(events[0]["transferData"], "0102030405060708")

    def test_negative_response_pending(self):
        events = self._events(
            ["(5.000000) can1 7E8#037F367800000000\n"]
        )
        self.assertEqual(events[0]["direction"], "negativeResponse")
        self.assertEqual(events[0]["service"], "TransferData")
        self.assertEqual(events[0]["negativeResponseName"], "responsePending")

    def test_unrelated_normal_can_is_ignored(self):
        events = self._events(
            ["(6.000000) can1 210#BE44000000E00000\n"]
        )
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
