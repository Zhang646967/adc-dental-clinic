"""Patient-visible facts from the existing visit, settlement and recall records."""
from django.shortcuts import get_object_or_404

from adc_core.snapshots import reporting_snapshot
from care.checkout import checkout_facts
from care.medication_charges import charge_projection
from clinical.return_visits import patient_sources
from clinical.plan_models import PerformedProcedure
from portal.policies import patient_access
from scheduling.models import Visit


def _published_care(invoice):
    record = invoice.current_record_version
    actual = list(PerformedProcedure.objects.filter(encounter__visit_id=invoice.visit_id, state='ACTIVE')
        .order_by('pk').values('charge_line__line_no', 'charge_snapshot', 'quantity', 'charge_mode'))
    source_lines = {row['charge_line__line_no'] for row in actual}
    # Line numbers retain the structured execution link through invoice revisions.
    treatments = [dict(name=row['charge_snapshot']['name'], unit=row['charge_snapshot']['unit'],
        quantity=row['quantity'], kind='NO_CHARGE_STAGE' if row['charge_mode'] == 'NO_CHARGE' else 'CHARGED')
        for row in actual]
    treatments.extend(dict(name=row['name_snapshot'], unit=row['unit_snapshot'], quantity=row['quantity'], kind='CHARGED')
        for row in record.treatment_lines.values('line_no', 'name_snapshot', 'unit_snapshot', 'quantity')
        if row['line_no'] not in source_lines)
    medications = [
        dict(name=row['name_snapshot'], unit=row['unit_snapshot'], net_quantity=row['quantity'],
            amount=row['line_amount'])
        for row in charge_projection(record)
    ]
    return dict(outcome=record.outcome, outcome_label=record.get_outcome_display(), treatments=treatments,
        medications=medications)


def visit_review(visit, *, actor, now):
    with reporting_snapshot():
        access = patient_access(actor)
        current = get_object_or_404(access.scope(Visit.objects.select_related('clinic__public_directory')), pk=visit.pk)
        summary = dict(attended_at=current.attended_at, completed_at=None, settlement_state=None,
            care=None, settlement=None, followups=[], return_sources=[])
        if access.delegated:
            return summary
        facts, invoice = checkout_facts(current, now, patient_actor=actor)
        summary.update(facts, completed_at=current.completed_at, return_sources=patient_sources(current, access),
            care=_published_care(invoice) if invoice else None)
        return summary
