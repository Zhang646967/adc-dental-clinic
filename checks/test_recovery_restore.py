"""Adverse restore gates; actual PG/age acceptance is recorded separately."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from checks import test_g4_course as course_tests, test_recovery_receipts as receipt_tests
from scripts.recovery_facts import METHOD, compare, fingerprint, validate
from scripts.recovery_observations import collect as observe, validate as validate_observations
from scripts.recovery_receipts import validate_restore, file_digest


def facts():
    return {'v': 1, 'method': METHOD, 'tables': {
        'public.finance_statementbatch': {'rows': 4, 'sha256': 'b' * 64, 'schema_sha256': 'c' * 64}}}


def target(project='adc_g4_222222222222'):
    return {'project': project, 'container_id': 'd' * 64, 'engine_sha256': 'e' * 64,
            'volume': project + '_data', 'volume_created_at': '2026-10-18T01:00:00Z'}


def proof(now):
    return {'v': 1, 'target': target(), 'comparison': compare(facts(), facts()),
            'elapsed_ms': 4200, 'completed_at': now.isoformat()}


def restore(self, fact):
    self.book.record('restored', fact, key_sha256=file_digest(self.key),
                     restore=proof(self.now), now=self.now)


class VerifiedRestoreReceiptTests(unittest.TestCase):
    setUp = receipt_tests.RecoveryReceiptTests.setUp
    private = receipt_tests.RecoveryReceiptTests.private
    point = receipt_tests.RecoveryReceiptTests.point
    status = receipt_tests.RecoveryReceiptTests.status
    record = receipt_tests.RecoveryReceiptTests.record
    restore = restore
    def test_verified_restore_is_bound_to_cipher_key_point_and_target(self):
        fact = self.point(); self.record(fact); self.restore(fact)
        result = self.status()
        self.assertEqual(result['code'], 0)
        self.assertEqual(result['restore_acceptance'], 'VERIFIED_EMPTY_TARGET_COMPARISON')
        self.assertEqual(result['conditions']['restored']['elapsed_ms'], 4200)
        self.private(self.key, b'changed-key')
        self.assertEqual(self.status()['conditions']['restored']['state'], 'UNKNOWN')

    def test_restore_uses_original_eight_day_boundary_not_test_date(self):
        for hours, state in ((193, 'WARNING'), (192, 'HEALTHY')):
            fact = self.point(hours=hours); self.restore(fact)
            self.assertEqual(self.status()['conditions']['restored']['state'], state)

    def test_new_download_does_not_claim_restore_of_newer_data(self):
        older = self.point(hours=3); self.record(older); self.restore(older)
        self.record(self.point(hours=1))
        self.assertEqual(self.status()['conditions']['restored']['reason'], 'NEWER_DOWNLOAD_NOT_RESTORED')

    def test_wrong_application_or_removed_cipher_cannot_use_old_restore(self):
        fact = self.point(); self.restore(fact)
        result = self.book.status('f'*40, self.image, self.destination, mode='mac', identity_file=self.key, now=self.now)
        self.assertEqual(result['conditions']['restored']['state'], 'UNKNOWN')
        (self.destination / fact['name']).unlink()
        self.assertEqual(self.status()['conditions']['restored']['state'], 'UNKNOWN')

    def test_missing_comparison_same_target_excess_time_and_future_proof_refused(self):
        for change in ({'comparison': {}}, {'target': target(self.project)},
                       {'elapsed_ms': 1800001}, {'elapsed_ms': True},
                       {'completed_at': (self.now + timedelta(seconds=1)).isoformat()}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.book.record('restored', self.point(), key_sha256=file_digest(self.key),
                                 restore=proof(self.now) | change, now=self.now)
        self.assertIsNone(self.book.load()['latest']['restored'])


class IndependentRestoreGateTests(unittest.TestCase):
    setUp = course_tests.CourseSafetyTests.setUp
    private = course_tests.CourseSafetyTests.private
    course = course_tests.CourseSafetyTests.course
    def materials(self):
        course = self.course()
        dump = self.private('database.dump', b'PGDMP synthetic parser fixture')
        expected = facts()
        observation_root = self.root / 'observations'
        observation_root.mkdir(mode=0o700)
        observations = observe(observation_root)
        self.private('facts.json', json.dumps(expected).encode())
        self.private('observations.json', json.dumps(observations).encode())
        from scripts.g4_course import digest
        meta = dict(format=2, project='adc_g4_111111111111', server_major=17,
                    source_commit=self.inputs['source_commit'], images={'app': self.inputs['app_image']},
                    database_identity=target('adc_g4_111111111111'),
                    snapshot_method='EXPORTED_REPEATABLE_READ', facts_sha256=fingerprint(expected),
                    files={name: {'sha256': digest(self.root/name), 'size': (self.root/name).stat().st_size}
                           for name in ('database.dump', 'facts.json', 'observations.json')})
        course.start_database = Mock()
        course.tables = Mock(return_value=0)
        course.dc = Mock(return_value=b'')
        course.database_identity = Mock(return_value=target(course.plan['project']))
        course.start_runtime = Mock()
        return course, dump, meta, expected

    def test_fact_mismatch_does_not_start_runtime_or_record_success(self):
        course, dump, meta, expected = self.materials()
        actual = deepcopy(expected); actual['tables']['public.finance_statementbatch']['sha256'] = 'f'*64
        with patch('scripts.g4_course.run', return_value=json.dumps({'facts': actual}).encode()), self.assertRaises(ValueError):
            course.restore_decrypted(dump, meta)
        course.start_runtime.assert_not_called()
        self.assertFalse((course.bundle/'private/restore-comparison.json').exists())

    def test_valid_facts_and_history_precede_start_and_plain_dump_never_stamps_receipt(self):
        course, dump, meta, expected = self.materials()
        course.start_runtime.side_effect = lambda: self.assertTrue((course.bundle/'private/recovered-observations.json').exists())
        with patch('scripts.g4_course.run', return_value=json.dumps({'facts': expected}).encode()):
            result = course.restore_decrypted(dump, meta)
        self.assertEqual(result['business_comparison'], 'PASSED')
        self.assertFalse((self.root/'recovery/receipts.json').exists())

    def test_running_worker_blocks_even_if_web_stopped(self):
        course, dump, meta, _ = self.materials()
        course.dc.return_value = b'db\nnotification-worker\n'
        with self.assertRaises(ValueError): course.restore_decrypted(dump, meta)
        course.start_runtime.assert_not_called()
        self.assertEqual(course.dc.call_count, 1)

    def test_bad_dump_and_comparison_materials_refused_before_import(self):
        course, dump, meta, _ = self.materials()
        (dump.parent/'facts.json').write_text('{}')
        with self.assertRaises(ValueError): course.restore_decrypted(dump, meta)
        self.assertFalse(any('pg_restore' in str(c) for c in course.dc.call_args_list))

    def test_partial_pg_restore_never_starts_runtime(self):
        course, dump, meta, _ = self.materials()
        course.dc.side_effect = [b'', RuntimeError('synthetic restore interruption')]
        with self.assertRaises(RuntimeError): course.restore_decrypted(dump, meta)
        course.start_runtime.assert_not_called()

    def test_full_table_missing_schema_rows_and_binary_differences_refused(self):
        for change in ({'rows': 5}, {'sha256': 'f'*64}, {'schema_sha256': 'f'*64}):
            actual = deepcopy(facts()); actual['tables']['public.finance_statementbatch'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): compare(facts(), actual)
        with self.assertRaises(ValueError): compare(facts(), facts() | {'tables': {}})

    def test_bounded_formats_and_booleans_refused(self):
        for value in (facts() | {'v': True}, facts() | {'method': 'repr'}, facts() | {'tables': {}}):
            with self.assertRaises(ValueError): validate(value)

    def test_historical_files_are_content_bound_and_missing_is_explicit(self):
        folder = self.root/'history'; (folder/'worker').mkdir(parents=True, mode=0o700)
        path = folder/'worker/heartbeat.json'; path.write_bytes(b'private historical observation'); path.chmod(0o600)
        value = observe(folder)
        self.assertIsNone(value['files']['monitor/monitor.json'])
        value['files']['worker/heartbeat.json']['base64'] = 'Y2hhbmdlZA=='
        with self.assertRaises(ValueError): validate_observations(value)

    def test_history_symlink_refused(self):
        folder = self.root/'history'; (folder/'worker').mkdir(parents=True, mode=0o700)
        (folder/'worker/heartbeat.json').symlink_to(self.private('other', b'private'))
        with self.assertRaises(OSError): observe(folder)
