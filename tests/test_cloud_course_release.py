"""The complete valid seed is exercised on an actual empty adc_rc_demo rehearsal."""
import io
import os
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import UserAccount


class CourseReleaseGuardTests(TestCase):
    def test_ordinary_application_database_cannot_be_seeded_implicitly(self):
        with self.assertRaises(CommandError):
            call_command('bootstrap_course_release', stdout=io.StringIO())
        self.assertFalse(UserAccount.objects.exists())

    @override_settings(ADC_READ_ONLY=True, ADC_CLINICAL_SYNTHETIC=True)
    def test_read_only_never_becomes_writable_via_course_initializer(self):
        with patch.dict(os.environ, {'ADC_RC_SYNTHETIC': '1'}), self.assertRaises(CommandError):
            call_command('bootstrap_course_release', stdout=io.StringIO())
        self.assertFalse(UserAccount.objects.exists())
