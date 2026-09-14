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

    def test_stop_all_returns_raw_uudt_zero(self):
        decision = self.state.control(bytes.fromhex("AA00"))
        self.assertEqual(decision.classification, "dynamicStop")
        self.assertEqual(decision.response, bytes.fromhex("00"))
        self.assertEqual(decision.transport, "raw")
        self.assertEqual(decision.response_channel, "uudt")

    def test_fast_schedule_returns_one_synthetic_sample(self):
        self.state.define(bytes.fromhex("2CFE430E"))
        decision = self.state.control(bytes.fromhex("AA04FE"))
        self.assertEqual(decision.classification, "dynamicSample")
        self.assertEqual(decision.response, bytes.fromhex("FE00"))
        self.assertEqual(decision.transport, "raw")
        self.assertEqual(decision.response_channel, "uudt")
        self.assertIn("periodic scheduler not emulated", decision.detail)

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
