"""Release orchestration boundaries; real Docker/PG evidence is recorded separately."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.g4_prepare import prepare, inspect_bundle, read_env
from scripts.g4_release import change_release, update_plan, versions
from scripts.g4_remote import Remote


class CloudReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bundle = Path(self.tmp.name) / '.g4'
        self.old, self.new = 'a' * 40, 'b' * 40
        self.old_image, self.new_image = 'sha256:' + '1' * 64, 'sha256:' + '2' * 64
        self.plan = prepare(self.bundle, host='course.adc.test', source_commit=self.old,
            app_image=self.old_image, db_image='postgres:17@sha256:' + '3' * 64,
            nginx_image='nginx:stable-alpine@sha256:' + '4' * 64, access_mode='course-writable',
            http_port=18197, https_port=18497, dataset='course-20')

    def course(self):
        c = Mock()
        c.bundle, c.plan = self.bundle, deepcopy(self.plan)
        c.backup.return_value = {'name': 'private-before-upgrade.tar.age'}
        for suffix in ('', '.json'):
            p = self.bundle / 'backups' / ('private-before-upgrade.tar.age' + suffix)
            p.write_bytes(b'unit fake ciphertext/checkpoint metadata')
            p.chmod(0o600)
        c.status.return_value = {'status': 'ORIGIN_READY'}
        return c

    def test_remote_maintenance_requires_the_retained_recovery_recipient(self):
        recipient = 'age1' + 'q' * 58
        path = self.bundle / 'private/recipient.txt'
        path.write_text(recipient + '\n')
        path.chmod(0o600)
        remote = object.__new__(Remote)
        remote.remote_bundle = '/srv/adc-course/releases/unit/.g4'
        remote.ssh = Mock(return_value=(recipient + '\n').encode())
        remote.check_backup_recipient(path)
        remote.ssh.assert_called_once_with(['cat', '--', remote.remote_bundle + '/private/backup-recipient.txt'])

    def test_remote_recipient_mismatch_stops_before_upload_or_maintenance(self):
        path = self.bundle / 'private/recipient.txt'
        path.write_text('age1' + 'q' * 58 + '\n')
        path.chmod(0o600)
        remote = object.__new__(Remote)
        remote.remote_bundle = '/srv/adc-course/releases/unit/.g4'
        remote.ssh = Mock(return_value=('age1' + 'p' * 58 + '\n').encode())
        with self.assertRaisesRegex(ValueError, 'differs from the server'):
            remote.rollback('a' * 40, path, 'b' * 40)

    def test_complete_dataset_has_separate_live_auth_and_memory_budget(self):
        runtime = read_env(self.bundle / 'private/runtime.env')
        self.assertEqual(runtime['ADC_RC_SYNTHETIC'], '1')
        self.assertEqual(runtime['ADC_PATIENT_AUTH_MODE'], 'live')
        self.assertEqual(runtime['ADC_PATIENT_IDENTITY_PROVIDER'], 'disabled')
        self.assertNotIn('ADC_MIGRATION_PASSWORD', runtime)
        text = (self.bundle / 'compose.yaml').read_text()
        self.assertIn('bootstrap_course_release', text)
        self.assertIn('mem_limit: 1536m', text)
        self.assertFalse(inspect_bundle(self.bundle)['public_acceptance_executed'])

    def test_update_and_rollback_keep_secrets_project_and_database_identity(self):
        files = ['private/runtime.env', 'private/maintenance.env', 'private/database.env']
        before = {n: read_env(self.bundle / n) for n in files}
        new = update_plan(self.bundle, self.new, self.new_image, controller=self.new)
        self.assertEqual(new['initial_source_commit'], self.old)
        self.assertEqual(new['project'], self.plan['project'])
        after = {n: read_env(self.bundle / n) for n in files}
        for n in files:
            self.assertEqual(before[n], {k: v for k, v in after[n].items() if k != 'ADC_SOURCE_COMMIT'} |
                             ({'ADC_SOURCE_COMMIT': self.old} if 'ADC_SOURCE_COMMIT' in before[n] else {}))
        # New privately configured authentication is retained during rollback.
        p = self.bundle / 'private/runtime.env'
        p.write_text(p.read_text() + 'ADC_WECHAT_MINI_APP_SECRET=private-new-setting\n')
        old = update_plan(self.bundle, self.old, self.old_image)
        self.assertEqual(read_env(p)['ADC_WECHAT_MINI_APP_SECRET'], 'private-new-setting')
        self.assertEqual(versions(old)[self.new], self.new_image)
        inspect_bundle(self.bundle)

    def test_stale_expected_version_never_stops_services(self):
        c = self.course()
        with patch('scripts.g4_release.inspect_artifacts', return_value={
                'source_commit': self.new, 'app_image': self.new_image}):
            with self.assertRaises(ValueError):
                change_release(c, artifacts='reviewed', recipient_file='public', expected_current='c' * 40)
        c.dc.assert_not_called()
        c.backup.assert_not_called()

    def test_migration_change_is_rejected_before_maintenance(self):
        c = self.course()
        with patch('scripts.g4_release.inspect_artifacts', return_value={
                'source_commit': self.new, 'app_image': self.new_image}), patch(
                'scripts.g4_release.image_migrations', side_effect=[{'old': '1'}, {'new': '2'}]):
            with self.assertRaises(ValueError):
                change_release(c, artifacts='reviewed', recipient_file='public', expected_current=self.old)
        c.dc.assert_not_called()

    def test_successful_upgrade_closes_gateway_then_backs_up_without_seeding(self):
        c = self.course()
        with patch('scripts.g4_release.inspect_artifacts', return_value={
                'source_commit': self.new, 'app_image': self.new_image}), patch(
                'scripts.g4_release.image_migrations', return_value={'same': 'migration'}), patch(
                'scripts.g4_release.start_candidate', return_value={'status': 'ORIGIN_READY'}):
            result = change_release(c, artifacts='reviewed', recipient_file='public', expected_current=self.old)
        self.assertEqual(result['status'], 'UPGRADED')
        self.assertFalse(result['database_restored'])
        self.assertEqual(c.dc.call_args_list[0].args[-1], 'gateway')
        c.backup.assert_called_once()
        self.assertNotIn('bootstrap', str(c.dc.call_args_list))
        self.assertNotIn('restore', str(c.dc.call_args_list))

    def test_failed_candidate_reverts_image_without_accepting_failed_version(self):
        c = self.course()
        with patch('scripts.g4_release.inspect_artifacts', return_value={
                'source_commit': self.new, 'app_image': self.new_image}), patch(
                'scripts.g4_release.image_migrations', return_value={'same': 'migration'}), patch(
                'scripts.g4_release.start_candidate', side_effect=[RuntimeError('candidate'), {'status': 'ORIGIN_READY'}]):
            with self.assertRaises(RuntimeError):
                change_release(c, artifacts='reviewed', recipient_file='public', expected_current=self.old)
        plan = json.loads((self.bundle / 'plan.json').read_text())
        self.assertEqual(plan['requested_source_commit'], self.old)
        self.assertNotIn(self.new, versions(plan))
        self.assertNotIn('restore', str(c.dc.call_args_list))
        result = json.loads((self.bundle / 'private/release-operation.json').read_text())
        self.assertEqual(result['status'], 'FAILED_IMAGE_REVERTED')

    def test_manual_rollback_uses_accepted_image_and_never_restores_database(self):
        c = self.course()
        c.plan = update_plan(self.bundle, self.new, self.new_image)
        with patch('scripts.g4_release.image_migrations', return_value={'same': 'migration'}), patch(
                'scripts.g4_release.start_candidate', return_value={'status': 'ORIGIN_READY'}):
            result = change_release(c, to_source=self.old, recipient_file='public', expected_current=self.new)
        self.assertEqual(result['status'], 'ROLLED_BACK')
        self.assertFalse(result['database_restored'])
        self.assertEqual(json.loads((self.bundle / 'plan.json').read_text())['project'], self.plan['project'])

    def test_same_version_repeat_does_not_create_another_backup_or_restart(self):
        c = self.course()
        with patch('scripts.g4_release.inspect_artifacts', return_value={
                'source_commit': self.old, 'app_image': self.old_image}):
            result = change_release(c, artifacts='reviewed', recipient_file='public', expected_current=self.old)
        self.assertEqual(result['status'], 'ALREADY_ACTIVE')
        c.backup.assert_not_called()
        c.dc.assert_not_called()

    def test_release_lock_prevents_a_second_concurrent_transition(self):
        from scripts.g4_course import exclusive
        c = self.course()
        with exclusive(self.bundle / 'private/release.lock'):
            with self.assertRaises(BlockingIOError):
                change_release(c, to_source=self.old, recipient_file='public', expected_current=self.old)
        c.dc.assert_not_called()

    def test_additive_option_does_not_allow_changed_old_migration_bytes(self):
        c = self.course()
        with patch('scripts.g4_release.inspect_artifacts', return_value={
                'source_commit': self.new, 'app_image': self.new_image}), patch(
                'scripts.g4_release.image_migrations', side_effect=[
                    {'accounts/migrations/0001.py': 'old'},
                    {'accounts/migrations/0001.py': 'changed', 'clinical/migrations/0002.py': 'new'}]):
            with self.assertRaisesRegex(ValueError, 'retain every old migration byte'):
                change_release(c, artifacts='reviewed', recipient_file='public',
                               expected_current=self.old, allow_additive=True)
        c.dc.assert_not_called()
        c.backup.assert_not_called()

    def test_backup_failure_before_additive_ddl_reopens_original_release(self):
        c = self.course()
        c.backup.side_effect = RuntimeError('backup failure')
        c.database_identity.return_value = {'volume': 'isolated'}
        current = {'accounts/migrations/0001.py': 'old'}
        target = current | {'clinical/migrations/0002.py': 'new'}
        with patch('scripts.g4_release.inspect_artifacts', return_value={
                'source_commit': self.new, 'app_image': self.new_image}), patch(
                'scripts.g4_release.image_migrations', side_effect=[current, target]), patch(
                'scripts.g4_release.applied_migrations', return_value={'accounts.0001'}), patch(
                'scripts.g4_release.check_upgrade_space'), patch('scripts.g4_release.schema_step') as schema:
            with self.assertRaisesRegex(RuntimeError, 'backup failure'):
                change_release(c, artifacts='reviewed', recipient_file='public',
                               expected_current=self.old, allow_additive=True)
        c.start_runtime.assert_called_once()
        self.assertEqual(c.plan['requested_source_commit'], self.old)
        schema.assert_called_once()
        self.assertFalse(schema.call_args.kwargs.get('apply', False))
        state = json.loads((self.bundle / 'private/release-operation.json').read_text())
        self.assertEqual(state['status'], 'FAILED_IMAGE_REVERTED')

    def test_applied_additive_failure_closes_gateway_and_resumes_without_rebackup(self):
        c = self.course()
        c.database_identity.return_value = {'volume': 'isolated'}
        c.dc.return_value = b''
        c.status.return_value = {'status': 'ORIGIN_READY'}
        current = {'accounts/migrations/0001.py': 'old'}
        target = current | {'clinical/migrations/0002.py': 'new'}
        before, after = {'accounts.0001'}, {'accounts.0001', 'clinical.0002'}
        options = dict(artifacts='reviewed', recipient_file='public',
                       expected_current=self.old, allow_additive=True)
        with patch('scripts.g4_release.inspect_artifacts', return_value={
                'source_commit': self.new, 'app_image': self.new_image}), patch(
                'scripts.g4_release.image_migrations', side_effect=[current, target, current, target]), patch(
                'scripts.g4_release.applied_migrations', side_effect=[before, before, after, after, after, after]), patch(
                'scripts.g4_release.check_upgrade_space'), patch('scripts.g4_release.schema_step') as schema, patch(
                'scripts.g4_release.start_candidate', side_effect=[RuntimeError('candidate'), {'status': 'ORIGIN_READY'}]) as start:
            with self.assertRaisesRegex(RuntimeError, 'candidate'):
                change_release(c, **options)
            state = json.loads((self.bundle / 'private/release-operation.json').read_text())
            self.assertEqual(state['status'], 'FAILED_MAINTENANCE_REQUIRED')
            self.assertEqual(c.plan['requested_source_commit'], self.new)
            self.assertIn('gateway', c.dc.call_args.args)
            self.assertEqual(start.call_count, 1)
            with self.assertRaisesRegex(ValueError, 'original upgrade command'):
                change_release(c, to_source=self.old, recipient_file='public', expected_current=self.new)
            result = change_release(c, **options)
        self.assertEqual(result['status'], 'UPGRADED')
        self.assertFalse(result['database_restored'])
        c.backup.assert_called_once()
        self.assertEqual(sum(call.kwargs.get('apply', False) for call in schema.call_args_list), 1)

    def interrupted_deploy(self):
        from scripts.g4_course import Course
        with patch('scripts.g4_course.docker_command', return_value=['docker', '--context', 'unit']):
            c = Course(self.bundle, context='unit', rehearsal=True)
        phase = {'project': self.plan['project'], 'source_commit': self.old, 'phase': 'BOOTSTRAP_STARTED'}
        for name, raw in [('deployment-phase.json', json.dumps(phase)), ('demo-credentials.txt', 'private captured credentials')]:
            p = self.bundle / 'private' / name
            p.write_text(raw)
            p.chmod(0o600)
        c.render, c.images, c.start_runtime, c.status = Mock(), Mock(), Mock(), Mock(return_value={'status': 'ORIGIN_READY'})
        return c

    def test_lost_success_reply_is_reconciled_with_status_only_not_reseeded(self):
        c = self.interrupted_deploy()
        c.dc = Mock(return_value=b'{"status":"ALREADY_PREPARED"}')
        self.assertEqual(c.deploy()['status'], 'ORIGIN_READY')
        self.assertIn('--status-only', c.dc.call_args.args)
        c.dc.assert_called_once()
        c.start_runtime.assert_called_once()

    def test_partial_initialization_is_not_retried_as_a_new_seed(self):
        c = self.interrupted_deploy()
        c.dc = Mock(return_value=b'{"status":"NOT_PREPARED"}')
        with self.assertRaises(ValueError):
            c.deploy()
        c.start_runtime.assert_not_called()
        phase = json.loads((self.bundle / 'private/deployment-phase.json').read_text())
        self.assertEqual(phase['phase'], 'BOOTSTRAP_STARTED')
