import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "voice_event_correlator.py"
spec = importlib.util.spec_from_file_location("voice_event_correlator", MODULE_PATH)
voice_event_correlator = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(voice_event_correlator)


class VoiceEventCorrelatorTest(unittest.TestCase):
    def test_voice_event_ranks_changed_can_byte(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "capture.log"
            metadata = root / "capture.voice.json"
            transcript = root / "capture.voice.transcript.tsv"

            lines = []
            for i in range(10):
                lines.append(f"({1000.0 + i * 0.1:.6f}) can0 100#00")
                lines.append(f"({1000.0 + i * 0.1:.6f}) can0 200#55")
            for i in range(10):
                lines.append(f"({1001.0 + i * 0.1:.6f}) can0 100#FF")
                lines.append(f"({1001.0 + i * 0.1:.6f}) can0 200#55")
            log.write_text("\n".join(lines) + "\n", encoding="utf-8")

            metadata.write_text(
                json.dumps(
                    {
                        "audio_start_epoch_seconds": 1000.0,
                        "alignment": {"input_latency_calibrated": False},
                    }
                ),
                encoding="utf-8",
            )
            transcript.write_text(
                "audio_start_seconds\taudio_end_seconds\ttext\n"
                "1.000\t1.200\tBrake now\n",
                encoding="utf-8",
            )

            frames = voice_event_correlator.load_frames(log)
            events = voice_event_correlator.load_transcript(transcript)
            results = voice_event_correlator.correlate(
                frames,
                events,
                1000.0,
                baseline_seconds=1.0,
                after_seconds=0.75,
                minimum_observations=3,
                limit=4,
            )

            self.assertEqual(len(results), 1)
            self.assertTrue(results[0]["candidates"])
            first = results[0]["candidates"][0]
            self.assertEqual(first["can_id_hex"], "0x100")
            self.assertEqual(first["byte_index"], 0)
            self.assertGreater(first["score"], 100.0)

    def test_comment_annotations_are_ignored_as_non_frames(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "capture.log"
            log.write_text(
                "# ATLAS_EVENT (1000.100000) source=voice label=hello\n"
                "(1000.200000) can0 123#01\n",
                encoding="utf-8",
            )
            frames = voice_event_correlator.load_frames(log)
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0][2], 0x123)


if __name__ == "__main__":
    unittest.main()
