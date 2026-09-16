import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tool" / "analyze_gen1_decel_brake_light.py"
spec = importlib.util.spec_from_file_location("analyze_gen1_decel_brake_light", TOOL)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)


def event(timestamp: float, label: str) -> str:
    return f"# ATLAS_EVENT ({timestamp:.6f}) 2026-09-16T00:00:00Z source=operator label={label}\n"


def can(timestamp: float, bus: str, can_id: int, payload: bytes) -> str:
    return f"({timestamp:.6f}) {bus} {can_id:03X}#{payload.hex().upper()}\n"


def speed_payload(mps: float) -> bytes:
    raw = max(0, min(65535, round(mps * 3.6 * 64.0)))
    return bytes([(raw >> 8) & 0xFF, raw & 0xFF, 0, 0, 0, 0, 0, 0])


def current_210_payload(signed_raw: int) -> bytes:
    return bytes([0, 0, signed_raw & 0xFF, 0, 0, 0, 0, 0])


def brake_payload(applied: bool) -> bytes:
    return bytes([0x02 if applied else 0x00, 0, 0, 0, 0, 0, 0, 0])


def gear_payload(low: bool) -> bytes:
    return bytes([0, 0, 0, 0x05 if low else 0x04, 0, 0, 0, 0])


def accelerator_payload(raw: int) -> bytes:
    return bytes([0, 0, 0, 0, 0, 0, raw & 0xFF, 0])


def build_capture() -> str:
    lines = [
        event(1000.0, "DBL_00_BASELINE"),
        event(1001.0, "DBL_10_D_STEADY"),
        event(1002.0, "DBL_20_D_LIFT_START"),
        event(1004.0, "DBL_21_D_LIFT_END"),
        event(1005.0, "DBL_30_L_LIFT_START"),
        event(1007.0, "DBL_31_L_LIFT_END"),
        event(1008.0, "DBL_40_LIGHT_BRAKE_START"),
        event(1009.0, "DBL_41_LIGHT_BRAKE_END"),
        event(1010.0, "DBL_50_MEDIUM_BRAKE_START"),
        event(1011.0, "DBL_51_MEDIUM_BRAKE_END"),
        event(1012.0, "DBL_90_TEST_END"),
    ]

    for step in range(121):
        timestamp = 1000.0 + step * 0.1
        elapsed = timestamp - 1000.0
        brake = False
        low = False
        accel = 150
        current_raw = 0
        candidate = 0

        if elapsed < 1.0:
            speed = 0.0
            accel = 0
        elif elapsed < 2.0:
            speed = 12.0
        elif elapsed < 4.0:
            speed = 12.0 - 0.5 * (elapsed - 2.0)
            accel = 0
            current_raw = -20
            candidate = 20
        elif elapsed < 5.0:
            speed = 12.0
        elif elapsed < 7.0:
            speed = 12.0 - 2.0 * (elapsed - 5.0)
            accel = 0
            low = True
            current_raw = -100
            candidate = 80
        elif elapsed < 8.0:
            speed = 12.0
        elif elapsed < 9.0:
            speed = 12.0 - 1.5 * (elapsed - 8.0)
            brake = True
            accel = 0
            current_raw = -60
            candidate = 60
        elif elapsed < 10.0:
            speed = 12.0
        elif elapsed < 11.0:
            speed = 12.0 - 2.5 * (elapsed - 10.0)
            brake = True
            accel = 0
            current_raw = -80
            candidate = 100
        else:
            speed = max(0.0, 9.5 - 0.5 * (elapsed - 11.0))
            accel = 0

        lines.extend(
            [
                can(timestamp, "can1", 0x3E9, speed_payload(speed)),
                can(timestamp, "can1", 0x0F1, brake_payload(brake)),
                can(timestamp, "can2", 0x210, current_210_payload(current_raw)),
                can(timestamp, "can3", 0x1F5, gear_payload(low)),
                can(timestamp, "can3", 0x1C3, accelerator_payload(accel)),
                can(timestamp, "can1", 0x300, bytes([candidate, 0, 0, 0, 0, 0, 0, 0])),
            ]
        )
    return "".join(lines)


class Gen1DecelBrakeLightAnalyzerTests(unittest.TestCase):
    def test_event_parser_reads_atlas_marker(self):
        parsed = module.parse_line(event(1234.5, "DBL_30_L_LIFT_START"))
        self.assertIsInstance(parsed, module.Event)
        self.assertEqual(parsed.label, "DBL_30_L_LIFT_START")
        self.assertEqual(parsed.timestamp, 1234.5)

    def test_pack_current_210_candidate_decode(self):
        frame = module.Frame(1.0, "can2", 0x210, current_210_payload(-100))
        self.assertAlmostEqual(module.decode_pack_current_210(frame), -10.1, places=6)

    def test_derived_motion_detects_stronger_l_lift(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.log"
            path.write_text(build_capture(), encoding="utf-8")
            report = module.analyze_capture(path, speed_mode="kph64")

        summary = report["eventSummary"]
        self.assertIn("dLift", summary)
        self.assertIn("lLift", summary)
        self.assertGreater(summary["lLift"]["medianDecelerationMps2"], 1.5)
        self.assertLess(summary["dLift"]["medianDecelerationMps2"], 1.0)
        self.assertGreater(
            summary["lLift"]["medianDecelerationMps2"],
            summary["dLift"]["medianDecelerationMps2"],
        )

    def test_shadow_replay_activates_for_l_regen_but_not_factory_brake(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.log"
            path.write_text(build_capture(), encoding="utf-8")
            report = module.analyze_capture(
                path,
                speed_mode="kph64",
                regen_source="210-negative",
                regen_threshold_a=1.0,
            )

        l_rows = [row for row in report["timeline"] if row["event"] == "lLift"]
        light_brake_rows = [row for row in report["timeline"] if row["event"] == "lightBrake"]
        self.assertTrue(any(row["regenBrakeLightRequest"] is True for row in l_rows))
        self.assertTrue(
            all(
                row["regenBrakeLightRequest"] is not True
                for row in light_brake_rows
                if row["factoryBrakeApplied"] is True
            )
        )
        self.assertTrue(
            any(row["shadowReason"] == "factoryBrakeApplied" for row in light_brake_rows)
        )

    def test_candidate_ranking_surfaces_synthetic_motion_byte(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.log"
            path.write_text(build_capture(), encoding="utf-8")
            report = module.analyze_capture(path, speed_mode="kph64", top_candidates=20)

        candidates = report["candidateBytes"]
        self.assertTrue(
            any(row["canId"] == "0x300" and row["byteIndex"] == 0 for row in candidates)
        )

    def test_current_event_correlation_keeps_candidate_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.log"
            path.write_text(build_capture(), encoding="utf-8")
            report = module.analyze_capture(path, speed_mode="kph64")

        correlation = report["regenCurrentCorrelation"]["0x210"]
        self.assertEqual(correlation["status"], "candidateOnly")
        self.assertEqual(correlation["candidatePolarityDuringLLift"], "negative")
        self.assertIn("must not be treated as validated", correlation["note"])


if __name__ == "__main__":
    unittest.main()
