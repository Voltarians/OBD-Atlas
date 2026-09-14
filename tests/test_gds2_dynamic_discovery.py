import pathlib
import sys
import unittest

TOOL_DIR = pathlib.Path(__file__).resolve().parents[1] / "tool"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import gds2_bench_simulator as base
import gds2_dynamic_discovery as dynamic


class Gds2DynamicDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.state = dynamic.DynamicDiscoveryState()

    def test_observed_contactor_definition_is_acknowledged(self):
        decision = self.state.define(bytes.fromhex("2CFE430E"))
        self.assertEqual(decision.classification, "dynamicDefine")
        self.assertEqual(decision.response, bytes.fromhex("6CFE"))
        self.assertEqual(self.state.definitions[0xFE], (0x430E,))

    def test_stop_all_returns_raw_uudt_zero_and_clears_schedule(self):
        self.state.define(bytes.fromhex("2CFE430E"))
        self.state.control(bytes.fromhex("AA03FE"), now=1.0)
        self.assertIn(0xFE, self.state.scheduled)

        decision = self.state.control(bytes.fromhex("AA00"), now=1.1)
        self.assertEqual(decision.classification, "dynamicStop")
        self.assertEqual(decision.response, bytes.fromhex("00"))
        self.assertEqual(decision.transport, "raw")
        self.assertEqual(decision.response_channel, "uudt")
        self.assertFalse(self.state.scheduled)

    def test_stop_individual_dpid_preserves_other_schedules(self):
        self.state.define(bytes.fromhex("2CFE430E"))
        self.state.define(bytes.fromhex("2CFD432C"))
        self.state.control(bytes.fromhex("AA03FE"), now=1.0)
        self.state.control(bytes.fromhex("AA03FD"), now=1.0)

        decision = self.state.control(bytes.fromhex("AA00FE"), now=1.1)
        self.assertEqual(decision.response, bytes.fromhex("00"))
        self.assertNotIn(0xFE, self.state.scheduled)
        self.assertIn(0xFD, self.state.scheduled)

    def test_medium_schedule_returns_immediate_sample_and_then_periodic_sample(self):
        self.state.define(bytes.fromhex("2CFE430E"))
        decision = self.state.control(bytes.fromhex("AA03FE"), now=10.0)
        self.assertEqual(decision.classification, "dynamicSchedule")
        self.assertEqual(decision.response, bytes.fromhex("FE00"))
        self.assertEqual(decision.transport, "raw")
        self.assertEqual(decision.response_channel, "uudt")
        self.assertIn("300ms", decision.detail)

        self.assertEqual(self.state.poll_due(10.299), [])
        due = self.state.poll_due(10.300)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0][0], 0xFE)
        self.assertEqual(due[0][1], bytes.fromhex("FE00"))
        self.assertEqual(due[0][2], 0x03)
        self.assertAlmostEqual(due[0][3], 0.300)
        self.assertAlmostEqual(self.state.seconds_until_next(10.300), 0.300)

    def test_fast_schedule_uses_documented_example_bench_cadence(self):
        self.state.define(bytes.fromhex("2CFE430E"))
        decision = self.state.control(bytes.fromhex("AA04FE"), now=20.0)
        self.assertEqual(decision.classification, "dynamicSchedule")
        self.assertIn("25ms", decision.detail)
        self.assertEqual(self.state.poll_due(20.024), [])
        self.assertEqual(self.state.poll_due(20.025)[0][1], bytes.fromhex("FE00"))

    def test_slow_schedule_fails_closed_until_explicitly_configured(self):
        self.state.define(bytes.fromhex("2CFE430E"))
        decision = self.state.control(bytes.fromhex("AA02FE"), now=1.0)
        self.assertEqual(decision.classification, "dynamicScheduleRateUnconfigured")
        self.assertEqual(decision.response, bytes.fromhex("7FAA12"))
        self.assertNotIn(0xFE, self.state.scheduled)

    def test_redefinition_cancels_existing_schedule(self):
        self.state.define(bytes.fromhex("2CFE430E"))
        self.state.control(bytes.fromhex("AA03FE"), now=1.0)
        self.assertIn(0xFE, self.state.scheduled)
        self.state.define(bytes.fromhex("2CFE432C"))
        self.assertNotIn(0xFE, self.state.scheduled)

    def test_missed_periods_are_collapsed_not_burst_replayed(self):
        self.state.define(bytes.fromhex("2CFE430E"))
        self.state.control(bytes.fromhex("AA03FE"), now=0.0)
        due = self.state.poll_due(1.05)
        self.assertEqual(len(due), 1)
        self.assertGreater(self.state.scheduled[0xFE].next_due, 1.05)

    def test_unknown_dynamic_pid_fails_closed(self):
        decision = self.state.define(bytes.fromhex("2CFE1234"))
        self.assertEqual(decision.classification, "unknownDynamicPid")
        self.assertEqual(decision.response, bytes.fromhex("7F2C31"))
        self.assertNotIn(0xFE, self.state.definitions)

    def test_reserved_dtc_dpid_range_is_rejected(self):
        decision = self.state.define(bytes.fromhex("2C80430E"))
        self.assertEqual(decision.classification, "dynamicDefineOutOfRange")
        self.assertEqual(decision.response, bytes.fromhex("7F2C31"))

    def test_existing_security_boundary_is_unchanged(self):
        decision = dynamic.decide_response(bytes.fromhex("2701"))
        self.assertEqual(decision.classification, "blocked")
        self.assertEqual(decision.response, bytes.fromhex("7F2733"))

    def test_existing_read_did_behavior_is_unchanged(self):
        decision = dynamic.decide_response(bytes.fromhex("22432D"))
        self.assertEqual(decision.classification, "readDid")
        self.assertEqual(decision.response, bytes.fromhex("62432D02DC"))


if __name__ == "__main__":
    unittest.main()
