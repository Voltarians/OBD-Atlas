import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tool" / "decode_gen1_hv_capture.py"
spec = importlib.util.spec_from_file_location("decode_gen1_hv_capture", TOOL)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)


def frame(can_id: int, payload: str, timestamp: float = 1.0, bus: str = "can0"):
    return module.Frame(timestamp, bus, can_id, bytes.fromhex(payload))


class Gen1HvCaptureDecoderTests(unittest.TestCase):
    def test_cell_block_decodes_real_saved_payload(self):
        decoded = module.decode_cell_block(frame(0x200, "177AF73EBBC01800"))
        self.assertEqual(decoded["block"], 1)
        self.assertEqual(decoded["bank"], 0)
        self.assertEqual(decoded["measurementSlots"], [1, 2, 3])
        self.assertEqual(decoded["volts"], [3.75625, 3.71875, 3.755])

    def test_cell_bank_selector_cycles_into_later_measurement_slots(self):
        decoded = module.decode_cell_block(frame(0x200, "17BCF7A6BD00F800"))
        self.assertEqual(decoded["bank"], 7)
        self.assertEqual(decoded["measurementSlots"], [22, 23, 24])
        self.assertTrue(all(3.0 < value < 4.2 for value in decoded["volts"]))

    def test_four_cell_blocks_span_96_measurement_slots(self):
        payloads = {
            0x200: "1734F70CB9A01800",
            0x202: "172EF73AB9801800",
            0x204: "1734F734B9901800",
            0x206: "1732F734B9C01800",
        }
        slots = []
        for can_id, payload in payloads.items():
            decoded = module.decode_cell_block(frame(can_id, payload))
            slots.extend(decoded["measurementSlots"])
            self.assertTrue(all(3.0 < value < 4.2 for value in decoded["volts"]))
        self.assertEqual(slots, [1, 2, 3, 25, 26, 27, 49, 50, 51, 73, 74, 75])
        # Structural capacity of the protocol: four blocks x eight banks x three readings.
        self.assertEqual(4 * 8 * 3, 96)

    def test_battery_temperature_mux_zero_has_six_values(self):
        decoded = module.decode_battery_temp(frame(0x302, "038BA18B898C8A1E"))
        self.assertEqual(decoded["mux"], 0)
        self.assertEqual(decoded["labels"], list("ABCDEF"))
        self.assertEqual(decoded["temperaturesC"], [29.5, 40.5, 29.5, 28.5, 30.0, 29.0])

    def test_battery_temperature_mux_one_has_three_values(self):
        decoded = module.decode_battery_temp(frame(0x302, "1F8C8B9300000030"))
        self.assertEqual(decoded["mux"], 1)
        self.assertEqual(decoded["labels"], list("GHI"))
        self.assertEqual(decoded["temperaturesC"], [30.0, 29.5, 33.5])

    def test_coolant_payloads_decode_to_plausible_temperatures(self):
        first = module.decode_coolant(frame(0x460, "0A3C0A3C"))
        second = module.decode_coolant(frame(0x460, "0A400A3C"))
        third = module.decode_coolant(frame(0x460, "0A3C0A34"))
        self.assertEqual((first["inletC"], first["outletC"]), (31.5, 31.5))
        self.assertEqual((second["inletC"], second["outletC"]), (32.0, 31.5))
        self.assertEqual((third["inletC"], third["outletC"]), (31.5, 30.5))

    def test_charger_stats_show_realistic_12v_output_when_hv_is_zero(self):
        decoded = module.decode_charger_stats(frame(0x212, "000000011200"))
        self.assertEqual(decoded["hvCurrentA"], 0.0)
        self.assertEqual(decoded["hvVoltageV"], 0.0)
        self.assertEqual(decoded["lvCurrentA"], 0.0)
        self.assertEqual(decoded["lvVoltageV"], 13.7)

    def test_charger_parameters_preserve_disabled_mode_validity_boundary(self):
        decoded = module.decode_charger_parameters(frame(0x304, "00007C00"))
        self.assertEqual(decoded["requestedCurrentA"], 0.0)
        self.assertEqual(decoded["requestedVoltageV"], 15872.0)
        self.assertIn("only when 0x30E enables", decoded["validityNote"])

    def test_ambiguous_charger_frames_remain_raw(self):
        status = module.decode_frame(frame(0x308, "0000000000"))
        ac_stats = module.decode_frame(frame(0x30A, "00000B00000000"))
        self.assertEqual(status["decoded"]["type"], "ambiguousRaw")
        self.assertEqual(ac_stats["decoded"]["type"], "ambiguousRaw")


if __name__ == "__main__":
    unittest.main()
