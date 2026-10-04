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

    def test_legacy_passive_driving_signal_decoders(self):
        speed = module.decode_legacy_vehicle_speed(bytes([0x0B, 0xAC]))
        self.assertEqual(speed["vehicle_speed_raw"], 2988)
        self.assertEqual(speed["vehicle_speed_mph"], 29.88)
        self.assertIn("vehicle_speed_updated_utc", speed)

        accelerator = module.decode_legacy_accelerator(
            bytes([0x00, 0x00, 0x00, 0x00, 0xFE])
        )
        self.assertEqual(accelerator["accelerator_raw"], 254)
        self.assertEqual(accelerator["accelerator_pct"], 100.0)

        brake = module.decode_legacy_brake(bytes([0x00, 0x1E]))
        self.assertEqual(brake["brake_raw"], 30)

        drive = module.decode_legacy_drive_position(bytes([0x02]))
        self.assertEqual(drive["drive_position_raw"], 2)
        self.assertEqual(drive["drive_position"], "DRIVE_OR_LOW")

        shift = module.decode_legacy_shift_position(
            bytes([0x00, 0x00, 0x00, 0x01])
        )
        self.assertEqual(shift["shift_position_raw"], 1)
        self.assertEqual(shift["shift_position"], "PARK")

    def test_ovms_passive_state_decoders(self):
        frame = bytes([0x80, 0x01, 0x90, 0x00, 0x7F])
        decoded = module.decode_legacy_accelerator(frame)
        self.assertTrue(decoded["vehicle_on"])
        self.assertEqual(decoded["motor_rpm"], 100)

        odo = module.decode_legacy_odometer(bytes([0x00, 0x01, 0x00, 0x00]))
        self.assertEqual(odo["odometer_raw"], 65536)
        self.assertEqual(odo["odometer_miles"], 1024.0)

        temps = module.decode_legacy_ambient_coolant(
            bytes([0x00, 0x00, 0x50, 0x00, 0x78])
        )
        self.assertEqual(temps["coolant_temperature_c"], 40.0)
        self.assertEqual(temps["ambient_temperature_c"], 20.0)

        for raw, state in (
            (1, "PARK"),
            (2, "REVERSE"),
            (3, "NEUTRAL"),
            (4, "DRIVE"),
            (5, "LOW"),
        ):
            decoded_shift = module.decode_legacy_shift_position(
                bytes([0x00, 0x00, 0x00, raw])
            )
            self.assertEqual(decoded_shift["shift_position"], state)

    def test_passive_driving_signals_are_bus_qualified(self):
        publisher = module.DirectStatePublisher(
            state_file=Path("/tmp/unused-state.json"),
            uc2_library=Path("/tmp/unused-libusbcan.so"),
        )

        publisher._handle("can3", 0x3E9, bytes([0x0B, 0xAC]))
        self.assertNotIn("vehicle_speed_mph", publisher.pending)

        publisher._handle("can1", 0x3E9, bytes([0x0B, 0xAC]))
        self.assertEqual(publisher.pending["vehicle_speed_mph"], 29.88)
        self.assertEqual(publisher.pending["vehicle_speed_source_bus"], "can1")

    def test_reused_ids_do_not_decode_on_wrong_physical_bus(self):
        publisher = module.DirectStatePublisher(
            state_file=Path("/tmp/unused-state.json"),
            uc2_library=Path("/tmp/unused-libusbcan.so"),
        )

        publisher._handle("can0", 0x210, bytes([0xB5, 0x40]))
        self.assertNotIn("hv_pack_voltage_v", publisher.pending)

        publisher._handle("can2", 0x210, bytes([0xB5, 0x40]))
        self.assertEqual(publisher.pending["hv_pack_voltage_source_bus"], "can2")
        self.assertIn("hv_pack_voltage_v", publisher.pending)

        publisher.pending.clear()
        publisher._handle("can1", 0x1D4, bytes([0x00, 0x99]))
        self.assertNotIn("apm_requested_voltage_v", publisher.pending)

        publisher._handle("can3", 0x1D4, bytes([0x00, 0x99]))
        self.assertEqual(publisher.pending["apm_command_source_bus"], "can3")
        self.assertAlmostEqual(
            publisher.pending["apm_requested_voltage_v"],
            12.047,
            places=3,
        )

    def test_source_evidence_tracks_reused_ids_by_physical_bus(self):
        publisher = module.DirectStatePublisher(
            state_file=Path("/tmp/unused-state.json"),
            uc2_library=Path("/tmp/unused-libusbcan.so"),
        )
        publisher._handle("can0", 0x210, bytes([0xB5, 0x40]))
        publisher._handle("can2", 0x210, bytes([0xB5, 0x40]))
        publisher._handle("can2", 0x210, bytes([0xB5, 0x40]))
        publisher._queue_health()

        evidence = publisher.pending["validated_id_source_evidence"]
        self.assertIn("0x210:can0=1,can2=2", evidence)

    def test_health_reports_top_ids_per_bus(self):
        publisher = module.DirectStatePublisher(
            state_file=Path("/tmp/unused-state.json"),
            uc2_library=Path("/tmp/unused-libusbcan.so"),
        )
        publisher._handle("can0", 0x100, b"")
        publisher._handle("can0", 0x101, b"")
        publisher._handle("can0", 0x100, b"")
        publisher._queue_health()

        self.assertEqual(
            publisher.pending["bus_can0_top_ids"],
            ["0x100=2", "0x101=1"],
        )
        self.assertEqual(publisher.pending["bus_can5_top_ids"], [])

    def test_health_reports_unique_id_count_per_bus(self):
        publisher = module.DirectStatePublisher(
            state_file=Path("/tmp/unused-state.json"),
            uc2_library=Path("/tmp/unused-libusbcan.so"),
        )
        publisher._handle("can0", 0x100, b"")
        publisher._handle("can0", 0x101, b"")
        publisher._handle("can0", 0x100, b"")
        publisher._queue_health()

        self.assertEqual(publisher.pending["bus_can0_unique_ids"], 2)
        self.assertEqual(publisher.pending["bus_can1_unique_ids"], 0)
        self.assertEqual(publisher.pending["bus_can5_unique_ids"], 0)

    def test_start_removes_stale_state_file(self):
        state_file = Path("/tmp/pcg1-stale-state-test.json")
        state_file.write_text(
            '{"bus_can2_last_seen_utc":"stale"}',
            encoding="utf-8",
        )
        publisher = module.DirectStatePublisher(
            state_file=state_file,
            uc2_library=Path("/tmp/unused-libusbcan.so"),
        )
        publisher._open_uc2 = lambda: None
        publisher._open_swcan = lambda: None

        publisher.start()

        self.assertFalse(state_file.exists())

    def test_partial_uc2_runtime_recovery_prefers_alternate_open_order(self):
        publisher = module.DirectStatePublisher(
            state_file=Path("/tmp/unused-state.json"),
            uc2_library=Path("/tmp/unused-libusbcan.so"),
        )
        publisher.uc2_open_order = (0, 1)
        publisher.bus_frames["can0"] = 100
        publisher.bus_frames["can1"] = 200
        publisher.bus_frames["can2"] = 0
        publisher.bus_frames["can3"] = 0

        opened = []
        publisher._close_uc2 = lambda: None
        publisher._open_uc2 = lambda orders=module.UC2_OPEN_ORDERS: opened.append(orders)

        recovered = publisher._recover_partial_uc2()

        self.assertTrue(recovered)
        self.assertEqual(publisher.uc2_runtime_recovery_count, 1)
        self.assertIn("silent=can2", publisher.uc2_runtime_recovery_reason)
        self.assertIn("silent=can3", publisher.uc2_runtime_recovery_reason)
        self.assertEqual(opened[0][0], (1, 0))
        self.assertEqual(publisher.bus_frames["can0"], 0)
        self.assertEqual(publisher.bus_frames["can1"], 0)

    def test_health_reports_warmup_timing(self):
        publisher = module.DirectStatePublisher(
            state_file=Path("/tmp/unused-state.json"),
            uc2_library=Path("/tmp/unused-libusbcan.so"),
        )
        publisher.started_monotonic = module.time.monotonic() - 5.0
        publisher._queue_health()

        self.assertTrue(publisher.pending["direct_can_warmup_active"])
        self.assertGreaterEqual(publisher.pending["direct_can_uptime_s"], 5.0)
        self.assertGreater(
            publisher.pending["direct_can_warmup_remaining_s"],
            0.0,
        )

    def test_health_uses_startup_warmup_before_declaring_missing_sources(self):
        publisher = module.DirectStatePublisher(
            state_file=Path("/tmp/unused-state.json"),
            uc2_library=Path("/tmp/unused-libusbcan.so"),
        )
        publisher.started_monotonic = module.time.monotonic()
        publisher._queue_health()

        self.assertEqual(
            publisher.pending["physical_vehicle_bus_health"],
            "starting_waiting_for_bus_traffic",
        )
        self.assertEqual(
            publisher.pending["validated_signal_bus_health"],
            "starting_waiting_for_signal_evidence",
        )

    def test_health_declares_missing_sources_after_warmup(self):
        publisher = module.DirectStatePublisher(
            state_file=Path("/tmp/unused-state.json"),
            uc2_library=Path("/tmp/unused-libusbcan.so"),
        )
        publisher.started_monotonic = (
            module.time.monotonic() - module.HEALTH_WARMUP_SECONDS - 1.0
        )
        publisher._queue_health()

        self.assertEqual(
            publisher.pending["physical_vehicle_bus_health"],
            "missing_expected_bus_traffic",
        )
        self.assertEqual(
            publisher.pending["validated_signal_bus_health"],
            "validated_source_missing",
        )

    def test_health_reports_validated_signal_source_buses(self):
        publisher = module.DirectStatePublisher(
            state_file=Path("/tmp/unused-state.json"),
            uc2_library=Path("/tmp/unused-libusbcan.so"),
        )
        publisher.bus_last_seen["can3"] = "2026-10-04T00:00:00Z"
        publisher.bus_last_seen["can2"] = "2026-10-04T00:00:00Z"
        publisher.id_source_frames[0x1D4]["can3"] = 1
        publisher.id_source_frames[0x1D6]["can3"] = 1
        publisher.id_source_frames[0x210]["can2"] = 1
        publisher.id_source_frames[0x302]["can2"] = 1
        for can_id in module.CELL_IDS:
            publisher.id_source_frames[can_id]["can2"] = 1
        publisher._queue_health()

        self.assertEqual(publisher.pending["validated_primary_bus"], "can3")
        self.assertEqual(publisher.pending["validated_hv_bus"], "can2")
        self.assertTrue(publisher.pending["validated_primary_bus_receiving"])
        self.assertTrue(publisher.pending["validated_hv_bus_receiving"])
        self.assertTrue(publisher.pending["validated_primary_signal_evidence"])
        self.assertTrue(publisher.pending["validated_hv_signal_evidence"])
        self.assertEqual(
            publisher.pending["validated_signal_bus_health"],
            "validated_sources_live",
        )

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
        self.assertEqual(module.DEFAULT_PRIMARY_INTERFACE, "can3")
        self.assertEqual(module.DEFAULT_HV_INTERFACE, "can2")
        self.assertEqual(module.UC2_RECEIVE_BURST_LIMIT, 64)
        self.assertEqual(module.UC2_RECEIVE_WAIT_MS, 100)
        self.assertEqual(module.HEALTH_WARMUP_SECONDS, 15.0)
        self.assertEqual(module.UC2_RUNTIME_RECOVERY_LIMIT, 1)
        self.assertEqual(module.FUTURE_LIN_INTERFACES, ("lin0", "lin1", "lin2"))
        self.assertEqual(
            module.PHYSICAL_BUS_ROLES["can0"],
            "high_voltage_energy_management",
        )
        self.assertEqual(
            module.PHYSICAL_BUS_ROLES["can1"],
            "high_voltage_powertrain_expansion",
        )
        self.assertEqual(module.PHYSICAL_BUS_ROLES["can2"], "chassis_expansion")
        self.assertEqual(module.PHYSICAL_BUS_ROLES["can3"], "primary_powertrain")
        self.assertEqual(module.PHYSICAL_BUS_ROLES["can4"], "body_electrical_swcan")


if __name__ == "__main__":
    unittest.main()
