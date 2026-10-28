"""Object adapter contracts with an in-memory SDK double, not live COS acceptance."""
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts.g4_offsite import ObjectBackups, offsite_status, validate_row


class MemoryCos:
    def __init__(self):
        self.objects = {}
        self.corrupt = False
        self.fail = False
        self.deleted = []

    def put_object(self, *, Bucket, Key, Body):
        if self.fail:
            raise RuntimeError('provider failure')
        self.objects[Key] = Body.read() if hasattr(Body, 'read') else Body

    def get_object(self, *, Bucket, Key):
        raw = self.objects[Key] + (b'broken' if self.corrupt and Key.endswith('.age') else b'')
        class Body:
            def get_raw_stream(self):
                return io.BytesIO(raw)
        return {'Body': Body()}

    def list_objects(self, *, Bucket, Prefix, Marker, MaxKeys):
        keys = sorted(k for k in self.objects if k.startswith(Prefix) and k > Marker)
        return {'Contents': [{'Key': k} for k in keys[:MaxKeys]],
                'IsTruncated': 'true' if len(keys) > MaxKeys else 'false',
                'NextMarker': keys[MaxKeys - 1] if len(keys) > MaxKeys else ''}

    def delete_object(self, *, Bucket, Key):
        self.deleted.append(Key)
        del self.objects[Key]


class OffsiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bundle = self.root / '.g4'
        (self.bundle / 'private').mkdir(parents=True)
        (self.bundle / 'backups').mkdir()
        self.project = 'adc_g4_' + '1' * 12
        self.private(self.bundle / 'plan.json', {'project': self.project})
        self.config = self.bundle / 'private/offsite.json'
        self.private(self.config, {'region': 'ap-guangzhou', 'bucket': 'course-12345678',
            'project': self.project, 'prefix': 'adc-backups', 'secret_id': 'unit-id', 'secret_key': 'unit-secret'})
        self.client = MemoryCos()
        self.store = ObjectBackups(self.config, self.client)

    def private(self, path, value):
        path.write_text(json.dumps(value))
        os.chmod(path, 0o600)

    def backup(self, offset=0, microseconds=0):
        at = datetime.now(timezone.utc) - timedelta(days=offset, microseconds=microseconds)
        name = 'backup-' + at.strftime('%Y%m%dT%H%M%S%fZ') + '-' + self.project + '.tar.age'
        raw = b'unit-encrypted-ciphertext-' + name.encode()
        path = self.bundle / 'backups' / name
        path.write_bytes(raw)
        os.chmod(path, 0o600)
        row = {'name': name, 'project': self.project, 'size': len(raw),
               'created_at': at.isoformat(), 'sha256': hashlib.sha256(raw).hexdigest(),
               'source_commit': 'a' * 40, 'app_image': 'sha256:' + 'b' * 64}
        self.private(path.with_name(name + '.json'), row)
        return row

    def test_complete_readback_precedes_publishing_accepted_inventory(self):
        row = self.backup()
        result = self.store.upload(self.bundle, row['name'])
        self.assertEqual(result['state'], 'VERIFIED')
        self.assertEqual(self.store.rows(), [row])
        self.assertEqual(offsite_status(self.bundle)['verified_recovery_point'], row['created_at'])
        self.assertEqual(offsite_status(self.bundle)['state'], 'HEALTHY')

    def test_corrupt_object_does_not_publish_inventory_or_advance_recovery_point(self):
        old = self.backup(offset=1)
        self.store.upload(self.bundle, old['name'])
        new = self.backup()
        self.client.corrupt = True
        with self.assertRaises(RuntimeError):
            self.store.upload(self.bundle, new['name'])
        self.assertNotIn(self.store.prefix + new['name'] + '.json', self.client.objects)
        status = json.loads((self.bundle / 'private/offsite-status.json').read_text())
        self.assertEqual(status['state'], 'FAILED')
        self.assertEqual(status['last_verified'], old)
        self.assertTrue((self.bundle / 'backups' / new['name']).exists())

    def test_failed_upload_keeps_prior_point_and_reports_failure(self):
        old = self.backup()
        self.store.upload(self.bundle, old['name'])
        new = self.backup(microseconds=-100)
        self.client.fail = True
        with self.assertRaises(RuntimeError):
            self.store.upload(self.bundle, new['name'])
        self.assertEqual(offsite_status(self.bundle)['state'], 'FAILED')
        self.assertEqual(offsite_status(self.bundle)['verified_recovery_point'], old['created_at'])

    def test_reuploading_old_backup_does_not_move_recovery_point_backwards(self):
        new = self.backup()
        old = self.backup(offset=1)
        self.store.upload(self.bundle, new['name'])
        self.store.upload(self.bundle, old['name'])
        self.assertEqual(offsite_status(self.bundle)['verified_recovery_point'], new['created_at'])

    def test_thirty_daily_copies_keep_newest_and_do_not_delete_other_projects(self):
        foreign = 'adc-backups/adc_g4_222222222222/unrelated.age'
        self.client.objects[foreign] = b'untouched'
        for day in range(31, -1, -1):
            row = self.backup(offset=day)
            self.store.upload(self.bundle, row['name'])
        rows = self.store.rows()
        self.assertEqual(len(rows), 30)
        self.assertIn(foreign, self.client.objects)
        self.assertTrue(all(key.startswith(self.store.prefix) for key in self.client.deleted))

    def test_multiple_same_day_backups_count_as_one_retained_daily_copy(self):
        for microseconds in (1000000, 500000, 0):
            row = self.backup(microseconds=microseconds)
            self.store.upload(self.bundle, row['name'])
        self.assertEqual(len(self.store.rows()), 1)

    def test_stale_and_missing_observation_never_report_healthy(self):
        self.assertEqual(offsite_status(self.bundle)['state'], 'UNKNOWN')
        row = self.backup(offset=2)
        self.store.upload(self.bundle, row['name'])
        self.assertEqual(offsite_status(self.bundle)['state'], 'STALE')

    def test_missing_configuration_has_no_recovery_claim(self):
        self.config.unlink()
        self.assertEqual(offsite_status(self.bundle), {'state': 'NOT_CONFIGURED', 'verified_recovery_point': None})

    def test_foreign_project_metadata_is_rejected(self):
        row = self.backup()
        row['project'] = 'adc_g4_' + '2' * 12
        with self.assertRaises(ValueError):
            validate_row(row, self.project)

    def test_foreign_sidecar_filename_cannot_select_another_object(self):
        row = self.backup()
        self.client.objects[self.store.prefix + 'backup-invalid.tar.age.json'] = json.dumps(row).encode()
        with self.assertRaises(ValueError):
            self.store.rows()
