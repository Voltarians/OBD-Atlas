import json
import pathlib
import sys
import tempfile
import unittest

TOOL_DIR = pathlib.Path(__file__).resolve().parents[1] / "tool"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import build_gm_tool_evidence_bundle as bundle


class GmToolEvidenceBundleSensitiveTests(unittest.TestCase):
    def test_security_access_raw_bus_payload_is_redacted_in_derived_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = pathlib.Path(directory) / "security.log"
            capture.write_text(
                "(1000.100000) can0 7E4#062702DEADBEEF00\n",
                encoding="utf-8",
            )

            result = bundle.build_bundle(capture=capture)
            security = [
                event
                for event in result["gmSession"]["events"]
                if event.get("service") == "SecurityAccess"
            ]

            self.assertEqual(len(security), 1)
            event = security[0]
            self.assertEqual(event["payload"], "<redacted>")
            self.assertTrue(event["sensitivePayloadRedacted"])
            self.assertEqual(event["payloadLength"], 6)
            self.assertEqual(len(event["payloadSha256"]), 64)

            rendered = json.dumps(result, sort_keys=True).upper()
            self.assertNotIn("DEADBEEF", rendered)
            self.assertNotIn("2702DEADBEEF", rendered)

            # The source capture remains unchanged and is tied to the bundle by hash.
            self.assertIn("DEADBEEF", capture.read_text(encoding="utf-8").upper())
            inputs = {row["role"]: row for row in result["integrity"]["inputs"]}
            self.assertEqual(inputs["atlasCandump"]["sizeBytes"], capture.stat().st_size)
            self.assertEqual(len(inputs["atlasCandump"]["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
