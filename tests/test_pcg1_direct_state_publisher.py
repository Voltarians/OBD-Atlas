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

    def test_degraded_cell_measurements_are_not_filtered_or_clipped(self):
        publisher = module.DirectStatePublisher(
            state_file=Path("/tmp/unused-state.json"),
            uc2_library=Path("/tmp/unused-libusbcan.so"),
        )
        publisher.cells = {index: 3.86 for index in range(96)}
        publisher.cells[16] = 1.3625
        publisher.cells[4] = 2.23
        publisher.cells[17] = 2.67
        publisher.cells[6] = 3.88

        summary = publisher._battery_summary()

        self.assertEqual(summary["hv_cell_measurement_slots_complete"], 96)
        self.assertEqual(summary["hv_cell_min_v"], 1.3625)
        self.assertEqual(summary["hv_cell_max_v"], 3.88)
        self.assertEqual(summary["hv_cell_delta_mv"], 2517.5)
        self.assertEqual(summary["hv_cell_slots_v"][16], 1.3625)
        self.assertEqual(summary["hv_cell_slots_v"][4], 2.23)
        self.assertEqual(summary["hv_cell_slots_v"][17], 2.67)

    def test_logical_network_classifier_uses_validated_id_families(self):
        self.assertEqual(
            module.classify_logical_network("can1", 0x1D4),
            "primary_powertrain",
        )
        self.assertEqual(
            module.classify_logical_network("can2", 0x210),
            "hv_energy_management",
        )
        self.assertEqual(
            module.classify_logical_network("can4", 0x123),
            "swcan",
        )
        self.assertIsNone(module.classify_logical_network("can0", 0x589))

    def test_default_configuration_matches_verified_pcg1_topology(self):
        self.assertEqual(
            module.UC2_LOGICAL_CHANNELS,
            (
                ("can0", 0, 0),
                ("can1", 0, 1),
                ("can2", 1, 0),
                ("can3", 1, 1),
            ),
        )
        self.assertEqual(module.SWCAN_LOGICAL_CHANNEL, "can4")
        self.assertEqual(module.RESERVED_CAN_CHANNEL, "can5")
        self.assertEqual(module.CURRENT_PHYSICAL_VEHICLE_BUSES_EXPECTED, 5)
        self.assertEqual(module.CURRENT_500K_PHYSICAL_BUSES_EXPECTED, 4)
        self.assertEqual(module.CURRENT_SWCAN_PHYSICAL_BUSES_EXPECTED, 1)
        self.assertEqual(module.KNOWN_HIDDEN_INTERNAL_BUSES, 1)
        self.assertEqual(module.TOTAL_KNOWN_VEHICLE_BUSES, 6)
        self.assertEqual(module.HIDDEN_INTERNAL_BUS_NAME, "bicm_internal_125k")
        self.assertEqual(module.CAN_CAPABLE_CHANNEL_COUNT, 6)
        self.assertEqual(module.UC2_OPEN_ORDERS, ((0, 1), (1, 0)))
        self.assertEqual(module.DEFAULT_PRIMARY_INTERFACE, "can1")
        self.assertEqual(module.DEFAULT_HV_INTERFACE, "can2")
        self.assertEqual(module.UC2_RECEIVE_BURST_LIMIT, 64)
        self.assertEqual(module.UC2_RECEIVE_WAIT_MS, 100)
        self.assertEqual(module.FUTURE_LIN_INTERFACES, ("lin0", "lin1", "lin2"))


if __name__ == "__main__":
    unittest.main()
