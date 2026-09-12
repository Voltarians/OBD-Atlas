import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tool" / "windows_j2534_inventory.py"
spec = importlib.util.spec_from_file_location("windows_j2534_inventory", TOOL)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)


class WindowsJ2534InventoryTests(unittest.TestCase):
    def test_registry_locations_cover_native_and_wow6432(self):
        locations = module.registry_locations()
        self.assertIn(r"SOFTWARE\PassThruSupport.04.04", locations)
        self.assertIn(r"SOFTWARE\WOW6432Node\PassThruSupport.04.04", locations)
        self.assertIn(r"SOFTWARE\PassThruSupport.05.00", locations)
        self.assertIn(r"SOFTWARE\WOW6432Node\PassThruSupport.05.00", locations)

    def test_normalize_provider_keeps_identity_and_capabilities(self):
        row = module.normalize_provider(
            registry_path=r"SOFTWARE\PassThruSupport.04.04",
            subkey="Example Device",
            values={
                "Name": "Example J2534",
                "Vendor": "Example Vendor",
                "FunctionLibrary": r"C:\missing\example.dll",
                "ConfigApplication": r"C:\missing\config.exe",
                "CAN": 1,
                "ISO15765": 1,
            },
        )
        self.assertEqual(row["name"], "Example J2534")
        self.assertEqual(row["vendor"], "Example Vendor")
        self.assertEqual(row["capabilities"]["CAN"], 1)
        self.assertEqual(row["capabilities"]["ISO15765"], 1)
        self.assertFalse(row["functionLibrary"]["exists"])

    def test_library_metadata_records_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "passthru.dll"
            library.write_bytes(b"abc")
            metadata = module._library_metadata(str(library))
            self.assertTrue(metadata["exists"])
            self.assertEqual(metadata["sizeBytes"], 3)

    def test_select_provider_requires_one_exact_match(self):
        providers = [
            {
                "registryPath": r"SOFTWARE\PassThruSupport.04.04",
                "registrySubkey": "VCX Nano",
                "name": "VCX Nano J2534",
                "vendor": "VXDIAG",
                "functionLibrary": {"path": r"C:\vcx\passthru.dll", "exists": True},
            },
            {
                "registryPath": r"SOFTWARE\PassThruSupport.04.04",
                "registrySubkey": "Other",
                "name": "Other J2534",
                "vendor": "Other",
                "functionLibrary": {"path": r"C:\other\passthru.dll", "exists": True},
            },
        ]
        selected = module.select_provider(providers, exact_name="VCX Nano J2534")
        self.assertEqual(selected["registrySubkey"], "VCX Nano")
        self.assertTrue(selected["selectionReadOnly"])
        self.assertEqual(len(selected["providerFingerprintSha256"]), 64)

    def test_select_provider_fails_closed_on_ambiguity_or_no_match(self):
        providers = [
            {"registrySubkey": "A", "name": "Same", "functionLibrary": {}},
            {"registrySubkey": "B", "name": "Same", "functionLibrary": {}},
        ]
        with self.assertRaisesRegex(ValueError, "matched 2 providers"):
            module.select_provider(providers, exact_name="Same")
        with self.assertRaisesRegex(ValueError, "matched 0 providers"):
            module.select_provider(providers, registry_subkey="Missing")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            module.select_provider(providers, exact_name="Same", registry_subkey="A")


if __name__ == "__main__":
    unittest.main()
