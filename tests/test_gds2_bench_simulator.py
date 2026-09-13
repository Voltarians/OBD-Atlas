import json
import pathlib
import sys
import tempfile
import unittest

TOOL_DIR = pathlib.Path(__file__).resolve().parents[1] / "tool"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import gds2_bench_simulator as sim


class Gds2BenchSimulatorTests(unittest.TestCase):
    def test_registry_hpcm2_is_confirmed_and_implemented(self):
        profile = sim.select_module("hpcm2")
        self.assertEqual(profile.request_id, 0x7E4)
        self.assertEqual(profile.normal_response_id, 0x7EC)
        self.assertEqual(profile.uudt_response_id, 0x5EC)
        self.assertEqual(profile.confidence, "confirmedBench")
        self.assertTrue(profile.implemented)

    def test_registry_observed_259_fails_closed(self):
        profile = sim.select_module("observed-0x259", require_implemented=False)
        self.assertEqual(profile.request_id, 0x259)
        self.assertFalse(profile.implemented)
        self.assertIsNone(profile.normal_response_id)
        with self.assertRaises(ValueError):
            sim.select_module("observed-0x259")

    def test_single_frame_round_trip(self):
        self.assertEqual(sim.parse_single_frame(bytes.fromhex("013E000000000000")), bytes.fromhex("3E"))
        self.assertEqual(sim.parse_single_frame(bytes.fromhex("023E00")), bytes.fromhex("3E00"))
        self.assertEqual(sim.encode_single_frame(bytes.fromhex("7E00")), bytes.fromhex("027E00"))

    def test_legacy_one_byte_tester_present_positive_response(self):
        decision = sim.decide_response(bytes.fromhex("3E"))
        self.assertEqual(decision.classification, "testerPresentLegacy")
        self.assertEqual(decision.response, bytes.fromhex("7E"))

    def test_tester_present_positive_response(self):
        decision = sim.decide_response(bytes.fromhex("3E00"))
        self.assertEqual(decision.classification, "testerPresent")
        self.assertEqual(decision.response, bytes.fromhex("7E00"))

    def test_suppressed_tester_present_has_no_response(self):
        decision = sim.decide_response(bytes.fromhex("3E80"))
        self.assertEqual(decision.classification, "testerPresentSuppressed")
        self.assertIsNone(decision.response)

    def test_gmlan_dtc_completion_uses_raw_uudt(self):
        decision = sim.decide_response(bytes.fromhex("A9811A"))
        self.assertEqual(decision.classification, "gmlanNoDtcs")
        self.assertEqual(decision.response, bytes.fromhex("81000000FF"))
        self.assertEqual(decision.transport, "raw")
        self.assertEqual(decision.response_channel, "uudt")

    def test_legacy_identification_fixtures(self):
        expected = {
            "1ACC": "5ACC05E69EC4",
            "1ACB": "5ACB05E69EC3",
            "1AC2": "5AC205E69EC2",
            "1AC1": "5AC105E69EC1",
        }
        for request, response in expected.items():
            with self.subTest(request=request):
                decision = sim.decide_response(bytes.fromhex(request))
                self.assertEqual(decision.classification, "readLegacyDid")
                self.assertEqual(decision.response, bytes.fromhex(response))

    def test_legacy_vin_and_traceability_are_multiframe_capable(self):
        vin = sim.decide_response(bytes.fromhex("1A90")).response
        traceability = sim.decide_response(bytes.fromhex("1AB4")).response
        self.assertEqual(vin, bytes.fromhex("5A90") + sim.DEFAULT_VIN.encode("ascii"))
        self.assertEqual(traceability, bytes.fromhex("5AB4") + b"OBDATLASBENCH001")
        self.assertGreater(len(sim.segment_isotp(vin)), 1)
        self.assertGreater(len(sim.segment_isotp(traceability)), 1)

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
        self.assertEqual(decision.response, bytes.fromhex("62F190") + sim.DEFAULT_VIN.encode("ascii"))
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
        self.assertEqual(sim.decide_response(bytes.fromhex("1901FF")).response, bytes.fromhex("5901FF010000"))
        self.assertEqual(sim.decide_response(bytes.fromhex("1902FF")).response, bytes.fromhex("5902FF"))

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
        self.assertEqual(args.module, "hpcm2")
        self.assertFalse(args.confirm_isolated_bench)

    def test_registry_rejects_empty_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "registry.json"
            path.write_text(json.dumps({"modules": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                sim.load_module_registry(path)


if __name__ == "__main__":
    unittest.main()
