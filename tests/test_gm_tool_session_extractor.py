import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tool" / "extract_gm_tool_session.py"

spec = importlib.util.spec_from_file_location("extract_gm_tool_session", TOOL)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)


class GmToolSessionExtractorTests(unittest.TestCase):
    def _events(self, lines):
        frames = list(module.parse_frames(lines))
        messages = list(module.reassemble_isotp(frames))
        return module.extract_diagnostic_events(messages)

    @staticmethod
    def _reference():
        return {
            "schemaVersion": 1,
            "catalogId": "test-legacy-reference",
            "confidence": "legacyReference",
            "modules": [
                {
                    "module": "ECM",
                    "requestCanIds": ["0x7E0"],
                    "normalResponseCanIds": ["0x7E8"],
                    "dataCanIds": ["0x5E8"],
                    "functionalRequestCanIds": ["0x7DF"],
                },
                {
                    "module": "BCM",
                    "requestCanIds": ["0x244"],
                    "normalResponseCanIds": ["0x644"],
                    "dataCanIds": ["0x544"],
                },
            ],
        }

    def test_read_data_by_identifier(self):
        events = self._events(
            [
                "(1.000000) can1 7E4#0322435600000000\n",
                "(1.010000) can1 7EC#05624356FFFA0000\n",
            ]
        )
        self.assertEqual(events[0]["service"], "ReadDataByIdentifier")
        self.assertEqual(events[0]["did"], "0x4356")
        self.assertEqual(events[1]["direction"], "positiveResponse")
        self.assertEqual(events[1]["data"], "FFFA")

    def test_security_access_seed_and_key(self):
        events = self._events(
            [
                "(2.000000) can1 7E0#0227010000000000\n",
                "(2.010000) can1 7E8#0667010102030400\n",
                "(2.020000) can1 7E0#0627021122334400\n",
                "(2.030000) can1 7E8#0267020000000000\n",
            ]
        )
        self.assertEqual(events[0]["securityOperation"], "requestSeed")
        self.assertEqual(events[1]["securityData"], "01020304")
        self.assertEqual(events[2]["securityOperation"], "sendKey")
        self.assertEqual(events[2]["securityData"], "11223344")

    def test_programming_sequence_summary(self):
        lines = [
            "(3.000000) can1 7E0#0210020000000000\n",
            "(3.010000) can1 7E8#0650020064177000\n",
            "(3.020000) can1 7E0#0227010000000000\n",
            "(3.030000) can1 7E8#0667010102030400\n",
            "(3.040000) can1 7E0#0634050001020300\n",
            "(3.050000) can1 7E8#04742003E4000000\n",
            "(3.060000) can1 7E0#043601AABB000000\n",
            "(3.070000) can1 7E8#0276010000000000\n",
            "(3.080000) can1 7E0#0137000000000000\n",
            "(3.090000) can1 7E8#0177000000000000\n",
        ]
        events = self._events(lines)
        summary = module.build_summary(events)
        self.assertTrue(summary["programmingTrafficObserved"])
        self.assertIn("RequestDownload", summary["programmingServicesObserved"])
        self.assertIn("TransferData", summary["programmingServicesObserved"])
        transfer = next(
            e
            for e in events
            if e["service"] == "TransferData" and e["direction"] == "request"
        )
        self.assertEqual(transfer["blockSequenceCounter"], 1)
        self.assertEqual(transfer["transferData"], "AABB")

    def test_multiframe_transfer_data(self):
        lines = [
            "(4.000000) can1 7E0#100A368001020304\n",
            "(4.001000) can1 7E8#3000000000000000\n",
            "(4.002000) can1 7E0#2105060708000000\n",
        ]
        events = self._events(lines)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["service"], "TransferData")
        self.assertEqual(events[0]["blockSequenceCounter"], 0x80)
        self.assertEqual(events[0]["transferData"], "0102030405060708")

    def test_negative_response_pending(self):
        events = self._events(
            ["(5.000000) can1 7E8#037F367800000000\n"]
        )
        self.assertEqual(events[0]["direction"], "negativeResponse")
        self.assertEqual(events[0]["service"], "TransferData")
        self.assertEqual(events[0]["negativeResponseName"], "responsePending")

    def test_unrelated_normal_can_is_ignored(self):
        events = self._events(
            ["(6.000000) can1 210#BE44000000E00000\n"]
        )
        self.assertEqual(events, [])

    def test_reference_enrichment_and_iso_tp_latency(self):
        index = module.build_address_index(self._reference())
        lines = [
            "(7.000000) can1 7E0#0322435600000000\n",
            "(7.012000) can1 7E8#05624356FFFA0000\n",
        ]
        frames = list(module.parse_frames(lines))
        events = module.extract_diagnostic_events(module.reassemble_isotp(frames))
        module.annotate_events(events, index)
        transactions = module.build_transactions(events)

        self.assertEqual(events[0]["likelyModule"], "ECM")
        self.assertEqual(events[0]["addressEvidence"], "legacyReference")
        self.assertEqual(events[1]["addressRole"], "normalResponse")
        self.assertEqual(transactions[0]["module"], "ECM")
        self.assertEqual(transactions[0]["initialResponseLatencyMs"], 12.0)
        self.assertEqual(transactions[0]["finalResponseLatencyMs"], 12.0)

    def test_legacy_unframed_family_and_data_stream_are_observed(self):
        index = module.build_address_index(self._reference())
        lines = [
            "(8.000000) can0 244#3E\n",
            "(8.010000) can0 644#7E00000000000000\n",
            "(8.020000) can0 544#0500010203040506\n",
        ]
        frames = list(module.parse_frames(lines))
        events = module.extract_legacy_reference_events(frames, index)
        module.annotate_events(events, index)
        traffic = module.build_endpoint_traffic(frames, index)
        transactions = module.build_transactions(events)

        self.assertEqual(events[0]["transport"], "legacyUnframedReference")
        self.assertEqual(events[0]["likelyModule"], "BCM")
        self.assertEqual(events[1]["addressRole"], "normalResponse")
        stream = next(row for row in traffic if row["role"] == "dataStream")
        self.assertEqual(stream["canId"], "0x544")
        self.assertEqual(stream["module"], "BCM")
        self.assertEqual(transactions[0]["initialResponseLatencyMs"], 10.0)

    def test_response_pending_records_initial_and_final_latency(self):
        index = module.build_address_index(self._reference())
        lines = [
            "(9.000000) can1 7E0#0236010000000000\n",
            "(9.010000) can1 7E8#037F367800000000\n",
            "(9.100000) can1 7E8#0276010000000000\n",
        ]
        frames = list(module.parse_frames(lines))
        events = module.extract_diagnostic_events(module.reassemble_isotp(frames))
        module.annotate_events(events, index)
        transaction = module.build_transactions(events)[0]

        self.assertEqual(transaction["responseCount"], 2)
        self.assertEqual(
            transaction["responses"][0]["negativeResponseName"], "responsePending"
        )
        self.assertEqual(transaction["initialResponseLatencyMs"], 10.0)
        self.assertEqual(transaction["finalResponseLatencyMs"], 100.0)
        self.assertEqual(transaction["finalResponseDirection"], "positiveResponse")

    def test_iso_tp_origin_is_not_reclassified_as_legacy_service(self):
        index = module.build_address_index(self._reference())
        lines = [
            "(10.000000) can1 7E0#0422F19000000000\n",
            "(10.010000) can1 7E8#0462F19001000000\n",
        ]
        frames = list(module.parse_frames(lines))
        iso_events = module.extract_diagnostic_events(module.reassemble_isotp(frames))
        legacy_events = module.extract_legacy_reference_events(
            frames, index, iso_events
        )
        events = module.merge_events(iso_events, legacy_events)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["service"], "ReadDataByIdentifier")
        self.assertEqual(legacy_events, [])


if __name__ == "__main__":
    unittest.main()
