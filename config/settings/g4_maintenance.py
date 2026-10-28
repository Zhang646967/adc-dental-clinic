"""Explicit private G4 maintenance process; never the Web/worker settings."""
import os
import sys
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

if os.environ.get('ADC_G4_MAINTENANCE') != '1':
    raise ImproperlyConfigured('Explicit private G4 maintenance process required.')
if (Path(sys.argv[0]).name != 'manage.py' or len(sys.argv) < 2 or
        sys.argv[1] not in {'migrate', 'collectstatic', 'check', 'check_g4_deployment', 'showmigrations',
                           'bootstrap_release_demo', 'bootstrap_course_release', 'invalidate_auth_challenges'}):
    raise ImproperlyConfigured('Maintenance settings are limited to explicit management commands.')

# Validate the same host, proxy, TLS and runtime configuration first. Only this
# separate process receives the migration owner's password and changes DB user.
from .production import *

_owner_password = os.environ.get('ADC_MIGRATION_PASSWORD', '')
if len(_owner_password) < 32 or _owner_password == os.environ.get('POSTGRES_PASSWORD'):
    raise ImproperlyConfigured('Separate migration-owner password required.')
DATABASES['default']['USER'] = os.environ['ADC_DATABASE_OWNER']
DATABASES['default']['PASSWORD'] = _owner_password
ADC_READ_ONLY = False
