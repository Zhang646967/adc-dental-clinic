"""The complete valid seed is exercised on an actual empty adc_rc_demo rehearsal."""
import io
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import UserAccount


class CourseReleaseGuardTests(TestCase):
    def test_release_metadata_checks_applied_migration_names_without_writes(self):
        output = io.StringIO()
        call_command('course_release_status', stdout=output)
        current = json.loads(output.getvalue())
        self.assertTrue(current['schema_matches_source'])
        self.assertEqual(current['pending_application_migrations'], 0)
        self.assertEqual(current['unexpected_application_migrations'], 0)
        self.assertEqual(current['release_edition'], 'UNIFIED')
        self.assertFalse(UserAccount.objects.exists())

    def test_equal_migration_counts_do_not_hide_different_source_names(self):
        from django.conf import settings
        count = len(list(Path(settings.BASE_DIR).glob('*/migrations/[0-9]*.py')))
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'synthetic_app/migrations'
            directory.mkdir(parents=True)
            for n in range(count):
                (directory / f'{n+1:04}_unapplied.py').write_text('# Synthetic source inventory only\n')
            output = io.StringIO()
            with override_settings(BASE_DIR=Path(folder)):
                call_command('course_release_status', stdout=output)
            result = json.loads(output.getvalue())
        self.assertEqual(result['migration_files'], result['applied_application_migrations'])
        self.assertFalse(result['schema_matches_source'])
        self.assertEqual(result['pending_application_migrations'], count)
        self.assertFalse(UserAccount.objects.exists())

    def test_ordinary_application_database_cannot_be_seeded_implicitly(self):
        with self.assertRaises(CommandError):
            call_command('bootstrap_course_release', stdout=io.StringIO())
        self.assertFalse(UserAccount.objects.exists())

    @override_settings(ADC_READ_ONLY=True, ADC_CLINICAL_SYNTHETIC=True)
    def test_read_only_never_becomes_writable_via_course_initializer(self):
        with patch.dict(os.environ, {'ADC_RC_SYNTHETIC': '1'}), self.assertRaises(CommandError):
            call_command('bootstrap_course_release', stdout=io.StringIO())
        self.assertFalse(UserAccount.objects.exists())
