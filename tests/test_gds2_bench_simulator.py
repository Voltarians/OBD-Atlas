import pathlib
import sys
import unittest

TOOL_DIR = pathlib.Path(__file__).resolve().parents[1] / "tool"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import gds2_bench_simulator as sim


class Gds2BenchSimulatorTests(unittest.TestCase):
    def test_single_frame_round_trip(self):
        self.assertEqual(
            sim.parse_single_frame(bytes.fromhex("023E00")),
            bytes.fromhex("3E00"),
        )
        self.assertEqual(
            sim.encode_single_frame(bytes.fromhex("7E00")),
            bytes.fromhex("027E00"),
        )

    def test_tester_present_positive_response(self):
        decision = sim.decide_response(bytes.fromhex("3E00"))
        self.assertEqual(decision.classification, "testerPresent")
        self.assertEqual(decision.response, bytes.fromhex("7E00"))

    def test_suppressed_tester_present_has_no_response(self):
        decision = sim.decide_response(bytes.fromhex("3E80"))
        self.assertEqual(decision.classification, "testerPresentSuppressed")
        self.assertIsNone(decision.response)

    def test_default_session_control(self):
        decision = sim.decide_response(bytes.fromhex("1001"))
        self.assertEqual(decision.classification, "sessionControl")
        self.assertEqual(decision.response, bytes.fromhex("5001003201F4"))

    def test_known_hpcm2_did_returns_fixture(self):
        decision = sim.decide_response(bytes.fromhex("22432D"))
        self.assertEqual(decision.classification, "readDid")
        self.assertEqual(decision.response, bytes.fromhex("62432D02DC"))

    def test_vin_did_returns_17_character_identity(self):
        decision = sim.decide_response(bytes.fromhex("22F190"))
        self.assertEqual(decision.classification, "readDid")
        self.assertEqual(
            decision.response,
            bytes.fromhex("62F190") + sim.DEFAULT_VIN.encode("ascii"),
        )
        frames = sim.segment_isotp(decision.response)
        self.assertGreater(len(frames), 1)
        self.assertEqual(frames[0][0] >> 4, 1)
        self.assertTrue(all(len(frame) <= 8 for frame in frames))

    def test_unknown_did_fails_closed(self):
        decision = sim.decide_response(bytes.fromhex("221234"))
        self.assertEqual(decision.classification, "unknownDid")
        self.assertEqual(decision.response, bytes.fromhex("7F2231"))

    def test_programming_and_security_services_are_blocked(self):
        for service in (0x27, 0x2E, 0x31, 0x34, 0x35, 0x36, 0x37, 0x3D):
            with self.subTest(service=service):
                decision = sim.decide_response(bytes((service, 0x01)))
                self.assertEqual(decision.classification, "blocked")
                self.assertEqual(decision.response[:2], bytes((0x7F, service)))

    def test_clear_and_control_services_are_blocked(self):
        for service in (0x14, 0x28, 0x85):
            with self.subTest(service=service):
                decision = sim.decide_response(bytes((service, 0x01)))
                self.assertEqual(decision.classification, "blocked")
                self.assertEqual(decision.response, bytes((0x7F, service, 0x11)))

    def test_read_dtc_information_reports_no_dtcs(self):
        self.assertEqual(
            sim.decide_response(bytes.fromhex("1901FF")).response,
            bytes.fromhex("5901FF010000"),
        )
        self.assertEqual(
            sim.decide_response(bytes.fromhex("1902FF")).response,
            bytes.fromhex("5902FF"),
        )

    def test_flow_control_stmin_conversions(self):
        self.assertEqual(sim.parse_stmin(0), 0.0)
        self.assertEqual(sim.parse_stmin(10), 0.010)
        self.assertAlmostEqual(sim.parse_stmin(0xF1), 0.0001)
        self.assertEqual(sim.parse_stmin(0x80), 0.0)

    def test_defaults_match_current_pcg1_bench(self):
        args = sim.build_parser().parse_args([])
        self.assertEqual(args.device, 0)
        self.assertEqual(args.channel, 1)
        self.assertEqual(args.bitrate, 500000)
        self.assertEqual(args.vin, sim.DEFAULT_VIN)
        self.assertFalse(args.confirm_isolated_bench)


if __name__ == "__main__":
    unittest.main()
