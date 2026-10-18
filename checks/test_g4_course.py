"""Safety boundaries for fresh deployment, SSH transfer and backup recovery.

Archive tests replace the encryption executable to test parsing/refusal only.
Actual age and PostgreSQL restore belong to the isolated runtime rehearsal.
"""
import io
from contextlib import nullcontext
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.g4_course import (BACKUP_NAME, Course, backup_inventory, decrypt_backup, digest,
                               private_file, prune_backups)
from scripts.g4_prepare import prepare
from scripts.g4_remote import Remote


class CourseSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bundle = self.root / '.g4'
        self.inputs = dict(host='course.adc.test', source_commit='a' * 40,
                          app_image='sha256:' + 'b' * 64,
                          db_image='postgres:17@sha256:' + 'c' * 64,
                          nginx_image='nginx:stable-alpine@sha256:' + 'd' * 64,
                          access_mode='course-writable', http_port=18030, https_port=18443)
        self.plan = prepare(self.bundle, **self.inputs)

    def course(self):
        with patch('scripts.g4_course.docker_command', return_value=['docker', '--context', 'unit']):
            return Course(self.bundle, context='unit', rehearsal=True)

    def test_cloud_refuses_loopback_and_mismatched_architecture(self):
        with self.assertRaises(ValueError):
            Course(self.bundle, context='unit')
        with self.assertRaises(ValueError):
            Course(self.bundle, context='unit', architecture='arm64')

    def test_rehearsal_refuses_public_ports(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder) / '.g4'
            prepare(bundle, **(self.inputs | dict(bind_ip='0.0.0.0', http_port=80, https_port=443)))
            with self.assertRaises(ValueError):
                Course(bundle, context='unit', rehearsal=True)

    def test_deploy_existing_tables_never_runs_schema_or_seed(self):
        course = self.course()
        course.start_database = Mock()
        course.tables = Mock(return_value=1)
        course.dc = Mock()
        with self.assertRaises(ValueError):
            course.deploy()
        course.dc.assert_not_called()

    def test_repeated_deploy_uses_status_without_seed(self):
        path = self.bundle / 'private/deployed.json'
        path.write_text(json.dumps({'project': self.plan['project'], 'source_commit': 'a' * 40}))
        os.chmod(path, 0o600)
        course = self.course()
        course.render, course.images = Mock(), Mock()
        course.status = Mock(return_value={'status': 'ORIGIN_READY'})
        course.start_database = Mock()
        self.assertEqual(course.deploy()['status'], 'ORIGIN_READY')
        course.start_database.assert_not_called()

    def test_status_supports_ndjson_and_never_grants_cloud_pass(self):
        course = self.course()
        course.render = Mock()
        course.dc = Mock(return_value=b'{"Service":"web","State":"running","Health":"healthy"}\n'
                                     b'{"Service":"db","State":"running","Health":"healthy"}\n')
        with patch('scripts.g4_course.OriginHTTPS', side_effect=OSError):
            result = course.status()
        self.assertEqual(result['status'], 'DEGRADED')
        self.assertFalse(result['public_acceptance_executed'])
        self.assertEqual(result['course_online_readiness'], 'NOT_RUN')

    def private(self, name, contents=b'synthetic'):
        path = self.root / name
        path.write_bytes(contents)
        os.chmod(path, 0o600)
        return path

    def test_private_files_refuse_world_readable_and_symlink(self):
        path = self.private('identity.txt')
        os.chmod(path, 0o644)
        with self.assertRaises(ValueError):
            private_file(path)
        os.chmod(path, 0o600)
        alias = self.root / 'alias'
        alias.symlink_to(path)
        with self.assertRaises(ValueError):
            private_file(alias)

    def archive(self, update=None, extra=None):
        data = b'PGDMP synthetic'
        meta = {'format': 1, 'project': 'adc_g4_111111111111', 'server_major': 17,
                'source_commit': 'a' * 40, 'images': {'app': self.inputs['app_image']},
                'files': {'database.dump': {'sha256': __import__('hashlib').sha256(data).hexdigest(),
                                            'size': len(data)}}}
        if update:
            update(meta)
        path = self.root / 'plain.tar'
        with tarfile.open(path, 'w') as archive:
            for name, payload in [('database.dump', data), ('archive.json', json.dumps(meta).encode())]:
                member = tarfile.TarInfo(name)
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
            if extra:
                archive.addfile(extra, io.BytesIO(b'x') if extra.isfile() else None)
        return path

    def decrypt(self, plain):
        encrypted, identity = self.private('cipher.age'), self.private('key')
        target = self.root / 'extracted'
        target.mkdir(mode=0o700)
        def fake_decrypt(command, *args, **kwargs):
            shutil.copyfile(plain, command[command.index('-o') + 1])
        with patch('scripts.g4_course.run', side_effect=fake_decrypt):
            return decrypt_backup(encrypted, identity, target, self.root / 'private.log')

    def test_valid_archive_checks_payload_and_keeps_private_permissions(self):
        meta = self.decrypt(self.archive())
        self.assertEqual(meta['server_major'], 17)
        self.assertEqual((self.root / 'extracted/database.dump').stat().st_mode & 0o777, 0o600)

    def test_corrupt_payload_and_non_pg17_refused(self):
        for update in (lambda m: m['files']['database.dump'].update(sha256='0' * 64),
                       lambda m: m.update(server_major=16)):
            with self.subTest(update=update):
                with self.assertRaises(ValueError):
                    self.decrypt(self.archive(update))
                shutil.rmtree(self.root / 'extracted')

    def test_boolean_manifest_versions_are_not_integer_versions(self):
        for field in ('format','server_major'):
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.decrypt(self.archive(lambda m:m.update({field:True})))
            shutil.rmtree(self.root/'extracted')

    def test_traversal_duplicate_and_symlink_archives_refused(self):
        for name, kind in (('../escape', tarfile.REGTYPE), ('database.dump', tarfile.REGTYPE),
                           ('alias', tarfile.SYMTYPE)):
            entry = tarfile.TarInfo(name)
            entry.type, entry.size = kind, 1 if kind == tarfile.REGTYPE else 0
            entry.linkname = '/etc/passwd' if kind == tarfile.SYMTYPE else ''
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.decrypt(self.archive(extra=entry))
            shutil.rmtree(self.root / 'extracted')
        self.assertFalse((self.root / 'escape').exists())

    def test_restore_existing_target_never_imports_or_starts_web(self):
        course = self.course()
        course.start_database = Mock()
        course.tables = Mock(return_value=16)
        course.dc = Mock()
        course.start_runtime = Mock()
        dump = self.private('database.dump')
        meta = {'project': 'adc_g4_111111111111', 'source_commit': 'a' * 40, 'server_major': 17,
                'images': {'app': self.inputs['app_image']},
                'files': {'database.dump': {'sha256': digest(dump), 'size': dump.stat().st_size}}}
        def decrypted(*args):
            shutil.copyfile(dump, Path(args[2]) / 'database.dump')
            return meta
        with patch('scripts.g4_course.decrypt_backup', side_effect=decrypted), self.assertRaises(ValueError):
            course.restore(self.private('backup.age'), self.private('identity'))
        course.dc.assert_not_called()
        course.start_runtime.assert_not_called()

    def test_corrupt_backup_blocks_pruning(self):
        folder = self.bundle / 'backups'
        name = 'backup-20261014T120000000001Z-' + self.plan['project'] + '.tar.age'
        path = folder / name
        path.write_bytes(b'encrypted')
        os.chmod(path, 0o600)
        record = dict(name=name, project=self.plan['project'], created_at='2026-10-14T12:00:00Z',
                      size=9, sha256='0' * 64)
        sidecar = folder / (name + '.json')
        sidecar.write_text(json.dumps(record))
        os.chmod(sidecar, 0o600)
        with self.assertRaises(ValueError):
            prune_backups(folder, self.plan['project'], 7)
        self.assertTrue(path.exists())

    def test_private_access_guides_cannot_replace_the_encrypted_backup_name(self):
        course = self.course()
        for name in ('demo-credentials.txt', 'COURSE_ACCESS.md'):
            path = self.bundle / 'private' / name
            path.write_text('synthetic private guide')
            os.chmod(path, 0o600)
        recipient = self.private('recipient', ('age1' + 'a' * 58).encode())
        def dump(*args, **kwargs):
            kwargs['output_file'].write(b'PGDMP synthetic')
        def encrypt(command, *args, **kwargs):
            shutil.copyfile(command[-1], command[command.index('-o') + 1])
        course.dc = Mock(side_effect=dump)
        course.database_identity = Mock(return_value={})
        course.observations = Mock(return_value={})
        facts = {'v': 1, 'method': 'PG17_JSONB_SHA256_V1', 'tables': {}}
        with patch('scripts.g4_course.run', side_effect=encrypt), patch(
                'scripts.g4_course.snapshot', return_value=nullcontext({'snapshot': '0001-0001-1', 'facts': facts})):
            result = course.backup(recipient)
        self.assertIsNotNone(BACKUP_NAME.fullmatch(result['name']))
        self.assertEqual(len(backup_inventory(self.bundle / 'backups', self.plan['project'])), 1)

    def test_retention_removes_only_verified_old_files_from_selected_project(self):
        folder = self.bundle / 'backups'
        for i in range(9):
            name = 'backup-2026100' + str(i+1) + 'T120000000000Z-' + self.plan['project'] + '.tar.age'
            path = folder / name
            path.write_bytes(b'encrypted')
            os.chmod(path, 0o600)
            row = dict(name=name, project=self.plan['project'], created_at=str(i), size=9, sha256=digest(path))
            sidecar = folder / (name + '.json')
            sidecar.write_text(json.dumps(row))
            os.chmod(sidecar, 0o600)
        unrelated = folder / 'operator-notes.txt'
        unrelated.write_text('keep')
        prune_backups(folder, self.plan['project'], 7)
        self.assertEqual(len(backup_inventory(folder, self.plan['project'])), 7)
        self.assertTrue(unrelated.exists())

    def test_ssh_config_refuses_loopback_target_before_connecting(self):
        config = self.private('ssh.json', json.dumps({
            'host': '127.0.0.1', 'user': 'root', 'fingerprint': 'SHA256:' + 'A' * 43}).encode())
        # Remote operations also reject the local rehearsal bundle before SSH.
        with self.assertRaises(ValueError):
            Remote(config, self.bundle)


if __name__ == '__main__':
    unittest.main()
