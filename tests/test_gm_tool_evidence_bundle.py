import hashlib
import json
import pathlib
import sys
import tempfile
import unittest

TOOL_DIR = pathlib.Path(__file__).resolve().parents[1] / "tool"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import build_gm_tool_evidence_bundle as bundle


class GmToolEvidenceBundleTests(unittest.TestCase):
    def test_parses_atlas_event_marker(self):
        rows = bundle.parse_atlas_markers(
            [
                "# ATLAS_EVENT (1000.050000) 1970-01-01T00:16:40.050Z source=operator label=HPCM2 Battery Data",
                "(1000.100000) can0 7E4#0322435600000000",
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "operator")
        self.assertEqual(rows[0]["label"], "HPCM2 Battery Data")
        self.assertEqual(rows[0]["evidenceClass"], "operatorMarker")

    def test_correlates_gds2_j2534_and_raw_bus_without_promoting_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            capture = root / "capture.log"
            capture.write_text(
                "\n".join(
                    [
                        "# ATLAS_EVENT (1000.050000) 1970-01-01T00:16:40.050Z source=operator label=HPCM2 Battery Data",
                        "(1000.100000) can0 7E4#0322435600000000",
                        "(1000.200000) can0 7EC#0562435612340000",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            trace = root / "gds2.jsonl"
            records = [
                {
                    "schema": "obd-atlas.j2534-trace.v1",
                    "recordType": "session",
                    "sequence": 0,
                    "utc": "1970-01-01T00:16:40.000Z",
                    "monotonicNs": 1,
                    "sourceApplication": "gds2",
                    "sourceApplicationVersion": "test",
                    "observerMode": "transparent-forwarder",
                    "proxyMayTransmitIndependently": False,
                    "provider": {"name": "fake"},
                    "providerFingerprintSha256": "0" * 64,
                    "sensitivePayloadPolicy": "redact-security-access-and-transfer-data",
                },
                {
                    "schema": "obd-atlas.j2534-trace.v1",
                    "recordType": "callBegin",
                    "sequence": 1,
                    "utc": "1970-01-01T00:16:40.100Z",
                    "monotonicNs": 2,
                    "callId": "call-00000001",
                    "api": "PassThruWriteMsgs",
                    "threadId": 1,
                    "deviceId": 1,
                    "channelId": 1,
                    "arguments": {},
                    "messages": [
                        {
                            "service": 0x22,
                            "dataLength": 7,
                            "payloadRedacted": False,
                            "payloadHex": "000007E4224356",
                        }
                    ],
                },
                {
                    "schema": "obd-atlas.j2534-trace.v1",
                    "recordType": "callEnd",
                    "sequence": 2,
                    "utc": "1970-01-01T00:16:40.101Z",
                    "monotonicNs": 3,
                    "callId": "call-00000001",
                    "api": "PassThruWriteMsgs",
                    "returnCode": 0,
                    "durationNs": 1,
                    "outputs": {"numMsgs": 1},
                },
                {
                    "schema": "obd-atlas.j2534-trace.v1",
                    "recordType": "callBegin",
                    "sequence": 3,
                    "utc": "1970-01-01T00:16:40.150Z",
                    "monotonicNs": 4,
                    "callId": "call-00000002",
                    "api": "PassThruReadMsgs",
                    "threadId": 1,
                    "deviceId": 1,
                    "channelId": 1,
                    "arguments": {},
                },
                {
                    "schema": "obd-atlas.j2534-trace.v1",
                    "recordType": "callEnd",
                    "sequence": 4,
                    "utc": "1970-01-01T00:16:40.200Z",
                    "monotonicNs": 5,
                    "callId": "call-00000002",
                    "api": "PassThruReadMsgs",
                    "returnCode": 0,
                    "durationNs": 1,
                    "outputs": {"numMsgs": 1},
                    "messages": [
                        {
                            "service": 0x22,
                            "dataLength": 9,
                            "payloadRedacted": False,
                            "payloadHex": "000007EC6243561234",
                        }
                    ],
                },
            ]
            trace.write_text(
                "\n".join(json.dumps(row, sort_keys=True) for row in records) + "\n",
                encoding="utf-8",
            )

            result = bundle.build_bundle(capture=capture, j2534_trace=trace)

            self.assertEqual(result["schema"], "obd-atlas.gm-tool-evidence-bundle.v1")
            self.assertEqual(result["sourceApplication"], "gds2")
            self.assertEqual(result["analysisMode"], "offlineObservationOnly")
            self.assertFalse(result["safety"]["transmitsVehicleTraffic"])
            self.assertFalse(result["safety"]["signalPromotionAuthorized"])
            self.assertEqual(result["summary"]["operatorMarkers"], 1)
            self.assertEqual(result["summary"]["gds2DidTransactions"], 1)
            self.assertGreaterEqual(result["summary"]["gmDiagnosticEvents"], 2)
            self.assertEqual(result["summary"]["j2534MessageEvents"], 2)

            statuses = [row["status"] for row in result["correlations"]["j2534ToBus"]]
            self.assertEqual(statuses, ["exactPayloadAndTimeMatch", "exactPayloadAndTimeMatch"])
            self.assertTrue(result["correlations"]["markersToDiagnostics"][0]["nearbyDiagnosticEvents"])

            inputs = {row["role"]: row for row in result["integrity"]["inputs"]}
            self.assertEqual(
                inputs["atlasCandump"]["sha256"],
                hashlib.sha256(capture.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                inputs["j2534Trace"]["sha256"],
                hashlib.sha256(trace.read_bytes()).hexdigest(),
            )

    def test_voice_report_is_supporting_marker_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "voice.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": "obd-atlas.voice-event-correlation.v1",
                        "evidence_class": "voiceSupportingEvidenceOnly",
                        "input_latency_calibrated": False,
                        "events": [
                            {
                                "annotation_index": 1,
                                "text": "brake now",
                                "can_window_start_epoch_seconds": 100.0,
                                "can_window_end_epoch_seconds": 101.0,
                                "candidates": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = bundle.build_bundle(voice_correlations=[path])
            marker = result["markers"][0]
            self.assertEqual(marker["source"], "voice")
            self.assertEqual(marker["evidenceClass"], "voiceSupportingEvidenceOnly")
            self.assertFalse(marker["inputLatencyCalibrated"])
            self.assertFalse(result["safety"]["signalPromotionAuthorized"])

    def test_redacted_j2534_message_has_no_payload_candidate(self):
        message = {
            "service": 0x27,
            "dataLength": 8,
            "payloadRedacted": True,
            "payloadSha256": "a" * 64,
            "sensitiveService": "SecurityAccess",
        }
        self.assertEqual(bundle._payload_candidates(message), set())

    def test_requires_evidence_input(self):
        with self.assertRaisesRegex(ValueError, "at least one evidence input"):
            bundle.build_bundle()


if __name__ == "__main__":
    unittest.main()
