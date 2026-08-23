import unittest

from fastapi import HTTPException

from app.main import vehicle_partition


class VehiclePartitionTests(unittest.TestCase):
    def test_uncertain_identity_is_quarantined(self) -> None:
        metadata = {
            "vehicleIdentity": {
                "status": "detected",
                "vinHash": "hash",
                "make": "Chevrolet",
                "model": "Volt",
                "modelYear": 2013,
            },
        }
        self.assertEqual(vehicle_partition(metadata), "UNCLASSIFIED")
        self.assertEqual(metadata["vehicleIdentity"]["status"], "unclassified")

    def test_confirmed_identity_receives_partition(self) -> None:
        metadata = {
            "vehicleIdentity": {
                "status": "operatorConfirmed",
                "operatorConfirmedUtc": "2026-08-23T00:00:00Z",
                "vinHash": "hash",
                "make": "Chevrolet",
                "model": "Volt",
                "modelYear": 2013,
            },
        }
        self.assertEqual(vehicle_partition(metadata), "chevrolet/volt/2013")

    def test_raw_vin_upload_is_rejected(self) -> None:
        with self.assertRaises(HTTPException):
            vehicle_partition({"vehicleIdentity": {"vin": "1M8GDM9AXKP042788"}})


if __name__ == "__main__":
    unittest.main()
