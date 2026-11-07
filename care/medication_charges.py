"""Translate physical fulfilment into separately retained published charges."""
from django.db.models import F

from care.models import MedicationCharge
from clinical.dispensing import settlement_sources
from clinical.pharmacy_models import PharmacyQuoteLine


def pending_charges(visit):
    return [
        dict(quote_line_id=row['line_id'], through_movement_id=row['through'],
             quantity=row['issued'] - row['returned'],
             line_amount=(row['issued'] - row['returned']) * row['line__unit_price'])
        for row in settlement_sources(visit)
    ]


def saved_charges(version):
    return list(version.medication_lines.values('quote_line_id', 'through_movement_id', 'quantity', 'line_amount'))


def save_charges(draft, charges):
    MedicationCharge.objects.bulk_create([MedicationCharge(record_version=draft, **row) for row in charges])


def charge_projection(version):
    return list(version.medication_lines.values(
        'quantity', 'line_amount', name_snapshot=F('quote_line__name_snapshot'),
        unit_snapshot=F('quote_line__unit_snapshot'), unit_price=F('quote_line__unit_price'),
    ))


def preview_charges(rows):
    lines = PharmacyQuoteLine.objects.in_bulk(row['quote_line_id'] for row in rows)
    return [
        dict(row, name_snapshot=lines[row['quote_line_id']].name_snapshot,
             unit_snapshot=lines[row['quote_line_id']].unit_snapshot,
             unit_price=lines[row['quote_line_id']].unit_price)
        for row in rows
    ]
