"""G4 settings checks: reviewed HSTS warnings do not waive other warnings."""
import io
from unittest.mock import patch
from django.core import checks
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings


@override_settings(SETTINGS_MODULE='config.settings.production', ALLOWED_HOSTS=['adc.g4.test'],
                   SECURE_HSTS_SECONDS=3600, SECURE_HSTS_INCLUDE_SUBDOMAINS=False,
                   SECURE_HSTS_PRELOAD=False)
class G4DeploymentCheckTests(SimpleTestCase):
    def test_only_reviewed_hsts_warnings_are_reported_and_accepted(self):
        output = io.StringIO()
        with patch('adc_core.management.commands.check_g4_deployment.checks.run_checks', return_value=[
            checks.Warning('Single host', id='security.W005'),
            checks.Warning('No preload yet', id='security.W021'),
        ]) as run:
            call_command('check_g4_deployment', stdout=output)
        run.assert_called_once_with(include_deployment_checks=True)
        self.assertIn('security.W005', output.getvalue())
        self.assertIn('"public_acceptance_executed": false', output.getvalue())

    def test_an_unreviewed_warning_still_blocks(self):
        with patch('adc_core.management.commands.check_g4_deployment.checks.run_checks', return_value=[
            checks.Warning('Weak secret', id='security.W009'),
        ]), self.assertRaises(CommandError):
            call_command('check_g4_deployment')

    def test_maintenance_settings_are_not_a_general_server_configuration(self):
        with override_settings(SETTINGS_MODULE='config.settings.test'), self.assertRaises(CommandError):
            call_command('check_g4_deployment')

    def test_unreviewed_preload_commitment_is_not_accepted(self):
        with override_settings(SECURE_HSTS_PRELOAD=True), self.assertRaises(CommandError):
            call_command('check_g4_deployment')
