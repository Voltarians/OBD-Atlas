import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tool" / "j2534_trace.py"
spec = importlib.util.spec_from_file_location("j2534_trace", TOOL)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)


class _Clock:
    def __init__(self):
        self.value = 1000

    def __call__(self):
        self.value += 100
        return self.value


PROVIDER = {
    "registryPath": r"SOFTWARE\PassThruSupport.04.04",
    "registrySubkey": "Example Device",
    "name": "Example J2534",
    "vendor": "Example Vendor",
    "functionLibrary": {
        "path": r"C:\Program Files\Example\passthru.dll",
        "exists": True,
        "sizeBytes": 123456,
        "modifiedUnixSeconds": 1700000000.0,
    },
}


class J2534TraceTests(unittest.TestCase):
    def test_writer_preserves_call_order_and_provider_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            clock = _Clock()
            with module.J2534TraceWriter(
                path,
                provider=PROVIDER,
                source_application="gds2",
                source_application_version="2026.1",
                utc_clock=lambda: "2026-09-12T10:00:00Z",
                monotonic_clock_ns=clock,
            ) as writer:
                call_id = writer.begin_call(
                    "PassThruOpen",
                    arguments={"pName": None},
                )
                writer.end_call(
                    call_id,
                    return_code=0,
                    outputs={"deviceId": 7},
                )

            records = module.read_trace(path)
            self.assertEqual([row["sequence"] for row in records], [0, 1, 2])
            self.assertEqual(records[0]["sourceApplication"], "gds2")
            self.assertEqual(
                records[0]["providerFingerprintSha256"],
                module.provider_fingerprint(PROVIDER),
            )
            self.assertEqual(records[1]["api"], "PassThruOpen")
            self.assertEqual(records[2]["returnCode"], 0)
            self.assertEqual(records[2]["durationNs"], 100)

    def test_sensitive_services_are_redacted_by_default(self):
        security = module.sanitize_message(
            {"service": 0x27, "data": bytes.fromhex("2702DEADBEEF")}
        )
        transfer = module.sanitize_message(
            {"service": 0x36, "data": bytes.fromhex("3601AABBCC")}
        )
        for row in (security, transfer):
            self.assertTrue(row["payloadRedacted"])
            self.assertNotIn("payloadHex", row)
            self.assertEqual(len(row["payloadSha256"]), 64)
            self.assertGreater(row["dataLength"], 0)

    def test_non_sensitive_message_keeps_payload(self):
        row = module.sanitize_message(
            {"service": 0x22, "data": bytes.fromhex("224356")}
        )
        self.assertFalse(row["payloadRedacted"])
        self.assertEqual(row["payloadHex"], "224356")

    def test_sensitive_payload_can_be_explicitly_included(self):
        row = module.sanitize_message(
            {"service": 0x27, "data": bytes.fromhex("27011234")},
            include_sensitive=True,
        )
        self.assertFalse(row["payloadRedacted"])
        self.assertEqual(row["payloadHex"], "27011234")

    def test_read_trace_rejects_orphan_call_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.jsonl"
            rows = [
                {
                    "schema": module.SCHEMA_ID,
                    "recordType": "session",
                    "sequence": 0,
                    "utc": "2026-09-12T10:00:00Z",
                    "monotonicNs": 1,
                },
                {
                    "schema": module.SCHEMA_ID,
                    "recordType": "callEnd",
                    "sequence": 1,
                    "utc": "2026-09-12T10:00:00Z",
                    "monotonicNs": 2,
                    "callId": "call-00000001",
                    "api": "PassThruClose",
                    "returnCode": 0,
                    "durationNs": 1,
                    "outputs": {},
                },
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            with self.assertRaisesRegex(ValueError, "orphan callEnd"):
                module.read_trace(path)

    def test_summary_counts_calls_messages_and_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            clock = _Clock()
            with module.J2534TraceWriter(
                path,
                provider=PROVIDER,
                source_application="dps",
                utc_clock=lambda: "2026-09-12T10:00:00Z",
                monotonic_clock_ns=clock,
            ) as writer:
                call_id = writer.begin_call(
                    "PassThruWriteMsgs",
                    channel_id=3,
                    messages=[
                        {"service": 0x22, "data": "224356"},
                        {"service": 0x27, "data": "2702DEADBEEF"},
                    ],
                )
                writer.end_call(call_id, return_code=0, outputs={"numMsgs": 2})
            summary = module.summarize_trace(module.read_trace(path))
            self.assertEqual(summary["callsStarted"], 1)
            self.assertEqual(summary["callsCompleted"], 1)
            self.assertEqual(summary["messages"], 2)
            self.assertEqual(summary["redactedMessages"], 1)
            self.assertEqual(summary["apiCounts"], {"PassThruWriteMsgs": 1})


if __name__ == "__main__":
    unittest.main()
