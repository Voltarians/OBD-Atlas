import importlib.util
import sqlite3
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tool" / "import_pcg1_20261003_can_knowledge.py"

spec = importlib.util.spec_from_file_location("pcg1_can_knowledge", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class Pcg1CanKnowledgeTests(unittest.TestCase):
    def test_seed_contains_106_network_scoped_entries(self):
        rows = module.build_entries()
        module.validate_entries(rows)

        self.assertEqual(len(rows), 106)
        self.assertEqual(
            Counter(row["logged_bus"] for row in rows),
            Counter({"can0": 4, "can1": 64, "can2": 14, "can3": 24}),
        )
        self.assertFalse(any(row["logged_bus"] == "can4" for row in rows))

    def test_database_import_inserts_all_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "atlas.sqlite3"
            count = module.import_entries(database)
            self.assertEqual(count, 106)

            connection = sqlite3.connect(database)
            try:
                rows = connection.execute(
                    """
                    SELECT logged_bus, COUNT(*)
                    FROM can_knowledge
                    GROUP BY logged_bus
                    ORDER BY logged_bus
                    """
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(
                rows,
                [("can0", 4), ("can1", 64), ("can2", 14), ("can3", 24)],
            )

    def test_duplicate_import_requires_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "atlas.sqlite3"
            module.import_entries(database)
            with self.assertRaises(RuntimeError):
                module.import_entries(database)
            self.assertEqual(module.import_entries(database, replace=True), 106)


if __name__ == "__main__":
    unittest.main()
