"""Read-only business/credential digests for an explicitly identified course DB.

Execute inside its runtime container; output no passwords, contact values,
session keys, clinical text or raw records. Not a browser acceptance substitute.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--project', required=True)
parser.add_argument('--load-prefix')
args = parser.parse_args()
if (not re.fullmatch(r'adc_g4_[0-9a-f]{12}', args.project) or
        os.environ.get('ADC_COURSE_PROJECT') != args.project or
        os.environ.get('ADC_COURSE_SYNTHETIC') != '1' or
        os.environ.get('DJANGO_SETTINGS_MODULE') != 'config.settings.production'):
    raise SystemExit('Explicit matching synthetic course runtime required.')

import django
django.setup()
from django.apps import apps
from django.db import connection, transaction
from django.conf import settings

if connection.vendor != 'postgresql' or connection.settings_dict['NAME'] != 'adc_rc_demo' or settings.ADC_READ_ONLY:
    raise SystemExit('Separate writable PostgreSQL course database required.')

facts = {}
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
    for model in apps.get_models():
        if model._meta.app_label not in ('accounts', 'registry', 'patients', 'scheduling', 'care',
                                         'finance', 'coordination', 'notifications', 'portal'):
            continue
        # Login timestamps may change during normal recovery/login verification.
        columns = [f.attname for f in model._meta.fields if f.attname != 'last_login']
        h, count = hashlib.sha256(), 0
        for row in model.objects.order_by('pk').values(*columns).iterator(chunk_size=100):
            h.update(json.dumps(row, sort_keys=True, default=str, ensure_ascii=False).encode())
            h.update(b'\n')
            count += 1
        facts[model._meta.label] = {'count': count, 'sha256': h.hexdigest()}
    result = {'project': args.project, 'scope': 'business tables and hashed account credentials',
              'server_major': connection.pg_version // 10000, 'timezone': settings.TIME_ZONE,
              'facts': facts, 'public_acceptance_executed': False}
    if args.load_prefix:
        if not re.fullmatch(r'COURSE-LOAD-[0-9a-f]{12}-[0-9a-f]{8}-', args.load_prefix):
            raise SystemExit('Use the recorded bounded synthetic workload prefix.')
        patient = apps.get_model('patients.Patient')
        rows = list(patient.objects.filter(name__startswith=args.load_prefix).values_list('name', flat=True))
        result['load_oracle'] = {'created': len(rows), 'distinct_names': len(set(rows))}
print(json.dumps(result, indent=2))
