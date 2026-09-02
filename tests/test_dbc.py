import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from dbc import DbcError, assert_round_trip, parse_dbc_text, semantic_model, write_dbc


ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "atlas.py"


def sample_dbc() -> str:
    extended = 0x80000000 | 0x18FF50E5
    return f'''VERSION "Atlas test 1"

NS_ :
    CM_
    BA_DEF_

BS_:

BU_: BCM HPCM2 IPC Vector__XXX

BO_ 801 VehicleSpeed: 8 BCM
 SG_ Speed : 0|16@1+ (0.01,0) [0|655.35] "km/h" HPCM2,IPC
 SG_ Direction : 16|2@1+ (1,0) [0|3] "" IPC

BO_ {extended} ExtendedStatus: 16 HPCM2
 SG_ Mode M : 0|4@1+ (1,0) [0|15] "" BCM
 SG_ Torque m1 : 8|16@0- (0.1,-1000) [-1000|1000] "Nm" BCM

CM_ BO_ 801 "Verified speed message";
CM_ SG_ 801 Speed "Wheel-derived vehicle speed";
VAL_ 801 Direction 0 "Stopped" 1 "Forward" 2 "Reverse" ;
BA_DEF_ BO_ "VFrameFormat" ENUM "StandardCAN","ExtendedCAN","StandardCAN_FD","ExtendedCAN_FD";
BA_ "VFrameFormat" BO_ {extended} 3;
'''


class DbcParserTests(unittest.TestCase):
    def test_core_parse_and_semantic_round_trip(self):
        database = parse_dbc_text(sample_dbc())
        self.assertEqual(database.nodes, ["BCM", "HPCM2", "IPC", "Vector__XXX"])
        self.assertEqual(len(database.messages), 2)
        self.assertEqual(database.messages[0].arbitration_id, 0x321)
        self.assertFalse(database.messages[0].is_extended)
        self.assertTrue(database.messages[1].is_extended)
        self.assertEqual(database.messages[1].dlc, 16)
        self.assertEqual(database.messages[1].signals[1].multiplex, "m1")
        self.assertTrue(database.messages[1].signals[1].is_signed)
        self.assertEqual(database.messages[0].signals[1].values[2].text, "Reverse")
        rendered = write_dbc(database)
        assert_round_trip(database, rendered)
        self.assertEqual(semantic_model(database), semantic_model(parse_dbc_text(rendered)))

    def test_rejects_invalid_standard_id_and_signal(self):
        with self.assertRaises(DbcError):
            parse_dbc_text('BO_ 5000000000 Bad: 8 ECU\n')
        with self.assertRaisesRegex(DbcError, "start bit"):
            parse_dbc_text('BO_ 1 Bad: 1 ECU\n SG_ X : 8|1@1+ (1,0) [0|1] "" ECU\n')


class DbcCliTests(unittest.TestCase):
    def run_atlas(self, *arguments: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ATLAS), *(str(item) for item in arguments)],
            check=False, capture_output=True, text=True,
        )

    def test_import_list_export_and_database_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "sample.dbc"
            database = directory / "atlas.sqlite3"
            exported = directory / "exported.dbc"
            source.write_text(sample_dbc(), encoding="utf-8")

            imported = self.run_atlas(
                "dbc-import", source, "--database", database, "--name", "volt-test"
            )
            self.assertEqual(imported.returncode, 0, imported.stderr)
            self.assertIn("Messages: 2  Signals: 4", imported.stdout)

            listed = self.run_atlas("dbc-list", "--database", database)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertIn("volt-test", listed.stdout)

            result = self.run_atlas(
                "dbc-export", "volt-test", exported, "--database", database
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(exported.is_file())
            assert_round_trip(parse_dbc_text(sample_dbc()), exported.read_text(encoding="utf-8"))

            connection = sqlite3.connect(database)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM dbc_sources").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM dbc_messages").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM dbc_signals").fetchone()[0], 4)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM dbc_values").fetchone()[0], 3)
            finally:
                connection.close()

    def test_duplicate_import_requires_replace(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "sample.dbc"
            database = directory / "atlas.sqlite3"
            source.write_text(sample_dbc(), encoding="utf-8")
            first = self.run_atlas("dbc-import", source, "--database", database)
            second = self.run_atlas("dbc-import", source, "--database", database)
            replacement = self.run_atlas(
                "dbc-import", source, "--database", database, "--replace"
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 2)
            self.assertIn("--replace", second.stderr)
            self.assertEqual(replacement.returncode, 0, replacement.stderr)


if __name__ == "__main__":
    unittest.main()

