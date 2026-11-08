"""First publication recovery with real file checks and controlled SSH replies."""
from pathlib import Path
import json
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.g4_course import digest, exclusive
from scripts.g4_prepare import prepare
from scripts.g4_remote import (PUBLISH_INTENT, PublicationPreflightError, Remote,
                               VERIFY_PUBLISH_COMPLETION, VERIFY_PUBLISH_RESUME)


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
        self.marker = self.release / '.g4/private/deployed.json'
        self.private(self.marker, self.marker_bytes())

    def marker_bytes(self):
        return json.dumps(dict(project=self.ready['project'], source_commit=self.source, fresh_seed=True)).encode()

    @staticmethod
    def private(path, value):
        path.write_bytes(value)
        path.chmod(0o600)
        return path

    def ssh(self, args, **kwargs):
        if args[:2] == ['python3', '-c'] and args[2] in (VERIFY_PUBLISH_RESUME, VERIFY_PUBLISH_COMPLETION):
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

    def test_healthy_origin_before_handover_finishes_using_existing_deploy(self):
        guide = self.marker.with_name('COURSE_ACCESS.md')
        guide.unlink()
        self.marker.unlink()
        credentials = self.marker.with_name('demo-credentials.txt')
        before = (credentials.stat().st_ino, digest(credentials))

        def operation(action, extra=()):
            if action == 'deploy':
                self.private(guide, b'completed access guide')
                self.private(self.marker, self.marker_bytes())
            return {'list-backups': {'backups': []}, 'backup': {'status': 'SERVER_BACKUP_CREATED'}}.get(
                action, self.ready)

        self.remote.operation = Mock(side_effect=operation)
        self.assertEqual(self.resume()['first_server_backup'], 'CREATED')
        self.assertEqual([call.args[0] for call in self.remote.operation.call_args_list],
                         ['status', 'deploy', 'install-server-jobs', 'list-backups', 'backup'])
        self.assertEqual((credentials.stat().st_ino, digest(credentials)), before)
        self.assertEqual((self.bundle / 'private' / guide.name).read_bytes(), guide.read_bytes())

    def test_still_missing_completion_or_wrong_marker_never_installs_jobs(self):
        self.marker.unlink()
        self.remote.operation = Mock(return_value=self.ready)
        with self.assertRaisesRegex(ValueError, 'readiness and handover'):
            self.resume()
        self.assertEqual([call.args[0] for call in self.remote.operation.call_args_list], ['status', 'deploy'])
        self.private(self.marker, self.marker_bytes().replace(self.source.encode(), b'b' * 40))
        self.remote.operation.reset_mock()
        with self.assertRaises(RuntimeError):
            self.resume()
        self.remote.operation.assert_called_once_with('status')
        self.remote.copy.assert_not_called()

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
        self.remote._preflight = Mock()
        with self.assertRaisesRegex(RuntimeError, 'after checked transfer'):
            self.remote.publish(self.artifacts, self.recipient)
        self.assertEqual((root / PUBLISH_INTENT).read_text(), self.remote._publish_intent('fresh'))
        self.assertEqual(digest(root / 'source-marker'), digest(fixture))
        self.assertEqual(digest(root / '.g4/plan.json'), digest(self.bundle / 'plan.json'))
        self.remote.operation.assert_not_called()

    def test_preflight_refusals_do_not_prepare_remote_paths_or_upload(self):
        remote = self.remote
        remote.config = {'host': '8.8.8.8', 'user': 'synthetic'}

        def answers(host, port, family):
            if family == socket.AF_INET:
                return [(family, 0, 0, '', ('8.8.8.8', port))]
            raise socket.gaierror(socket.EAI_NONAME, 'synthetic no AAAA')

        with patch('scripts.g4_course.socket.getaddrinfo', return_value=[
                (socket.AF_INET, 0, 0, '', ('8.8.4.4', 80))]):
            with self.assertRaisesRegex(ValueError, 'A records'):
                remote.publish(self.artifacts, self.recipient)
        remote.ssh.assert_not_called()
        remote.copy.assert_not_called()

        for failure in ('amd64 required', 'port already occupied', 'insufficient disk'):
            remote.ssh = Mock(side_effect=RuntimeError(failure))
            with self.subTest(failure=failure), patch('scripts.g4_course.socket.getaddrinfo', side_effect=answers):
                with self.assertRaisesRegex(PublicationPreflightError, 'before upload'):
                    remote.publish(self.artifacts, self.recipient)
            remote.ssh.assert_called_once()
            command = remote.ssh.call_args.args[0]
            self.assertEqual(command[:2], ['sh', '-c'])
            self.assertEqual(command[4], '--preflight')
            remote.copy.assert_not_called()

        remote.ssh = Mock(return_value=b'HOST_PREFLIGHT_READY\n')
        with patch('scripts.g4_course.socket.getaddrinfo', side_effect=answers):
            result = remote.preflight(self.artifacts, self.recipient)
        self.assertEqual(result['status'], 'PREFLIGHT_READY')
        self.assertFalse(result['public_acceptance_executed'])
        remote.ssh.assert_called_once()
        remote.copy.assert_not_called()

    def test_actual_host_preflight_shell_rejects_wrong_platform_and_occupied_ports(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/g4_host_bootstrap.sh'
        ubuntu = self.private(self.root / 'os-release', b'ID=ubuntu\nVERSION_ID=24.04\n')
        apt = self.private(self.root / 'apt-get', b'#!/bin/sh\nexit 89\n')
        apt.chmod(0o700)
        payload = script.read_text().replace('. /etc/os-release', '. "$3"')
        # Override only the read-only host inputs. Reaching apt would fail.
        fixture = ('id() { echo 0; }; uname() { echo "$ARCH"; }; ss() { printf "%s" "$LISTENERS"; }; '
                   'docker() { case "$*" in *ps*) :;; *info*) echo /var/lib/docker;; esac; }; '
                   'python3() { cat >/dev/null; echo HOST_PREFLIGHT_READY; };\n')
        for arch, listeners, expected in (('aarch64', '', 'amd64'), ('x86_64', ':443', 'HTTPS listener'),
                                           ('x86_64', '', 'HOST_PREFLIGHT_READY')):
            env = dict(ARCH=arch, LISTENERS=listeners, PATH=f'{self.root}:/usr/bin:/bin')
            call = subprocess.run(['sh', '-c', fixture + payload, 'test-host', '--preflight',
                                   str(self.root / 'new-release'), str(ubuntu)],
                                  env=env, capture_output=True, text=True, timeout=10)
            self.assertIn(expected, call.stdout + call.stderr)
            self.assertEqual(call.returncode, 0 if expected == 'HOST_PREFLIGHT_READY' else 1)
        self.assertFalse((self.root / 'new-release').exists())

    def test_first_publish_transport_allows_combined_server_stages(self):
        remote = self.remote
        remote.ssh = Mock(return_value=b'{}')
        for action in ('deploy', 'restore-verified-dump', 'backup'):
            remote.operation(action)
            self.assertGreater(remote.ssh.call_args.kwargs['timeout'], 900)
        remote.operation('upgrade', timeout=1800)
        self.assertEqual(remote.ssh.call_args.kwargs['timeout'], 1800)

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
