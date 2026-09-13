import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tool" / "extract_gen1_startup_timeline.py"
spec = importlib.util.spec_from_file_location("extract_gen1_startup_timeline", TOOL)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)


class Gen1StartupTimelineTests(unittest.TestCase):
    def test_motorola_decoder_known_2c7_values(self):
        current, voltage = module.decode_2c7(bytes.fromhex("03BFCABD8000"))
        self.assertAlmostEqual(current, -8.1, places=3)
        self.assertAlmostEqual(voltage, 379.0, places=3)

    def test_startup_timeline_and_evidence_boundary(self):
        lines = [
            "(100.000000) can4 10240040#0000000000000000\n",
            "(100.100000) can2 210#BE44000000E00000\n",
            "(100.100000) can3 212#000000000000\n",
            "(116.000000) can1 0F1#280000400000\n",
            "(116.100000) can1 0F1#280100400000\n",
            "(116.300000) can1 0F1#3E1201400000\n",
            "(118.000000) can1 1F1#830E00000800007A\n",
            "(118.400000) can1 2C7#03BFCABD8000\n",
            "(118.950000) can1 1F1#820E00000800007A\n",
        ]
        result = module.analyze(module.parse_frames(lines))
        events = {row["event"]: row for row in result["timeline"]}
        self.assertEqual(events["brakePedalMovementBegins"]["seconds"], 16.1)
        self.assertEqual(events["startRequest"]["seconds"], 18.0)
        self.assertEqual(events["hvCurrentTransient"]["hvBatteryCurrentCandidateAmps"], -8.1)
        self.assertEqual(events["systemRun"]["seconds"], 18.95)
        self.assertFalse(result["evidenceBoundary"]["directAuxiliaryHsPresentAtStart"])
        self.assertFalse(result["evidenceBoundary"]["individualContactorStateConfirmed"])


if __name__ == "__main__":
    unittest.main()
