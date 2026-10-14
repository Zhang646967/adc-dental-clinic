"""Allowlisted read-only facts from an explicitly selected synthetic G4 Web.

Run via stdin in the inspected container with matching ADC_G4_PROJECT/--project.
No credentials, contact fields, clinical notes, sessions or tokens are exported.
"""
import argparse
import hashlib
import json
import os
import re

parser = argparse.ArgumentParser()
parser.add_argument('--project', required=True)
args = parser.parse_args()
if not re.fullmatch(r'adc_g4_[0-9a-f]{12}', args.project) or os.environ.get('ADC_G4_PROJECT') != args.project:
    raise SystemExit('Explicit matching G4 project required.')

import django
django.setup()
from django.apps import apps
from django.conf import settings
from django.db import connection, transaction

if (not settings.ADC_READ_ONLY or connection.vendor != 'postgresql' or
        connection.settings_dict['NAME'] != 'adc_rc_demo' or
        connection.settings_dict['USER'] != 'adc_g4_runtime'):
    raise SystemExit('Dedicated read-only synthetic G4 runtime required.')

fields = {
    'accounts.UserAccount': 'id username dentist_id is_active is_staff is_superuser',
    'accounts.RoleAssignment': 'id user_id role clinic_id is_active',
    'registry.Dentist': 'id employee_no is_active',
    'registry.Qualification': 'id code is_active',
    'registry.DentistQualification': 'id dentist_id qualification_id is_active',
    'registry.TreatmentType': 'id code standard_unit_price',
    'patients.Patient': 'id patient_no allergy_status allergy_info_version',
    'scheduling.AvailabilitySlot': 'id clinic_id dentist_id starts_at ends_at is_active booking_paused intake_revision',
    'scheduling.Visit': 'id visit_no patient_id clinic_id dentist_id availability_slot_id status scheduled_start scheduled_end attended attended_at completed_at lock_version replaces_visit_id',
    'care.VisitRecordVersion': 'id visit_id revision_no state total_amount previous_version_id correction_request_id prepared_by_id reviewed_by_id published_at',
    'care.TreatmentRecord': 'id record_version_id quantity unit_price line_amount',
    'care.Invoice': 'id visit_id current_record_version_id first_issued_at',
    'care.CorrectionRequest': 'id visit_id kind status requester_id reviewer_id base_record_version_id',
    'finance.Quarter': 'id year quarter_no roster_status',
    'finance.DentistQuarterCost': 'id quarter_id dentist_id cost_status supply_cost operating_expense',
    'coordination.WaitRequest': 'id patient_id clinic_id state revision',
    'coordination.WaitOffer': 'id request_id slot_id state visit_id starts_at ends_at expires_at',
    'coordination.CoordinationTask': 'id slot_id purpose state assignee_id submitted_by_id closed_by_id revision',
    'notifications.NotificationOutbox': 'id task_id action state event_state completed_at',
    'notifications.InboxMessage': 'id event_id recipient_id grant_id clinic_id role read_at',
}
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
    rows = {name: list(apps.get_model(name).objects.order_by('id').values(*columns.split()))
            for name, columns in fields.items()}
    headers = list(apps.get_model('care.VisitRecordVersion').objects.order_by('id').values(
        'id', 'billing_header_snapshot'))
    receipts = apps.get_model('portal.BookingReceipt').objects.count()
    payload = json.dumps({'rows': rows, 'headers': headers, 'receipts': receipts},
                         default=str, sort_keys=True, ensure_ascii=False).encode()
    counts = {name: len(values) for name, values in rows.items()}
    counts['portal.BookingReceipt'] = receipts

print(json.dumps({'scope': 'Allowlisted committed synthetic business facts; technical sessions/context excluded',
                  'counts': counts, 'business_sha256': hashlib.sha256(payload).hexdigest()}, indent=2))
