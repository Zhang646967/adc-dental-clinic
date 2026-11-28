"""Create the first institution and its technical administrator in one transaction."""
import json
import os
import re
import sys

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from accounts.models import RoleAssignment, UserAccount
from care.audit import emit
from care.models import AuditEvent
from patients.models import Patient
from registry.models import Clinic, Dentist
from scheduling.models import AvailabilitySlot, Visit


EVENT = 'clinic.initialized'
CLINIC_FIELDS = {'clinic_code', 'name', 'postal_address', 'supervisor_name', 'phone', 'email', 'area_sqm'}


def require_installation():
    instance = os.environ.get('ADC_CLINIC_INSTALLATION', '')
    if not (re.fullmatch(r'adc_g4_[a-f0-9]{12}', instance)
            and instance == os.environ.get('ADC_OPERATIONS_INSTANCE')
            and settings.SETTINGS_MODULE == 'config.settings.g4_maintenance'
            and os.environ.get('ADC_G4_MAINTENANCE') == '1'
            and settings.ADC_PATIENT_AUTH_MODE == 'live'
            and not settings.ADC_CLINICAL_SYNTHETIC and not settings.ADC_READ_ONLY
            and connection.vendor == 'postgresql' and connection.settings_dict['NAME'] == 'adc_clinic'):
        raise CommandError('A private production maintenance process and dedicated clinic database are required.')


@transaction.atomic
def initialize(document):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(1503915401, 1)")
    if any(model.objects.exists() for model in (Clinic, UserAccount, RoleAssignment, Dentist, Patient, Visit, AvailabilitySlot, AuditEvent)):
        raise CommandError('Initialization requires an empty business database.')
    if not isinstance(document, dict) or set(document) != {'clinic', 'administrator'}:
        raise CommandError('Provide both clinic and administrator.')
    clinic_data, admin_data = document['clinic'], document['administrator']
    if (not isinstance(clinic_data, dict) or set(clinic_data) != CLINIC_FIELDS
            or not isinstance(admin_data, dict) or set(admin_data) != {'username', 'password'}
            or not all(isinstance(value, str) and value.strip() for value in [*clinic_data.values(), *admin_data.values()])):
        raise CommandError('The required institution or administrator fields are incomplete.')
    clinic = Clinic(**clinic_data)
    administrator = UserAccount(username=admin_data['username'], is_active=True, is_staff=False, is_superuser=False)
    password = admin_data['password']
    if not 16 <= len(password) <= 256:
        raise CommandError('Use a unique administrator password of 16–256 characters.')
    try:
        clinic.full_clean()
        administrator.full_clean(exclude=['password'])
        validate_password(password, administrator)
    except ValidationError as exc:
        # Field validators can contain private input values. Return only field names.
        fields = sorted(getattr(exc, 'error_dict', {'administrator': []}))
        raise CommandError('Check the values for ' + ', '.join(fields)) from None
    administrator.set_password(password)
    clinic.save(force_insert=True)
    administrator.save(force_insert=True)
    RoleAssignment.objects.create(user=administrator, role='SYSADMIN', scope_kind='TECHNICAL')
    emit(administrator, EVENT, clinic, summary={'grant': 'SYSADMIN', 'scope': 'TECHNICAL'})
    return {'status': 'INITIALIZED', 'clinics_created': 1, 'technical_administrators_created': 1}


class Command(BaseCommand):
    help = 'Initialize an empty clinic using private JSON from stdin.'

    def add_arguments(self, parser):
        parser.add_argument('--status-only', action='store_true')

    def handle(self, *args, **options):
        require_installation()
        if options['status_only']:
            result = {'status': 'INITIALIZED' if AuditEvent.objects.filter(event_type=EVENT).exists() else 'UNINITIALIZED'}
        else:
            payload = sys.stdin.buffer.read(16385)
            if len(payload) > 16384:
                raise CommandError('Institution setup exceeds the size limit.')
            try:
                document = json.loads(payload)
            except (ValueError, UnicodeError):
                raise CommandError('Provide valid UTF-8 institution JSON.') from None
            result = initialize(document)
        self.stdout.write(json.dumps(result))
