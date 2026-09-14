import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tool" / "decode_gen1_hpcm2_contactor_state.py"
spec = importlib.util.spec_from_file_location("decode_gen1_hpcm2_contactor_state", TOOL)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)


class Gen1Hpcm2ContactorStateTests(unittest.TestCase):
    def test_known_state_bits(self):
        off = module.decode_state(0x68)
        first = module.decode_state(0x6A)
        precharge = module.decode_state(0x6F)
        ready = module.decode_state(0x6B)

        self.assertEqual(off["phase"], "hvOff")
        self.assertFalse(off["mainContactorBit0"])
        self.assertFalse(off["mainContactorBit1"])
        self.assertFalse(off["prechargeBit2"])

        self.assertEqual(first["phase"], "firstMainContactorEngaged")
        self.assertFalse(first["mainContactorBit0"])
        self.assertTrue(first["mainContactorBit1"])

        self.assertEqual(precharge["phase"], "prechargeActive")
        self.assertTrue(precharge["mainContactorBit0"])
        self.assertTrue(precharge["mainContactorBit1"])
        self.assertTrue(precharge["prechargeBit2"])

        self.assertEqual(ready["phase"], "hvBusEstablished")
        self.assertFalse(ready["prechargeBit2"])

    def test_successful_startup_sequence(self):
        self.assertEqual(
            module.classify_sequence([0x68, 0x68, 0x6A, 0x6F, 0x6B, 0x6B]),
            "successfulStartup",
        )

    def test_normal_shutdown_sequence(self):
        self.assertEqual(
            module.classify_sequence([0x6B, 0x6B, 0x6A, 0x68, 0x68]),
            "normalShutdown",
        )

    def test_parse_and_marker_window(self):
        lines = [
            "# ATLAS_EVENT (100.000000) 2026-09-14T00:00:00Z source=discovery label=HPCM2 Contactor Startup. start\n",
            "(100.100000) can1 5EC#FE68000000000000\n",
            "(100.300000) can1 5EC#FE6A000000000000\n",
            "(100.500000) can1 5EC#FE6F000000000000\n",
            "(100.700000) can1 5EC#FE6B000000000000\n",
            "# ATLAS_EVENT (101.000000) 2026-09-14T00:00:01Z source=discovery label=HPCM2 Contactor Startup. end\n",
        ]
        samples, markers = module.parse(lines)
        result = module.analyze(samples, markers)
        self.assertEqual(result["classification"], "successfulStartup")
        self.assertEqual(result["sampleCount"], 4)
        self.assertAlmostEqual(result["cadenceMs"]["median"], 200.0, places=3)
        self.assertEqual(
            [row["rawHex"] for row in result["transitions"]],
            ["0x68", "0x6A", "0x6F", "0x6B"],
        )


if __name__ == "__main__":
    unittest.main()
