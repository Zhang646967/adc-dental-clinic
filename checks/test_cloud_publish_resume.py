"""First publication recovery with real file checks and controlled SSH replies."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.g4_course import digest, exclusive
from scripts.g4_prepare import prepare
from scripts.g4_remote import PUBLISH_INTENT, Remote, VERIFY_PUBLISH_RESUME


class PublishResumeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.bundle = self.root / '.g4'
        self.release = self.root / 'server-release'
        self.source = 'a' * 40
        self.image = 'sha256:' + '1' * 64
        plan = prepare(self.bundle, host='course.adc.test', source_commit=self.source, app_image=self.image,
                       db_image='postgres:17@sha256:' + '2' * 64,
                       nginx_image='nginx:stable-alpine@sha256:' + '3' * 64,
                       bind_ip='0.0.0.0', access_mode='course-writable', dataset='course-20')
        self.recipient = self.private(self.root / 'recipient.txt', ('age1' + 'q' * 58 + '\n').encode())
        self.artifacts = self.root / 'artifacts'
        self.artifacts.mkdir(mode=0o700)
        archives = {name: self.private(self.artifacts / name, ('synthetic ' + name).encode())
                    for name in ('source.tar', 'application.tar')}
        meta = dict(source_commit=self.source, app_image=self.image, architecture='amd64',
                    source_sha256=digest(archives['source.tar']), image_archive_sha256=digest(archives['application.tar']))
        self.private(self.artifacts / 'build.json', json.dumps(meta).encode())
        self.release.mkdir(mode=0o700)
        shutil.copytree(self.bundle, self.release / '.g4')
        for name, path in archives.items():
            shutil.copy2(path, self.release / name)
        remote = self.remote = object.__new__(Remote)
        remote.bundle, remote.plan = self.bundle, plan
        remote.folder, remote.remote_bundle = str(self.release), str(self.release / '.g4')
        remote.ssh = Mock(side_effect=self.ssh)
        remote.copy = Mock(side_effect=self.download)
        self.private(self.release / PUBLISH_INTENT, remote._publish_intent('fresh').encode())
        shutil.copy2(self.recipient, self.release / '.g4/private/backup-recipient.txt')
        for name in ('fullchain.pem', 'privkey.pem'):
            self.private(self.release / '.g4/tls' / name, b'synthetic TLS presence fixture')
        for name in ('demo-credentials.txt', 'COURSE_ACCESS.md'):
            self.private(self.release / '.g4/private' / name, b'synthetic receipt')
        self.ready = dict(status='ORIGIN_READY', project=plan['project'], source_commit=self.source)

    @staticmethod
    def private(path, value):
        path.write_bytes(value)
        path.chmod(0o600)
        return path

    def ssh(self, args, **kwargs):
        if args[:3] == ['python3', '-c', VERIFY_PUBLISH_RESUME]:
            result = subprocess.run([sys.executable, *args[1:]], capture_output=True, timeout=10)
            if result.returncode:
                raise RuntimeError('Verified transfer or TLS prerequisite rejected.')
            return result.stdout
        if args[:2] == ['sha256sum', '--']:
            return (digest(Path(args[2])) + '  fixture\n').encode()
        raise AssertionError('Unexpected SSH operation in resume.')

    def download(self, path, target, *, download):
        self.assertTrue(download)
        self.private(path, Path(target).read_bytes())

    def resume(self):
        return self.remote.resume_publish(self.artifacts, self.recipient)

    def test_lost_deploy_reply_reuses_ready_instance_and_exact_backup(self):
        local = self.private(self.bundle / 'private/demo-credentials.txt', b'synthetic receipt')
        before = local.stat()
        self.remote.operation = Mock(side_effect=[self.ready, {}, {'backups': [
            {'source_commit': self.source, 'app_image': self.image},
        ]}])
        result = self.resume()
        self.assertEqual(result['first_server_backup'], 'REUSED')
        self.assertFalse(result['public_acceptance_executed'])
        self.assertEqual([call.args[0] for call in self.remote.operation.call_args_list],
                         ['status', 'install-server-jobs', 'list-backups'])
        self.remote.copy.assert_called_once()
        self.assertEqual(self.remote.copy.call_args.args[0].name, 'COURSE_ACCESS.md')
        self.assertEqual((local.stat().st_ino, local.stat().st_mtime_ns), (before.st_ino, before.st_mtime_ns))

    def test_resume_after_tls_uses_existing_deploy_guard_and_adds_first_backup(self):
        self.remote.operation = Mock(side_effect=[
            self.ready | {'status': 'DEGRADED'}, self.ready, {},
            {'backups': [{'source_commit': 'b' * 40, 'app_image': self.image}]},
            {'status': 'SERVER_BACKUP_CREATED'},
        ])
        self.assertEqual(self.resume()['first_server_backup'], 'CREATED')
        self.assertEqual([call.args[0] for call in self.remote.operation.call_args_list],
                         ['status', 'deploy', 'install-server-jobs', 'list-backups', 'backup'])

    def test_incomplete_changed_and_restore_transfers_stop_before_runtime(self):
        self.remote.operation = Mock()
        for relative in ('application.tar', '.g4/private/runtime.env', '.g4/tls/fullchain.pem', PUBLISH_INTENT):
            path = self.release / relative
            original = path.read_bytes()
            replacement = self.remote._publish_intent('restore').encode() if relative == PUBLISH_INTENT else b''
            self.private(path, replacement)
            with self.subTest(relative=relative), self.assertRaises(RuntimeError):
                self.resume()
            self.private(path, original)
        self.remote.operation.assert_not_called()
        self.remote.copy.assert_not_called()

    def test_fresh_publish_records_its_mode_only_after_checked_unpack(self):
        root = self.root / 'new-server-release'
        self.remote.folder, self.remote.remote_bundle = str(root), str(root / '.g4')
        self.remote.config = {'user': 'synthetic'}
        fixture = self.private(self.root / 'source-marker', b'tested source')
        source = self.artifacts / 'source.tar'
        with tarfile.open(source, 'w') as archive:
            archive.add(fixture, arcname='source-marker')
        meta = self.artifacts / 'build.json'
        payload = json.loads(meta.read_text())
        payload['source_sha256'] = digest(source)
        self.private(meta, json.dumps(payload).encode())

        def ssh(args, **kwargs):
            if args[0] == 'sh':
                raise RuntimeError('connection interrupted after checked transfer')
            if not root.exists():
                root.mkdir(mode=0o700)
                return b''
            return subprocess.check_output([sys.executable, *args[1:]], timeout=10)

        self.remote.ssh = Mock(side_effect=ssh)
        self.remote.copy = Mock(side_effect=shutil.copyfile)
        self.remote.operation = Mock()
        with self.assertRaisesRegex(RuntimeError, 'after checked transfer'):
            self.remote.publish(self.artifacts, self.recipient)
        self.assertEqual((root / PUBLISH_INTENT).read_text(), self.remote._publish_intent('fresh'))
        self.assertEqual(digest(root / 'source-marker'), digest(fixture))
        self.assertEqual(digest(root / '.g4/plan.json'), digest(self.bundle / 'plan.json'))
        self.remote.operation.assert_not_called()

    def test_partial_existing_credentials_are_preserved_and_block_finalization(self):
        local = self.private(self.bundle / 'private/demo-credentials.txt', b'synthetic partial')
        self.remote.operation = Mock(return_value=self.ready)
        with self.assertRaisesRegex(ValueError, 'Existing private handover'):
            self.resume()
        self.assertEqual(local.read_bytes(), b'synthetic partial')
        self.remote.operation.assert_called_once_with('status')
        self.remote.copy.assert_not_called()

    def test_publish_and_resume_share_the_local_operation_lock(self):
        with exclusive(self.bundle / 'private/publish.lock'):
            with self.assertRaises(BlockingIOError):
                self.resume()
            with self.assertRaises(BlockingIOError):
                self.remote.publish(self.artifacts, self.recipient)
        self.remote.ssh.assert_not_called()

    def test_interrupted_private_download_is_atomic_and_keeps_existing_file(self):
        remote = self.remote
        remote.folder = '/srv/adc-course/releases/fixture'
        remote.config, remote.options, remote.target = {'sudo': True}, [], 'operator@synthetic'
        remote.log = self.root / 'private.log'
        path = self.bundle / 'private/COURSE_ACCESS.md'

        def interrupt(*args, output_file, **kwargs):
            output_file.write(b'partial')
            raise RuntimeError('lost SSH reply')

        def finish(*args, output_file, **kwargs):
            output_file.write(b'complete')

        target = remote.folder + '/.g4/private/COURSE_ACCESS.md'
        with patch('scripts.g4_remote.run', side_effect=interrupt), self.assertRaises(RuntimeError):
            Remote.copy(remote, path, target, download=True)
        self.assertFalse(path.exists())
        with patch('scripts.g4_remote.run', side_effect=finish) as run:
            Remote.copy(remote, path, target, download=True)
            with self.assertRaises(FileExistsError):
                Remote.copy(remote, path, target, download=True)
        run.assert_called_once()
        self.assertEqual(path.read_bytes(), b'complete')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
