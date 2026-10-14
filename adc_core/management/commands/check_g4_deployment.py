"""Django deployment checks with only the reviewed initial HSTS policy allowed."""
import json
from django.conf import settings
from django.core import checks
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Check G4 settings; does not certify DNS, TLS, backups or a live host.'
    requires_system_checks = []

    def handle(self, *args, **options):
        if settings.SETTINGS_MODULE not in ('config.settings.production', 'config.settings.g4_maintenance'):
            raise CommandError('Use the reviewed G4 production or maintenance settings.')
        if (len(settings.ALLOWED_HOSTS) != 1 or settings.SECURE_HSTS_SECONDS != 3600 or
                settings.SECURE_HSTS_INCLUDE_SUBDOMAINS or settings.SECURE_HSTS_PRELOAD):
            raise CommandError('Review the initial single-host, short HSTS policy before changing it.')
        issues = checks.run_checks(include_deployment_checks=True)
        # These warnings explicitly concern parent/subdomain and browser-preload
        # commitments. The current candidate deliberately makes neither. Every
        # other warning/error still blocks this command; none are silenced.
        reviewed = {'security.W005', 'security.W021'}
        blocking = [i.id for i in issues if i.level >= checks.WARNING and i.id not in reviewed]
        if blocking:
            raise CommandError('Unreviewed deployment issues: ' + ', '.join(blocking))
        self.stdout.write(json.dumps({
            'configuration_checks': 'PASS',
            'reviewed_initial_hsts_warnings': sorted(i.id for i in issues if i.id in reviewed),
            'public_acceptance_executed': False,
        }))
