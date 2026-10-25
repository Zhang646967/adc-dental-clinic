"""Authorized source quote. All identifiers and caps are reread on confirmation."""
import hashlib
import json
from care.models import Invoice, CorrectionRequest
from care.insurance_facts import insurance_bill
from adc_core.rules import RuleError
from insurance.models import ClinicArrangement, FeeMapping, PolicyCatalogue
from insurance.policies import scope
from insurance.selectors import eligibility_at, mapping_blocker
from insurance.settlement_rules import source_fund_limit


def digest(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def authorized_invoice(actor, invoice_id):
    binding = scope(actor, ('FRONT_DESK', 'FINANCE'))
    invoices = Invoice.objects.select_related('visit__clinic', 'current_record_version').only(
        'id', 'invoice_no', 'visit__id', 'visit__clinic_id', 'visit__patient_id', 'visit__status',
        'visit__attended_at', 'visit__clinic__id', 'visit__clinic__is_active',
        'current_record_version__id', 'current_record_version__state', 'current_record_version__outcome',
        'current_record_version__total_amount')
    if binding['role'] == 'FRONT_DESK':
        invoices = invoices.filter(visit__clinic_id=binding['clinic'])
    return invoices.get(pk=invoice_id)


def quote_source(actor, invoice_id, *, lock=False):
    invoice = authorized_invoice(actor, invoice_id)
    if lock:
        from care.insurance_facts import lock_insurance_invoice
        invoice = lock_insurance_invoice(invoice)
    bill = insurance_bill(invoice)
    if CorrectionRequest.objects.filter(visit_id=invoice.visit_id, status='OPEN').exists():
        raise RuleError('账单仍有待审核费用更正，请先完成原更正再办理医保结算。')
    if lock:
        from registry.models import Clinic
        Clinic.objects.select_for_update().get(pk=bill.clinic_id)
    if not invoice.visit.clinic.is_active:
        raise RuleError('门店已停用；保留原账及请求，不能新建医保结算。')
    arrangement = ClinicArrangement.objects.filter(clinic_id=bill.clinic_id, state='CONFIRMED',
        catalogue__state='CONFIRMED', starts_on__lte=bill.service_on, ends_on__gte=bill.service_on).select_related('catalogue').first()
    if arrangement is None:
        raise RuleError('实际接诊日期没有已核对的本店模拟安排，请先核对日期和来源。')
    if lock:
        # Preparation commands use Clinic -> Catalogue -> subject -> fee.
        PolicyCatalogue.objects.select_for_update().get(pk=arrangement.catalogue_id)
        arrangement = ClinicArrangement.objects.select_for_update().select_related('catalogue').get(pk=arrangement.pk)
        if arrangement.state != 'CONFIRMED' or arrangement.catalogue.state != 'CONFIRMED':
            raise RuleError('目录或门店安排已变化，请重新预览。')
    eligibility, blocker = eligibility_at(bill.clinic_id, bill.patient_id, bill.service_on)
    if blocker:
        raise RuleError(blocker + '；未取得可核对待遇，不能据此模拟清偿。')
    from finance.cash_selectors import invoice_cash_facts
    cash = invoice_cash_facts(invoice.pk)
    if cash['pending']:
        raise RuleError('本账单仍有收退款待审，请先完成原财务办理再核对医保分担。')
    mapping_rows = FeeMapping.objects.filter(clinic_id=bill.clinic_id,
        state='CONFIRMED', policy_item__catalogue=arrangement.catalogue,
        treatment_type_id__in=[r.treatment_type_id for r in bill.lines]).order_by('pk')
    if lock:
        list(mapping_rows.select_for_update())
        from registry.models import TreatmentType
        list(TreatmentType.objects.select_for_update().filter(pk__in=[r.treatment_type_id for r in bill.lines]).order_by('pk'))
    mappings = {m.treatment_type_id: m for m in mapping_rows.select_related('policy_item__catalogue', 'treatment_type')}
    rows = []
    for line in bill.lines:
        mapping = mappings.get(line.treatment_type_id)
        exception = mapping_blocker(mapping) if mapping else '尚无本店已核对适配，保留自付例外'
        if mapping and not exception and (line.unit != mapping.fee_snapshot['unit'] or line.name != mapping.fee_snapshot['name']):
            exception = '账单保留的项目含义或单位与现有适配不同，须另行核对'
        usable = mapping is not None and not exception
        item = mapping.policy_item if mapping else None
        limit = source_fund_limit(line.amount, payment_class=item.payment_class if item else 'UNKNOWN',
            pre_self_pay_percent=item.pre_self_pay_percent if item else None, mapping_usable=usable)
        rows.append(dict(treatment_record=line.id, line_no=line.line_no, treatment_type=line.treatment_type_id,
            name=line.name, unit=line.unit, quantity=str(line.quantity), unit_price=str(line.unit_price), amount=str(line.amount),
            mapping=mapping.pk if usable else None, policy_code=item.code if item else None,
            policy_unit=item.unit if item else None, policy_quantity=str(line.quantity*mapping.policy_units_per_fee) if usable else None,
            payment_class=item.payment_class if item else 'UNKNOWN',
            pre_self_pay_percent=str(item.pre_self_pay_percent) if item and item.pre_self_pay_percent is not None else None,
            fund_limit=str(limit), mapping_usable=usable, exception=exception))
    snapshot = dict(invoice=bill.invoice_id, invoice_no=bill.invoice_no, record_version=bill.record_version_id,
        clinic=bill.clinic_id, patient=bill.patient_id, service_on=str(bill.service_on), currency='CNY',
        total=str(bill.total), arrangement=arrangement.pk, catalogue=arrangement.catalogue_id,
        catalogue_digest=arrangement.catalogue.source_digest, eligibility=eligibility.pk,
        insured_region=eligibility.insured_region, scheme=eligibility.scheme, cash_cursor=cash['cursor'], lines=rows)
    return dict(invoice=invoice, arrangement=arrangement, eligibility=eligibility, snapshot=snapshot, digest=digest(snapshot))
