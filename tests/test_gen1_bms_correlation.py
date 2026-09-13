from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tool"
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

import aggregate_gen1_bms_mapping_sessions as aggregate
import capture_gen1_bms_dual_socketcan as capture
import correlate_gen1_bms_networks as correlate
import decode_gen1_internal_bms as internal
import generate_gen1_bms_correlation_fixture as fixture


class Gen1BmsCorrelationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = internal.load_registry()

    def test_internal_registry_decodes_all_cells_and_temperatures(self) -> None:
        definitions = [item for items in self.registry.values() for item in items]
        cells = {item.signal_name for item in definitions if item.signal_name.startswith("Cell_")}
        temperatures = {item.signal_name for item in definitions if item.signal_name.startswith("Temp_")}
        self.assertEqual(cells, {f"Cell_{index:02d}" for index in range(1, 97)})
        self.assertEqual(temperatures, {f"Temp_{index:02d}" for index in range(1, 17)})
        self.assertTrue(all(item.network == "internal_becm_bicm" for item in definitions))
        self.assertTrue(all(item.bitrate_kbps == 125 for item in definitions))

    def test_synthetic_fixture_recovers_scrambled_96_cell_mapping(self) -> None:
        internal_lines = fixture.generate_internal_lines(self.registry, cycles=12)
        hv_lines = fixture.generate_hv_lines(cycles=12)
        cells = correlate.decode_internal_cells(internal_lines, self.registry)
        slots = correlate.decode_hv_slots(hv_lines)
        result = correlate.rank_mapping(cells, slots, max_delta_s=0.20, min_pairs=8)

        self.assertEqual(result["cellCount"], 96)
        self.assertEqual(result["slotCount"], 96)
        self.assertEqual(result["assignedCount"], 96)
        self.assertEqual(result["mappingStatus"], "candidateOnly")

        by_cell = {row["cell"]: row for row in result["mapping"]}
        for cell_number in range(1, 97):
            cell = f"Cell_{cell_number:02d}"
            expected_slot = f"HVslot_{fixture.cell_to_slot(cell_number):02d}"
            self.assertEqual(by_cell[cell]["slot"], expected_slot)
            self.assertEqual(by_cell[cell]["confidence"], "strongCandidate")
            self.assertNotEqual(by_cell[cell]["confidence"], "confirmed")

    def test_three_identical_sessions_become_repeatable_candidate_not_confirmed(self) -> None:
        internal_lines = fixture.generate_internal_lines(self.registry, cycles=10)
        hv_lines = fixture.generate_hv_lines(cycles=10)
        result = correlate.rank_mapping(
            correlate.decode_internal_cells(internal_lines, self.registry),
            correlate.decode_hv_slots(hv_lines),
            max_delta_s=0.20,
            min_pairs=8,
        )
        combined = aggregate.aggregate([result, result, result])
        self.assertEqual(combined["mappingStatus"], "candidateOnly")
        self.assertEqual(len(combined["mapping"]), 96)
        self.assertTrue(all(row["status"] == "repeatableCrossSessionCandidate" for row in combined["mapping"]))
        self.assertFalse(any(row["status"] == "confirmed" for row in combined["mapping"]))

    def test_session_disagreement_is_rejected(self) -> None:
        good = {"mapping": [{"cell": "Cell_01", "slot": "HVslot_01", "score": 0.99,
                             "rmseV": 0.001, "confidence": "strongCandidate"}]}
        changed = {"mapping": [{"cell": "Cell_01", "slot": "HVslot_02", "score": 0.99,
                                "rmseV": 0.001, "confidence": "strongCandidate"}]}
        combined = aggregate.aggregate([good, good, changed])
        self.assertEqual(combined["mapping"][0]["status"], "inconsistentAcrossSessions")
        self.assertIsNone(combined["mapping"][0]["slot"])

    def test_dual_capture_frame_formatter_is_candump_compatible(self) -> None:
        payload = bytes.fromhex("0102030405060708")
        line = capture.format_candump(12.5, "can125", 0x460, payload)
        self.assertEqual(line, "(12.500000) can125 460#0102030405060708\n")
        raw = capture.CAN_FRAME.pack(0x460, 8, payload)
        can_id, decoded = capture.decode_socketcan_frame(raw)
        self.assertEqual(can_id, 0x460)
        self.assertEqual(decoded, payload)


if __name__ == "__main__":
    unittest.main()
