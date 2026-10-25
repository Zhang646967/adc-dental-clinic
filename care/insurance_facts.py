"""Care-owned read contract: published actual charges, never treatment plans."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from zoneinfo import ZoneInfo
from adc_core.rules import RuleError


@dataclass(frozen=True)
class InsuranceCharge:
    id: int
    line_no: int
    treatment_type_id: int
    name: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


@dataclass(frozen=True)
class InsuranceBill:
    invoice_id: int
    invoice_no: str
    record_version_id: int
    clinic_id: int
    patient_id: int
    service_on: date
    total: Decimal
    lines: tuple[InsuranceCharge, ...]


def insurance_bill(invoice):
    """Internal contract; caller authorizes the exact invoice and snapshot."""
    visit, version = invoice.visit, invoice.current_record_version
    if visit.status != 'COMPLETED' or version.state != 'PUBLISHED' or version.outcome != 'TREATED' or not visit.attended_at:
        raise RuleError('医保费用只能来自实际已接诊、治疗完成的当前发布账单。')
    rows = tuple(InsuranceCharge(r.pk, r.line_no, r.treatment_type_id, r.name_snapshot, r.unit_snapshot,
        r.quantity, r.unit_price, r.line_amount) for r in version.treatment_lines.order_by('line_no'))
    if not rows or version.total_amount <= 0 or sum(r.amount for r in rows) != version.total_amount:
        raise RuleError('原实际收费行与账单总额须一致且大于零；不能另造申报费用。')
    return InsuranceBill(invoice.pk, invoice.invoice_no, version.pk, visit.clinic_id, visit.patient_id,
        timezone.localdate(visit.attended_at, ZoneInfo(settings.TIME_ZONE)), version.total_amount, rows)


def lock_insurance_invoice(invoice):
    """Shared slot/patient/Visit/Invoice order; caller owns financial authority."""
    from scheduling.coordination import lock_slots
    from scheduling.models import Visit
    from patients.models import Patient
    from care.models import Invoice
    lock_slots([invoice.visit.availability_slot_id])
    Patient.objects.select_for_update().get(pk=invoice.visit.patient_id)
    Visit.objects.select_for_update().get(pk=invoice.visit_id)
    return Invoice.objects.select_for_update().get(pk=invoice.pk)
