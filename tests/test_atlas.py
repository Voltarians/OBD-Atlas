import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "atlas.py"


class AtlasIngestTest(unittest.TestCase):
    def test_ingest_and_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            log = directory / "sample.log"
            audio = directory / "sample.flac"
            metadata = directory / "sample.meta.txt"
            database = directory / "atlas.sqlite3"

            log.write_text(
                "(1000.000001) can0 100#01\n"
                "(1000.000002) vcan0 10204040#010203\n",
                encoding="utf-8",
            )
            audio.write_bytes(b"test-audio")
            metadata.write_text("test metadata\n", encoding="utf-8")

            def entry(path: Path, role: str, format_name: str) -> dict:
                return {
                    "name": path.name,
                    "role": role,
                    "format": format_name,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256(path.read_bytes()).hexdigest(),
                }

            manifest = {
                "schema": "voltec-atlas.capture-session.v1",
                "session_id": "test-session",
                "capture_type": "passive_multi_bus_can_with_voice",
                "vehicle": {
                    "platform": "GM Voltec",
                    "model": "Chevrolet Volt",
                    "generation": 1,
                },
                "time": {
                    "can_duration_seconds": 0.000001,
                    "audio_duration_seconds": 1.0,
                },
                "capture_status": {"total_frames": 2},
                "buses": [
                    {
                        "logged_interface": "can0",
                        "atlas_bus": "primary_swcan",
                        "frames": 1,
                        "unique_arbitration_ids": 1,
                        "captured": True,
                    },
                    {
                        "logged_interface": "vcan0",
                        "atlas_bus": "auxiliary_test",
                        "frames": 1,
                        "unique_arbitration_ids": 1,
                        "captured": True,
                    },
                ],
                "files": [
                    entry(log, "candump_log", "candump_-L"),
                    entry(audio, "synchronized_voice_annotation", "flac"),
                    entry(metadata, "capture_metadata", "text"),
                ],
            }
            manifest_path = directory / "sample.session.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ATLAS),
                    "ingest",
                    str(manifest_path),
                    "--database",
                    str(database),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            connection = sqlite3.connect(database)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM frames").fetchone()[0], 2)
                standard, extended = connection.execute(
                    "SELECT SUM(is_extended = 0), SUM(is_extended = 1) FROM frames"
                ).fetchone()
                self.assertEqual((standard, extended), (1, 1))
            finally:
                connection.close()

            summary = subprocess.run(
                [sys.executable, str(ATLAS), "summary", "--database", str(database)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(summary.returncode, 0, summary.stderr)
            self.assertIn("test-session", summary.stdout)
            self.assertIn("primary_swcan", summary.stdout)


if __name__ == "__main__":
    unittest.main()
