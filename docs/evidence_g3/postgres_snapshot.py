"""Read-only, allowlisted facts for a deliberately named synthetic G3 instance.

Run through stdin in that instance's web container with --instance NAME.
Never export credentials, contact fields, clinical notes, sessions or tokens.
This checks committed facts; it does not substitute for browser interactions.
"""
import argparse
import hashlib
import json
import os
import re

parser = argparse.ArgumentParser()
parser.add_argument('--instance', required=True)
args = parser.parse_args()
if (not re.fullmatch(r'adc_rc1_[0-9a-f]{12}', args.instance)
        or os.environ.get('ADC_RC_INSTANCE') != args.instance
        or os.environ.get('ADC_RC_SYNTHETIC') != '1'):
    raise SystemExit('Explicit matching synthetic instance required.')

import django
django.setup()
from django.apps import apps
from django.db import connection, transaction

if connection.vendor != 'postgresql' or connection.settings_dict['NAME'] != 'adc_rc_demo':
    raise SystemExit('Dedicated synthetic PostgreSQL database required.')

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
        cursor.execute('SELECT CURRENT_TIMESTAMP')
        observed_at = cursor.fetchone()[0]
    rows = {name: list(apps.get_model(name).objects.order_by('id').values(*columns.split()))
            for name, columns in fields.items()}
    headers = [
        {'record_id': item['id'], 'sha256': hashlib.sha256(json.dumps(
            item['billing_header_snapshot'], sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
        for item in apps.get_model('care.VisitRecordVersion').objects.order_by('id').values(
            'id', 'billing_header_snapshot')
    ]
    receipt_count = apps.get_model('portal.BookingReceipt').objects.count()
print(json.dumps({'scope': 'Committed allowlisted synthetic PostgreSQL facts',
                  'observed_at': observed_at, 'rows': rows,
                  'billing_header_hashes': headers, 'booking_receipts': receipt_count},
                 default=str, ensure_ascii=False, indent=2))
