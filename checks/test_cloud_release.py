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
