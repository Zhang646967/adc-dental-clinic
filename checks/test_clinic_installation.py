"""Boundaries of a new institution's installation profile."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.clinic_release import ClinicInstallation
from scripts.g4_course import Course
from scripts.g4_prepare import inspect_bundle, prepare, read_env


class ClinicProfileTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.bundle = Path(self.folder.name) / '.g4'
        self.inputs = dict(host='clinic.example.org', source_commit='1'*40, app_image='sha256:'+'2'*64,
                           db_image='postgres:17@sha256:'+'3'*64, nginx_image='nginx:stable-alpine@sha256:'+'4'*64,
                           http_port=19180, https_port=19443, access_mode='clinic-writable', dataset='empty')

    def test_simulation_and_clinic_profiles_are_mutually_exclusive(self):
        for overrides in ({'access_mode': 'course-writable'}, {'dataset': 'course-20'}, {'mode': 'teacher_tunnel'}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                prepare(self.bundle, **(self.inputs | overrides))
        prepare(self.bundle, **self.inputs)
        self.assertEqual(inspect_bundle(self.bundle)['access_mode'], 'clinic-writable')
        env = read_env(self.bundle / 'private/runtime.env')
        self.assertEqual(env['POSTGRES_DB'], 'adc_clinic')
        self.assertEqual(env['ADC_PATIENT_AUTH_MODE'], 'live')
        self.assertFalse(any('SYNTHETIC' in field for field in env))
        self.assertNotIn('bootstrap_release_demo', (self.bundle / 'compose.yaml').read_text())
        with self.assertRaises(ValueError):
            Course(self.bundle, context='unit', rehearsal=True)
        with patch('scripts.g4_course.docker_command', return_value=[]):
            clinic = ClinicInstallation(self.bundle, context='unit', rehearsal=True)
        # Reject a course archive before reading files or opening a database.
        with self.assertRaisesRegex(ValueError, 'profiles differ'):
            clinic._restore_decrypted('missing', {}, schema_mode='migration-built')

    def test_linux_image_inspection_uses_api_148_supported_arguments_and_actual_architecture(self):
        plan = prepare(self.bundle, **self.inputs)
        with patch('scripts.g4_course.docker_command', return_value=['docker']):
            clinic = ClinicInstallation(self.bundle, context='unit', rehearsal=True)
        def inspect(command, log):
            self.assertEqual(command[:3], ['docker', 'image', 'inspect'])
            self.assertEqual(len(command), 4)
            return json.dumps([{'Os': 'linux', 'Architecture': 'amd64', 'Config': {
                'Labels': {'org.opencontainers.image.revision': plan['requested_source_commit']}}}]).encode()
        with patch('scripts.g4_course.run', side_effect=inspect) as calls:
            clinic.images()
        self.assertEqual(calls.call_count, 3)
        for wrong in ({'Os': 'windows', 'Architecture': 'amd64'}, {'Os': 'linux', 'Architecture': 'arm64'}):
            with patch('scripts.g4_course.run', return_value=json.dumps([wrong]).encode()), self.assertRaises(ValueError):
                clinic.images()

    def test_recovery_requires_the_independent_custody_record(self):
        prepare(self.bundle, **self.inputs)
        with patch('scripts.g4_course.docker_command', return_value=[]):
            clinic = ClinicInstallation(self.bundle, context='unit', rehearsal=True)
        archive = self.bundle / 'private/archive.age'
        identity = self.bundle / 'private/current-identity'
        for entry in (archive, identity):
            entry.touch(mode=0o600)
        with patch('scripts.g4_course.decrypt_backup') as decrypt:
            with self.assertRaisesRegex(ValueError, 'custody record'):
                clinic.restore(archive, identity, expected_source='adc_g4_010203040506', expected_sha256='0'*64)
            decrypt.assert_not_called()
        from scripts.g4_course import digest
        with patch('scripts.g4_course.decrypt_backup', return_value={'project':'adc_g4_000000000000'}):
            with self.assertRaisesRegex(ValueError, 'different institution'):
                clinic.restore(archive, identity, expected_source='adc_g4_010203040506', expected_sha256=digest(archive))

    def test_maintenance_and_runtime_cannot_enable_training(self):
        prepare(self.bundle, **self.inputs)
        for who in ('runtime', 'maintenance'):
            path = self.bundle / ('private/' + who + '.env')
            original = path.read_text()
            with self.subTest(who=who):
                path.write_text(original + 'ADC_COURSE_SYNTHETIC=1\n')
                with self.assertRaises(ValueError):
                    inspect_bundle(self.bundle)
                path.write_text(original)
