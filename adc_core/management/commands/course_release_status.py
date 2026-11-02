"""Private release metadata only; never include account or patient values."""
import hashlib
import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from scripts.g4_manifest import migrations, source_inventory


class Command(BaseCommand):
    help = 'Report release, migration and synthetic dataset metadata without personal data.'

    def handle(self, *args, **options):
        from registry.directory_models import ClinicDirectory
        files = migrations(settings.BASE_DIR)
        expected = {(Path(name).parts[0], Path(name).stem) for name in files}
        with connection.cursor() as cursor:
            cursor.execute("SELECT app, name FROM django_migrations WHERE app NOT IN ('auth','contenttypes','sessions','admin')")
            applied = set(cursor.fetchall())
        self.stdout.write(json.dumps({'source_commit': os.environ.get('ADC_SOURCE_COMMIT', 'unknown'),
            'product': 'ADC', 'release_edition': 'UNIFIED',
            'migration_files': len(files), 'applied_application_migrations': len(applied),
            'migration_sha256': hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
            'schema_matches_source': expected == applied,
            'pending_application_migrations': len(expected - applied),
            'unexpected_application_migrations': len(applied - expected),
            'release_inventory': source_inventory(settings.BASE_DIR),
            'published_synthetic_clinics': ClinicDirectory.objects.filter(is_published=True, synthetic=True).count(),
            'synthetic_business_data': settings.ADC_CLINICAL_SYNTHETIC,
            'authentication_mode': settings.ADC_PATIENT_AUTH_MODE,
            'real_wechat_acceptance': 'NOT_RECORDED', 'physical_device_acceptance': 'NOT_RECORDED'}))
