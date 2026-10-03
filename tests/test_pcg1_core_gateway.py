import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tool" / "pcg1_core_gateway.py"

spec = importlib.util.spec_from_file_location("pcg1_core_gateway", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class Pcg1CoreGatewayTests(unittest.TestCase):
    def test_normalize_state_keeps_only_supported_fields(self):
        state = module.normalize_state({
            "bus12_voltage_v": 12.64,
            "apm_output_voltage_v": 14.42,
            "apm_current_a": 18.7,
            "apm_power_w": 270,
            "apm_state": "ACTIVE",
            "unvalidated_guess": 1234,
        })
        self.assertEqual(state["bus12_voltage_v"], 12.64)
        self.assertEqual(state["apm_output_voltage_v"], 14.42)
        self.assertEqual(state["apm_current_a"], 18.7)
        self.assertEqual(state["apm_power_w"], 270.0)
        self.assertEqual(state["apm_state"], "ACTIVE")
        self.assertNotIn("unvalidated_guess", state)

    def test_state_file_preserves_last_valid_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(
                json.dumps({"bus12_voltage_v": 12.5}),
                encoding="utf-8",
            )
            source = module.StateFile(path)
            self.assertEqual(source.read()["bus12_voltage_v"], 12.5)

            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(source.read()["bus12_voltage_v"], 12.5)

    def test_nested_apm_payload_is_supported(self):
        state = module.normalize_state({
            "data": {
                "apm": {
                    "output_voltage_v": 14.5,
                    "output_current_a": 20.0,
                    "output_power_w": 290.0,
                    "state": "RUN",
                }
            }
        })
        self.assertEqual(state["apm"]["output_voltage_v"], 14.5)
        self.assertEqual(state["apm"]["output_current_a"], 20.0)
        self.assertEqual(state["apm"]["output_power_w"], 290.0)
        self.assertEqual(state["apm"]["state"], "RUN")


if __name__ == "__main__":
    unittest.main()
