"""Patient advances use the cash ledger, independent review and one channel fact."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import RoleAssignment
from adc_core.rules import RuleError
from care.models import AuditEvent
from finance.cash_models import CashEntry
from finance.cash_selectors import cash_listing, invoice_balance
from finance.cash_services import confirm_cash_request, confirm_cash_review, prepare_cash, prepare_review
from finance.daily_facts import advance_receipts_on_day, day_facts
from finance.daily_services import confirm_close, confirm_close_review, prepare_close, prepare_close_review
from finance.fund_models import StatementUse
from finance.reconciliation_selectors import candidates
from patients.models import Patient
from tests.test_care_finance_equipment import activate
from tests.test_financial_evidence import EvidenceFixture


class PatientAdvanceTests(EvidenceFixture, TransactionTestCase):
    def setUp(self):
        self.setup_evidence()

    def preview(self, **overrides):
        values = dict(actor=self.front, source_type='advance', source_id=self.p1.pk,
                      kind='RECEIPT', amount='300.00', occurred_on=self.today,
                      reason='课程合成预收', payment_account_id=self.account.pk, reference='ADVANCE-1')
        values.update(overrides)
        return prepare_cash(**values)

    def submit(self, **overrides):
        token = self.preview(**overrides)['proposal_token']
        return confirm_cash_request(actor=overrides.get('actor', self.front), proposal_token=token, confirmed=True)[0]

    def test_http_front_desk_and_independent_finance_flow(self):
        _, invoice = self.billed()
        original_bill = invoice_balance(invoice)
        url = reverse('cash_advance_request', args=[self.p1.pk])
        self.client.force_login(self.front)
        self.assertContains(self.client.get(reverse('patient_detail', args=[self.p1.pk])), url)
        form = self.client.get(url).context['form']
        self.assertNotIn('kind', form.fields)
        preview = self.client.post(url, dict(action='preview', amount='300.00',
            occurred_on=self.today.isoformat(), reason='课程合成预收',
            payment_account_id=self.account.pk, reference='ADVANCE-1'))
        self.assertContains(preview, self.p1.name)
        self.assertContains(preview, self.a.name)
        self.assertFalse(CashEntry.objects.exists())
        submission = dict(action='confirm', proposal_token=preview.context['form'].initial['proposal_token'], confirmed='on')
        result = self.client.post(url, submission)
        self.assertEqual(result.status_code, 302)
        entry = CashEntry.objects.get()
        detail = reverse('cash_detail', args=[entry.pk])
        self.assertEqual(self.client.post(url, submission).url, detail)
        self.assertContains(self.client.get(detail), '患者预收款')
        self.assertEqual(entry.state, 'PENDING')
        self.assertEqual(day_facts(self.a.pk, self.today)['totals']['RECEIPT'], '0.00')
        self.assertEqual(entry.evidence_versions.get().state, 'PENDING')
        self.assertEqual(invoice_balance(invoice), original_bill)

        self.client.force_login(self.fin)
        queue = self.client.get(reverse('cash_list'), {'kind': 'ADVANCE', 'state': 'PENDING'})
        self.assertEqual([row.pk for row in queue.context['rows']], [entry.pk])
        review_url = reverse('cash_review', args=[entry.pk])
        review = self.client.post(review_url, dict(action='preview', decision='approve', reason='课程合成独立复核'))
        self.assertContains(review, 'ADVANCE-1')
        self.assertContains(review, 'BANK-A')
        approval = dict(action='confirm', proposal_token=review.context['form'].initial['proposal_token'], confirmed='on')
        self.assertEqual(self.client.post(review_url, approval).url, detail)
        self.assertEqual(self.client.post(review_url, approval).url, detail)
        entry.refresh_from_db()
        self.assertEqual((entry.state, entry.prepared_by, entry.reviewed_by), ('POSTED', self.front, self.fin))
        self.assertEqual(entry.evidence_versions.get().state, 'APPROVED')
        self.assertEqual(day_facts(self.a.pk, self.today)['totals']['RECEIPT'], '300.00')
        self.assertEqual(advance_receipts_on_day(self.a.pk, self.today), Decimal('300.00'))
        self.assertEqual(self.client.get(detail).context['balance']['advance_received'], Decimal('300.00'))
        self.assertEqual(invoice_balance(invoice), original_bill)
        self.assertEqual(list(AuditEvent.objects.filter(subject_type='cashentry', subject_key=str(entry.pk))
                         .order_by('pk').values_list('event_type', flat=True)), ['CASH_REQUESTED', 'CASH_POSTED'])
        daily = prepare_close(actor=self.manager, business_date=self.today,
            declared={'RECEIPT': '300.00', 'REFUND': '0.00', 'EQUIPMENT_EXPENSE': '0.00', 'EXPENSE_REVERSAL': '0.00'},
            evidence='课程合成日结凭据', reason='预收实收列入收款')
        close, _ = confirm_close(actor=self.manager, proposal_token=daily['proposal_token'], confirmed=True)
        preview = prepare_close_review(actor=self.fin, close_id=close.pk, decision='approve', reason='独立核对日结')
        close, _ = confirm_close_review(actor=self.fin, proposal_token=preview['proposal_token'], confirmed=True)
        self.assertEqual(close.state, 'APPROVED')
        self.assertEqual(close.snapshot['totals']['RECEIPT'], '300.00')

    def test_clinic_roles_and_hq_aggregate(self):
        with self.assertRaises(RuleError):
            self.preview(source_id=self.p2.pk)
        with self.assertRaises(RuleError):
            self.preview(actor=self.front2, source_id=self.p2.pk)
        entry = self.approve(self.submit())
        detail = reverse('cash_detail', args=[entry.pk])
        self.client.force_login(self.front2)
        self.client.post(reverse('activate_clinic'), {'clinic': self.b.pk})
        self.assertEqual(self.client.get(reverse('cash_advance_request', args=[self.p1.pk])).status_code, 404)
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(self.client.get(reverse('cash_advance_request', args=[self.p1.pk])).status_code, 403)
        self.client.force_login(self.pa)
        self.assertEqual(self.client.get(detail).status_code, 403)
        summary = cash_listing(self.hq, kind='ADVANCE')
        self.assertEqual(summary['totals']['advance_receipts'], Decimal('300.00'))
        self.assertEqual(summary['rows'], [])
        with self.assertRaises(PermissionDenied):
            cash_listing(self.hq, advance=str(self.p1.pk))

    def test_self_approval_and_later_deactivation_leave_a_rejectable_request(self):
        entry = self.submit()
        RoleAssignment.objects.create(user=self.front, role='FINANCE', scope_kind='CHAIN')
        activate(self.front, 'FINANCE')
        with self.assertRaisesRegex(RuleError, '必须为不同账号'):
            self.approve(entry, actor=self.front)
        review = prepare_review(actor=self.fin, entry_id=entry.pk, decision='approve', reason='合成独立复核')
        Patient.objects.filter(pk=self.p1.pk).update(is_active=False)
        with self.assertRaisesRegex(RuleError, '已停用'):
            confirm_cash_review(actor=self.fin, proposal_token=review['proposal_token'], confirmed=True)
        self.assertEqual(self.approve(entry, 'reject').state, 'REJECTED')
        self.assertEqual(entry.evidence_versions.get().state, 'REJECTED')
        self.assertEqual(advance_receipts_on_day(self.a.pk, self.today), 0)

    def test_only_one_channel_use_and_no_second_receipt(self):
        entry = self.approve(self.submit())
        line = self.imported(self.raw(reference='ADVANCE-1', amount='300.00'))
        self.assertEqual([row.cash_entry_id for row in candidates(self.manager, line)], [entry.pk])
        match = self.match_review(self.proposed(entry, line))
        self.assertEqual(match.state, 'CONFIRMED')
        self.assertEqual(StatementUse.objects.filter(line=line, state='ACTIVE').count(), 1)
        self.assertEqual(candidates(self.manager, line), [])
        _, invoice = self.billed()
        with self.assertRaisesRegex(RuleError, '此渠道凭据已用于'):
            self.cash_preview(invoice, payment_account_id=self.account.pk, reference='ADVANCE-1')
        with self.assertRaisesRegex(RuleError, '此渠道凭据已用于'):
            self.preview()
        self.assertEqual(CashEntry.objects.count(), 1)

    def test_rejected_reference_can_be_resubmitted_but_an_existing_invoice_reference_cannot(self):
        self.approve(self.submit(), 'reject')
        self.assertEqual(self.submit().state, 'PENDING')
        _, invoice = self.billed()
        self.cash(invoice, payment_account_id=self.account.pk, reference='INVOICE-1')
        with self.assertRaisesRegex(RuleError, '此渠道凭据已用于'):
            self.preview(reference='INVOICE-1')

    def test_distinct_patients_and_business_dates_compete_for_one_reference(self):
        # Different staff accounts, patients and business dates share only the channel.
        local = Patient.objects.create(name='课程合成另一患者', date_of_birth=self.p1.date_of_birth,
                                       created_in_clinic=self.a)
        activate(self.front2, 'FRONT_DESK', self.a)
        actors = [self.front, self.front2]
        previews = [self.preview(), self.preview(actor=self.front2, source_id=local.pk,
                                                 occurred_on=self.today-timedelta(days=1))]

        def confirm(index):
            try:
                confirm_cash_request(actor=self.actor_copy(actors[index]),
                                     proposal_token=previews[index]['proposal_token'], confirmed=True)
            except RuleError as error:
                return str(error)
            return 'submitted'

        result = self.race(confirm)
        self.assertEqual(result.count('submitted'), 1)
        self.assertIn('此渠道凭据已用于', next(item for item in result if item != 'submitted'))
        self.assertEqual(CashEntry.objects.count(), 1)
        self.assertEqual(CashEntry.objects.get().evidence_versions.count(), 1)

    def test_sql_rejects_wrong_clinic_and_posting_without_evidence(self):
        common = dict(clinic=self.a, kind='RECEIPT', amount='300.00', occurred_on=self.today,
                      reason='课程合成数据库检查', prepared_by=self.front)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CashEntry.objects.create(advance_patient=self.p2, **common)
        entry = CashEntry.objects.create(advance_patient=self.p1, **common)
        with self.assertRaisesRegex(RuleError, '原始预收凭据缺失'):
            self.approve(entry)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CashEntry.objects.filter(pk=entry.pk).update(state='POSTED', lock_version=1, reviewed_by=self.fin,
                reviewed_at=timezone.now(), review_reason='合成独立核对')
        self.assertEqual(day_facts(self.a.pk, self.today)['totals']['RECEIPT'], '0.00')
