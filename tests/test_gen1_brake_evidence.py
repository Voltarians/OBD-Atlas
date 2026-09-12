import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tool" / "extract_gen1_startup_timeline.py"
spec = importlib.util.spec_from_file_location("extract_gen1_startup_timeline_brake", TOOL)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)


class Gen1BrakeEvidenceTests(unittest.TestCase):
    def test_0c9_ecm_brake_pressed_bit(self):
        self.assertEqual(module.dbc_motorola(bytes.fromhex("0000002000110800"), 40, 1), 1)
        self.assertEqual(module.dbc_motorola(bytes.fromhex("8000002A00101800"), 40, 1), 0)

    def test_1e9_vehicle_dynamic_brake_pressed_bit(self):
        self.assertEqual(module.dbc_motorola(bytes.fromhex("4FF0300E00006000"), 6, 1), 1)
        self.assertEqual(module.dbc_motorola(bytes.fromhex("0FF0300E00002000"), 6, 1), 0)

    def test_0d1_normalized_brake_field(self):
        self.assertEqual(module.dbc_motorola(bytes.fromhex("45787A87E41B00"), 39, 8), 228)
        self.assertEqual(module.dbc_motorola(bytes.fromhex("00000000000000"), 39, 8), 0)

    def test_214_and_2f9_pressure_fields_match_known_capture_sample(self):
        first = module.dbc_motorola(bytes.fromhex("000A01F60000"), 0, 9)
        mirror = module.dbc_motorola(bytes.fromhex("7A000000000500"), 47, 9)
        self.assertEqual(first, 10)
        self.assertEqual(mirror, 10)
        self.assertEqual(first, mirror)


if __name__ == "__main__":
    unittest.main()
