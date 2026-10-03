import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tool" / "pcg1_pid0142_reader.py"

spec = importlib.util.spec_from_file_location("pcg1_pid0142_reader", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class Pcg1Pid0142ReaderTests(unittest.TestCase):
    def test_parses_multiple_single_frame_responses(self):
        text = """
7EA04414230EB
7E804414230BB
7EB044142314A
7EF0441423014
7E904414230FB
7EC0441423122
7ED044142312D
>
"""
        values = module.parse_pid0142_voltages(text)
        self.assertEqual(
            values,
            [12.523, 12.475, 12.618, 12.308, 12.539, 12.578, 12.589],
        )
        median, samples = module.median_pid0142_voltage(text)
        self.assertEqual(samples, values)
        self.assertAlmostEqual(median, 12.539, places=3)

    def test_parses_iso_tp_first_frames_without_counting_continuations(self):
        text = """
7E9100C414234C90100
7EA100C414234DF0100
7E8100C414234870101
7EB100C414234DD0100
7EF07414233ED4233ED
7E9210400004234C9AA
7EC100C414235080181
7EA210400004234DFAA
7E82127E5E5423487AA
7ED07414234F24234F2
7EB210400004234DDAA
7EC21040000423508AA
>
"""
        values = module.parse_pid0142_voltages(text)
        self.assertEqual(
            values,
            [13.513, 13.535, 13.447, 13.533, 13.293, 13.576, 13.554],
        )
        median, _ = module.median_pid0142_voltage(text)
        self.assertAlmostEqual(median, 13.533, places=3)

    def test_rejects_non_pid0142_and_implausible_values(self):
        text = "410080000001\n41420001\n4142FFFF\n>"
        self.assertEqual(module.parse_pid0142_voltages(text), [])

    def test_merge_state_preserves_existing_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text('{"apm_state":"UNKNOWN"}\n', encoding="utf-8")
            module._merge_state(path, 13.533, [13.513, 13.535, 13.533])
            data = __import__("json").loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["apm_state"], "UNKNOWN")
            self.assertEqual(data["bus12_voltage_v"], 13.533)
            self.assertEqual(
                data["bus12_voltage_source"],
                "sae_mode01_pid_0142_median",
            )
            self.assertEqual(data["bus12_pid0142_sample_count"], 3)


if __name__ == "__main__":
    unittest.main()
