import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tool" / "pcg1_direct_state_publisher.py"

spec = importlib.util.spec_from_file_location("pcg1_direct_state_publisher", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class Pcg1DirectStatePublisherTests(unittest.TestCase):
    def test_apm_command_matches_core_decoder(self):
        decoded = module.decode_apm_command(bytes([0x00, 0x99]))
        self.assertEqual(decoded["apm_status_raw"], 0)
        self.assertEqual(decoded["apm_state"], "OFF")
        self.assertAlmostEqual(decoded["apm_requested_voltage_v"], 12.047, places=3)

    def test_apm_stats_match_core_decoder(self):
        decoded = module.decode_apm_stats(
            bytes([0xA0, 0x28, 0xB7, 0x3F, 0x40, 0x05, 0x1F])
        )
        self.assertEqual(decoded["apm_status_raw"], 0xA0)
        self.assertAlmostEqual(decoded["apm_hv_input_current_a"], -1.0, places=3)
        self.assertAlmostEqual(decoded["apm_output_voltage_v"], 14.409, places=3)
        self.assertAlmostEqual(decoded["bus12_voltage_v"], 14.409, places=3)
        self.assertEqual(decoded["bus12_voltage_source"], "apm_0x1d6_low_voltage_sensed")
        self.assertEqual(decoded["apm_temperature_1_c"], 23.0)
        self.assertEqual(decoded["apm_temperature_2_c"], 24.0)
        self.assertEqual(decoded["apm_current_a"], 5.0)
        self.assertAlmostEqual(decoded["apm_power_w"], 72.047, places=3)
        self.assertEqual(decoded["apm_counter_raw"], 0x1F)

    def test_signed_apm_output_current_is_preserved(self):
        decoded = module.decode_apm_stats(
            bytes([0x00, 0x00, 0xB7, 0x3F, 0x3F, 0xFB, 0x00])
        )
        self.assertEqual(decoded["apm_hv_input_current_a"], -7.0)
        self.assertEqual(decoded["apm_current_a"], -5.0)

    def test_default_configuration_uses_all_six_buses(self):
        self.assertEqual(
            module.DEFAULT_INTERFACES,
            ("can0", "can1", "can2", "can3", "can4", "can5"),
        )
        self.assertEqual(module.DEFAULT_PRIMARY_INTERFACE, "can1")
        self.assertEqual(module.DEFAULT_HV_INTERFACE, "can2")
        self.assertEqual(module.FUTURE_LIN_INTERFACES, ("lin0", "lin1", "lin2"))


if __name__ == "__main__":
    unittest.main()
