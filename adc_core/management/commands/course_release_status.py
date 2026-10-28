"""Private release metadata only; never include account or patient values."""
import hashlib
import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Report release, migration and synthetic dataset metadata without personal data.'

    def handle(self, *args, **options):
        from registry.directory_models import ClinicDirectory
        migrations = {str(p.relative_to(settings.BASE_DIR)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(Path(settings.BASE_DIR).glob('*/migrations/[0-9]*.py'))}
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM django_migrations WHERE app NOT IN ('auth','contenttypes','sessions','admin')")
            applied = cursor.fetchone()[0]
        self.stdout.write(json.dumps({'source_commit': os.environ.get('ADC_SOURCE_COMMIT', 'unknown'),
            'migration_files': len(migrations), 'applied_application_migrations': applied,
            'migration_sha256': hashlib.sha256(json.dumps(migrations, sort_keys=True).encode()).hexdigest(),
            'published_synthetic_clinics': ClinicDirectory.objects.filter(is_published=True, synthetic=True).count(),
            'synthetic_business_data': settings.ADC_CLINICAL_SYNTHETIC,
            'authentication_mode': settings.ADC_PATIENT_AUTH_MODE,
            'real_wechat_acceptance': 'NOT_RECORDED', 'physical_device_acceptance': 'NOT_RECORDED'}))
