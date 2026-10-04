import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from tools.vehicle_ingest import IntakeError, canonical_vehicle, review, stage

class VehicleIngestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.storage = self.root / 'private'

    def bundle(self, vehicle, name='test-session', *, corrupt=False, extra=None):
        payload = b'(1780000000.000001) can0 7E4#0210010000000000\n'
        (self.source / 'capture.log').write_bytes(payload)
        manifest = {
            'schema': 'voltec-atlas.capture-session.v1',
            'session_id': name, 'capture_type': 'passive_multi_bus_can',
            'vehicle': vehicle, 'buses': [{'logged_interface': 'can0', 'atlas_bus': 'unassigned',
                                       'frames': 1, 'unique_arbitration_ids': 1, 'captured': True}],
            'capture_status': {'total_frames': 1, 'complete_shutdown': True},
            'files': [{'name': 'capture.log', 'role': 'candump_log', 'format': 'candump_-L',
                       'size_bytes': len(payload), 'sha256': '0' * 64 if corrupt else hashlib.sha256(payload).hexdigest()}]
        }
        if extra:
            manifest.update(extra)
        path = self.source / (name + '.session.json')
        path.write_text(json.dumps(manifest))
        return path

    def volt(self, year=2013, **extra):
        return {'make': 'Chevrolet', 'model': 'Volt', 'model_year': year, **extra}

    def test_generation_boundaries(self):
        self.assertEqual(canonical_vehicle(self.volt(2015)).vehicle_type, 'chevrolet-volt-gen1')
        self.assertEqual(canonical_vehicle(self.volt(2016)).vehicle_type, 'chevrolet-volt-gen2')
        self.assertEqual(canonical_vehicle({'make': 'Cadillac', 'model': 'ELR', 'model_year': 2016}).generation, 1)
        with self.assertRaises(IntakeError): canonical_vehicle(self.volt(2016, generation=1))
        with self.assertRaises(IntakeError): canonical_vehicle(self.volt(2020))

    def test_public_volt_staged_not_trusted(self):
        path = self.bundle(self.volt(identity_status='verified', identity_source='curator_verified'))
        staged = stage(path, self.storage)
        receipt = json.loads((staged / 'receipt.json').read_text())
        self.assertEqual(receipt['state'], 'awaiting_identity_review')
        self.assertFalse((self.storage / 'databases').exists())
        self.assertEqual(stage(path, self.storage), staged)

    def test_other_vehicle_rejected_from_public(self):
        path = self.bundle({'make': 'Toyota', 'model': 'Prius', 'model_year': 2015})
        with self.assertRaises(IntakeError): stage(path, self.storage)
        self.assertFalse((self.storage / 'incoming').exists())

    def test_private_research_separates_types(self):
        path = self.bundle({'make': 'Toyota', 'model': 'Prius', 'model_year': 2015})
        staged = stage(path, self.storage, 'research')
        vehicle = canonical_vehicle({'make': 'Toyota', 'model': 'Prius', 'model_year': 2015}, allow_unknown=False)
        accepted = review(staged, self.storage, vehicle, 'Verified shop registration and model plate', privacy_reviewed=True, import_database=False)
        self.assertIn('vehicles/toyota-prius/2015/', accepted.as_posix())
        self.assertEqual(json.loads((accepted / 'receipt.json').read_text())['state'], 'accepted_private')

    def test_unknown_can_be_reviewed_but_not_autorouted(self):
        staged = stage(self.bundle({}), self.storage)
        with self.assertRaises(IntakeError):
            review(staged, self.storage, canonical_vehicle(self.volt()), '', privacy_reviewed=True, import_database=False)
        with self.assertRaises(IntakeError):
            review(staged, self.storage, canonical_vehicle(self.volt()), 'VIN decode', import_database=False)
        accepted = review(staged, self.storage, canonical_vehicle(self.volt()), 'Independent VIN decode', privacy_reviewed=True, import_database=False)
        self.assertIn('chevrolet-volt-gen1/2013/', accepted.as_posix())

    def test_conflicting_identity_never_contaminates_volt(self):
        staged = stage(self.bundle(self.volt(2018)), self.storage)
        with self.assertRaises(IntakeError):
            review(staged, self.storage, canonical_vehicle(self.volt(2013)), 'Incorrect review', privacy_reviewed=True, import_database=False)
        self.assertTrue(staged.exists())

    def test_public_nonvolt_requires_explicit_reclassification(self):
        staged = stage(self.bundle({}), self.storage)
        other = canonical_vehicle({'make': 'Ford', 'model': 'Focus', 'model_year': 2017})
        with self.assertRaises(IntakeError):
            review(staged, self.storage, other, 'Registration', privacy_reviewed=True, import_database=False)
        accepted = review(staged, self.storage, other, 'Registration', privacy_reviewed=True, import_database=False, reclassify_research=True)
        self.assertIn('vehicles/ford-focus/2017/', accepted.as_posix())
        self.assertEqual(json.loads((accepted / 'receipt.json').read_text())['scope'], 'research')

    def test_hash_and_traversal_rejected(self):
        with self.assertRaises(IntakeError): stage(self.bundle(self.volt(), corrupt=True), self.storage)
        path = self.bundle(self.volt())
        manifest = json.loads(path.read_text())
        manifest['files'][0]['name'] = '../outside.log'
        path.write_text(json.dumps(manifest))
        with self.assertRaises(IntakeError): stage(path, self.storage)
        manifest['files'][0]['name'] = 'receipt.json'
        path.write_text(json.dumps(manifest))
        with self.assertRaises(IntakeError): stage(path, self.storage)

    def test_original_vin_and_free_text_not_in_reviewed_manifest(self):
        vin = '1G1RA6E43DU100001'
        staged = stage(self.bundle({**self.volt(), 'vin': vin}, extra={'notes': vin}), self.storage)
        accepted = review(staged, self.storage, canonical_vehicle(self.volt()), 'Independent VIN decoder', privacy_reviewed=True, import_database=False)
        self.assertNotIn(vin, (accepted / 'reviewed.session.json').read_text())
        self.assertIn(vin, (accepted / 'original.session.json').read_text())

    def test_tampering_after_stage_is_rejected(self):
        staged = stage(self.bundle(self.volt()), self.storage)
        (staged / 'capture.log').write_text('modified')
        with self.assertRaises(IntakeError):
            review(staged, self.storage, canonical_vehicle(self.volt()), 'VIN decode', privacy_reviewed=True, import_database=False)

if __name__ == '__main__':
    unittest.main()
