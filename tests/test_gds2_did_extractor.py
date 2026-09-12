import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tool" / "extract_gds2_dids.py"

spec = importlib.util.spec_from_file_location("extract_gds2_dids", TOOL)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)


class Gds2DidExtractorTests(unittest.TestCase):
    def test_single_frame_read_data_by_identifier(self):
        lines = [
            "(1.000000) can1 7E4#0322435600000000\n",
            "(1.012000) can1 7EC#05624356FFFA0000\n",
        ]
        frames = list(module.parse_frames(lines))
        messages = list(module.reassemble_isotp(frames))
        rows = module.extract_did_transactions(messages)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["did"], "0x4356")
        self.assertEqual(rows[0]["data"], "FFFA")
        self.assertEqual(rows[0]["latencyMs"], 12.0)

    def test_multiframe_positive_response(self):
        lines = [
            "(2.000000) can1 7E4#0322430000000000\n",
            "(2.010000) can1 7EC#100A624300010203\n",
            "(2.011000) can1 7E4#3000000000000000\n",
            "(2.015000) can1 7EC#2104050607000000\n",
        ]
        frames = list(module.parse_frames(lines))
        messages = list(module.reassemble_isotp(frames))
        rows = module.extract_did_transactions(messages)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["did"], "0x4300")
        self.assertEqual(rows[0]["data"], "01020304050607")

    def test_dynamic_single_pid_definition_and_uudt_sample(self):
        lines = [
            "(4.000000) can1 7E4#042CFE434F000000\n",
            "(4.010000) can1 7EC#026CFEAAAAAAAAAA\n",
            "(4.020000) can1 7E4#03AA04FE00000000\n",
            "(4.030000) can1 5EC#FE30000000000000\n",
            "(4.050000) can1 5EC#FE31000000000000\n",
        ]
        frames = list(module.parse_frames(lines))
        messages = list(module.reassemble_isotp(frames))
        events = module.extract_dynamic_packet_sessions(frames, messages)
        definitions = [e for e in events if e["kind"] == "dynamicDefinition"]
        samples = [e for e in events if e["kind"] == "dynamicPacketSample"]
        self.assertEqual(definitions[0]["packetId"], "0xFE")
        self.assertEqual(definitions[0]["dids"], ["0x434F"])
        self.assertEqual(samples[0]["singleDid"], "0x434F")
        self.assertEqual(samples[0]["singleDidData"], "30000000000000")

    def test_multiframe_dynamic_definition_preserves_pid_order(self):
        lines = [
            "(5.000000) can1 7E4#10082CFE43694368\n",
            "(5.001000) can1 7EC#3000000000000000\n",
            "(5.002000) can1 7E4#21801F0000000000\n",
            "(5.020000) can1 7E4#03AA04FE00000000\n",
            "(5.030000) can1 5EC#FE43706000000000\n",
        ]
        frames = list(module.parse_frames(lines))
        messages = list(module.reassemble_isotp(frames))
        events = module.extract_dynamic_packet_sessions(frames, messages)
        definitions = [e for e in events if e["kind"] == "dynamicDefinition"]
        samples = [e for e in events if e["kind"] == "dynamicPacketSample"]
        self.assertEqual(
            definitions[0]["dids"],
            ["0x4369", "0x4368", "0x801F"],
        )
        self.assertEqual(samples[0]["dids"], ["0x4369", "0x4368", "0x801F"])
        self.assertNotIn("singleDid", samples[0])

    def test_ignores_unrelated_can_and_unmatched_response(self):
        lines = [
            "(3.000000) can3 210#BE44000000E00000\n",
            "(3.010000) can1 7EC#05624356FFFA0000\n",
        ]
        rows = module.extract_did_transactions(
            module.reassemble_isotp(module.parse_frames(lines))
        )
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
