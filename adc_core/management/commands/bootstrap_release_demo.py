"""Seed ONLY a fresh isolated RC database; private credential file, never logs."""
import io,os
from pathlib import Path
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand,CommandError
from django.db import connection,transaction
from django.test.utils import override_settings
from accounts.models import UserAccount
from registry.models import Clinic,Dentist
from patients.models import Patient
from scheduling.models import AvailabilitySlot

class Command(BaseCommand):
    help='Create synthetic RC demo in an empty domain, saving private local credentials.'
    def handle(self,*args,**options):
        if os.environ.get('ADC_RC_SYNTHETIC')!='1' or connection.settings_dict['NAME']!='adc_rc_demo' or settings.ADC_READ_ONLY:
            raise CommandError('Writable dedicated RC synthetic instance required.')
        if any(m.objects.exists() for m in (UserAccount,Clinic,Dentist,Patient,AvailabilitySlot)):
            raise CommandError('Refusing to seed an existing domain or imported data.')
        capture=io.StringIO()
        # Seed helpers require DEBUG for local use; override only this explicit command.
        with override_settings(DEBUG=True), transaction.atomic():
            for name in ('seed_demo','seed_portal_demo','seed_workspace_demo'):
                call_command(name,stdout=capture)
        # Wrapper redirects this explicit private output into a local private file.
        # It must never be attached to evidence or a course report.
        self.stdout.write(capture.getvalue())
