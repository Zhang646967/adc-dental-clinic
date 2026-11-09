"""Same-patient advance applications, independent review and immutable amounts."""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import RoleAssignment, UserAccount
from adc_core.rules import RuleError
from care.corrections import request_line_correction, review_correction
from finance import advance_services as allocation
from finance.advance_models import AdvanceAllocation, AdvanceAllocationLine
from finance.cash_models import CashEntry
from finance.cash_selectors import cash_detail, invoice_balance, receivables
from finance.cash_services import confirm_cash_request, prepare_cash
from finance.daily_facts import day_facts
from patients.models import Patient
from scheduling.models import AvailabilitySlot
from scheduling.services import change_appointment
from tests.test_care_finance_equipment import activate
from tests.test_financial_evidence import EvidenceFixture

D = Decimal


class AdvanceAllocationFixture(EvidenceFixture):
    def setUp(self):
        self.setup_evidence()

    def receipt(self, *, amount='300.00', reference='ALLOC-ADVANCE', posted=True):
        preview = prepare_cash(actor=self.front, source_type='advance', source_id=self.p1.pk,
            kind='RECEIPT', amount=amount, occurred_on=self.today, reason='合成预收',
            payment_account_id=self.account.pk, reference=reference)
        row, _ = confirm_cash_request(actor=self.front, proposal_token=preview['proposal_token'], confirmed=True)
        return self.approve(row) if posted else row

    def other_bill(self, *, offset=1, patient=None):
        start = self.t + timedelta(hours=offset)
        visit = self.book(patient_no=(patient or self.p1).patient_no, start=start, end=start+timedelta(hours=1))
        visit = change_appointment(actor=self.front, visit_id=visit.pk, expected_version=visit.lock_version, action='check_in')
        self.review(visit)
        self.line(visit, quantity=D('2'))
        return self.finish(visit)

    def request(self, receipt, items, actor=None):
        actor = actor or self.front
        proposal = allocation.prepare_allocation(actor=actor, receipt_id=receipt.pk, items=items, basis='合成同店抵扣')
        return allocation.confirm_allocation(actor=actor, receipt_id=receipt.pk,
            proposal_token=proposal['proposal_token'], confirmed=True)[0]

    def review_preview(self, row, actor=None, decision='approve'):
        return allocation.prepare_allocation_review(actor=actor or self.fin, allocation_id=row.pk,
            decision=decision, reason='合成独立复核')['proposal_token']

    def decide(self, row, actor=None, decision='approve'):
        actor = actor or self.fin
        return allocation.confirm_allocation_review(actor=actor, allocation_id=row.pk,
            proposal_token=self.review_preview(row, actor, decision), confirmed=True)[0]


class AdvanceAllocationTests(AdvanceAllocationFixture, TransactionTestCase):
    def test_normal_web_flow_splits_300_and_keeps_one_cash_receipt(self):
        _, first = self.billed()
        second = self.other_bill()
        receipt = self.receipt()
        before = day_facts(self.a.pk, self.today)
        self.client.force_login(self.front)
        original = self.client.get(reverse('cash_detail', args=[receipt.pk]))
        url = reverse('advance_allocation_new', args=[receipt.pk])
        self.assertContains(original, url)
        response = self.client.get(url)
        self.assertContains(response, first.invoice_no)
        self.assertContains(response, second.invoice_no)
        preview = self.client.post(url, {
            'action': 'preview', 'basis': '课程合成抵扣', 'form-TOTAL_FORMS': 5, 'form-INITIAL_FORMS': 0,
            'form-0-invoice': first.pk, 'form-0-amount': '120.00',
            'form-1-invoice': second.pk, 'form-1-amount': '80.00',
        })
        self.assertContains(preview, '100.00')
        self.assertFalse(AdvanceAllocation.objects.exists())
        submission = {'action': 'confirm', 'confirmed': 'on',
                      'proposal_token': preview.context['form'].initial['proposal_token']}
        response = self.client.post(url, submission)
        self.assertEqual(response.status_code, 302)
        row = AdvanceAllocation.objects.get()
        detail = reverse('advance_allocation_detail', args=[row.pk])
        self.assertEqual(self.client.post(url, submission).url, detail)
        self.assertEqual(row.state, 'PENDING')
        self.assertEqual(invoice_balance(first)['remaining'], D('199.98'))
        self.assertEqual(allocation.available_amount(receipt), D('300.00'))

        self.client.force_login(self.fin)
        queue = self.client.get(reverse('advance_allocation_list'), {'state': 'PENDING'})
        self.assertContains(queue, detail)
        review_url = reverse('advance_allocation_review', args=[row.pk])
        preview = self.client.post(review_url, {'action': 'preview', 'decision': 'approve', 'reason': '课程合成复核'})
        self.assertContains(preview, first.invoice_no)
        self.assertContains(preview, '79.98')
        approval = {'action': 'confirm', 'confirmed': 'on',
                    'proposal_token': preview.context['form'].initial['proposal_token']}
        self.assertEqual(self.client.post(review_url, approval).url, detail)
        self.assertEqual(self.client.post(review_url, approval).url, detail)
        row.refresh_from_db()
        self.assertEqual((row.state, row.total, row.reviewed_by), ('POSTED', D('200.00'), self.fin))
        self.assertEqual(row.lines.count(), 2)
        self.assertEqual(allocation.available_amount(receipt), D('100.00'))
        self.assertEqual(cash_detail(self.fin, receipt.pk)['balance']['advance_available'], D('100.00'))
        for bill, applied, due in [(first, D('120'), D('79.98')), (second, D('80'), D('119.98'))]:
            balance = invoice_balance(bill)
            self.assertEqual((balance['net_received'], balance['advance_applied'], balance['remaining']), (0, applied, due))
        self.assertEqual(receivables(self.fin, 'due')['totals']['remaining'], D('199.96'))
        self.assertEqual(day_facts(self.a.pk, self.today), before)
        self.assertEqual(before['totals']['RECEIPT'], '300.00')
        self.assertEqual(CashEntry.objects.count(), 1)
        self.assertEqual(receipt.evidence_versions.count(), 1)
        self.client.force_login(self.pa)
        self.assertContains(self.client.get(reverse('portal_invoice', args=[first.pk])), '已抵扣预收款')
        self.assertEqual(self.client.get(detail).status_code, 403)

    def test_scope_and_input_reject_foreign_bills_pending_receipt_and_duplicate_line(self):
        _, bill = self.billed()
        other = Patient.objects.create(name='合成另一患者', date_of_birth=self.p1.date_of_birth, created_in_clinic=self.a)
        other_bill = self.other_bill(patient=other)
        receipt = self.receipt()
        with self.assertRaisesRegex(RuleError, '本店同一患者'):
            self.request(receipt, [(other_bill.pk, '20.00')])
        with self.assertRaisesRegex(RuleError, '只能填写一次'):
            self.request(receipt, [(bill.pk, '20.00'), (bill.pk, '10.00')])
        with self.assertRaisesRegex(RuleError, '当前待付金额'):
            self.request(receipt, [(bill.pk, '200.00')])
        with self.assertRaisesRegex(RuleError, '独立记账'):
            self.request(self.receipt(posted=False, reference='ALLOC-PENDING'), [(bill.pk, '10.00')])
        self.assertFalse(AdvanceAllocation.objects.exists())
        self.client.force_login(self.front2)
        self.client.post(reverse('activate_clinic'), {'clinic': self.b.pk})
        self.assertEqual(self.client.get(reverse('advance_allocation_new', args=[receipt.pk])).status_code, 404)

    def test_self_review_revoked_authority_and_rejection(self):
        _, bill = self.billed()
        receipt = self.receipt()
        row = self.request(receipt, [(bill.pk, '120.00')])
        RoleAssignment.objects.create(user=self.front, role='FINANCE', scope_kind='CHAIN')
        activate(self.front, 'FINANCE')
        with self.assertRaises(PermissionDenied):
            self.review_preview(row, self.front)
        approve = self.review_preview(row)
        RoleAssignment.objects.filter(user=self.front, role='FRONT_DESK', clinic=self.a).update(is_active=False)
        with self.assertRaisesRegex(RuleError, '授权已失效'):
            allocation.confirm_allocation_review(actor=self.fin, allocation_id=row.pk, proposal_token=approve, confirmed=True)
        self.assertEqual(self.decide(row, decision='reject').state, 'REJECTED')
        self.assertEqual(allocation.available_amount(receipt), D('300.00'))
        self.assertEqual(invoice_balance(bill)['advance_applied'], 0)

    def test_same_patient_at_another_clinic_cannot_use_this_receipt(self):
        receipt = self.receipt()
        start = self.t + timedelta(hours=5)
        slot = AvailabilitySlot.objects.create(
            clinic=self.b, dentist=self.d1, starts_at=start, ends_at=start+timedelta(hours=1))
        visit = self.book(actor=self.front2, slot_id=slot.pk, start=start, end=slot.ends_at)
        visit = change_appointment(actor=self.front2, visit_id=visit.pk, expected_version=visit.lock_version, action='check_in')
        self.review(visit)
        self.line(visit, quantity=D('2'))
        bill = self.finish(visit)
        with self.assertRaisesRegex(RuleError, '本店同一患者'):
            self.request(receipt, [(bill.pk, '120.00')])
        self.assertFalse(AdvanceAllocation.objects.exists())

    def test_posting_a_direct_receipt_invalidates_old_allocation_review(self):
        _, bill = self.billed()
        receipt = self.receipt()
        row = self.request(receipt, [(bill.pk, '60.00')])
        stale = self.review_preview(row)
        self.approve(self.cash(bill, amount='40.00'))
        with self.assertRaisesRegex(RuleError, '待付或预收余额已变化'):
            allocation.confirm_allocation_review(actor=self.fin, allocation_id=row.pk, proposal_token=stale, confirmed=True)
        self.assertEqual(self.decide(row).state, 'POSTED')
        self.assertEqual(invoice_balance(bill)['remaining'], D('99.98'))

    def test_allocation_invalidates_old_direct_cash_preview_even_if_it_still_fits(self):
        _, bill = self.billed()
        receipt = self.receipt()
        direct = self.cash_preview(bill, amount='30.00')
        self.decide(self.request(receipt, [(bill.pk, '80.00')]))
        with self.assertRaisesRegex(RuleError, '已变化'):
            confirm_cash_request(actor=self.front, proposal_token=direct['proposal_token'], confirmed=True)
        self.assertFalse(CashEntry.objects.filter(invoice=bill).exists())

    def replace_bill(self, visit, invoice, *, unit_price='70.00'):
        visit.refresh_from_db()
        line = invoice.current_record_version.treatment_lines.get()
        req = request_line_correction(actor=self.doctor, visit_id=visit.pk, expected_version=visit.lock_version,
            line_id=line.pk, quantity=D('1'), unit_price=D(unit_price), reason='合成实际收费更正')
        return review_correction(actor=self.fin, request_id=req.pk, decision='approve', reason='合成独立复核更正')

    def test_replaced_bill_keeps_posted_history_flags_excess_and_blocks_old_request(self):
        visit, bill = self.billed()
        receipt = self.receipt()
        retained = self.decide(self.request(receipt, [(bill.pk, '120.00')]))
        later = self.request(receipt, [(bill.pk, '30.00')])
        token = self.review_preview(later)
        original = retained.lines.get().record_version_id
        corrected = self.replace_bill(visit, bill)
        self.assertNotEqual(original, corrected.current_record_version_id)
        with self.assertRaisesRegex(RuleError, '账单已发布新版本'):
            allocation.confirm_allocation_review(actor=self.fin, allocation_id=later.pk, proposal_token=token, confirmed=True)
        self.assertEqual(self.decide(later, decision='reject').state, 'REJECTED')
        balance = invoice_balance(corrected)
        self.assertEqual((balance['advance_applied'], balance['advance_excess'], balance['refund_due']), (D('120'), D('50'), 0))
        self.assertEqual(receivables(self.fin, 'advance-excess')['rows'][0].pk, bill.pk)
        self.assertEqual(retained.lines.get().record_version_id, original)

    def compete(self, rows):
        reviewer = UserAccount.objects.create_user(username='allocation_fin_second', password='synthetic-test-only')
        RoleAssignment.objects.create(user=reviewer, role='FINANCE', scope_kind='CHAIN')
        activate(reviewer, 'FINANCE')
        people = [self.fin, reviewer]
        tokens = [self.review_preview(row, actor) for row, actor in zip(rows, people)]

        def complete(index):
            try:
                allocation.confirm_allocation_review(actor=self.actor_copy(people[index]), allocation_id=rows[index].pk,
                    proposal_token=tokens[index], confirmed=True)
            except RuleError as error:
                return str(error)
            return 'posted'

        outcomes = self.race(complete)
        self.assertEqual(outcomes.count('posted'), 1)
        self.assertEqual(AdvanceAllocation.objects.filter(state='POSTED').count(), 1)
        return next(result for result in outcomes if result != 'posted')

    def test_concurrent_allocations_do_not_exceed_one_receipt(self):
        _, first = self.billed()
        second = self.other_bill()
        receipt = self.receipt()
        activate(self.front2, 'FRONT_DESK', self.a)
        rows = [self.request(receipt, [(first.pk, '160.00')]),
                self.request(receipt, [(second.pk, '160.00')], self.front2)]
        self.assertIn('超过原预收款', self.compete(rows))
        self.assertEqual(allocation.available_amount(receipt), D('140.00'))

    def test_concurrent_receipts_do_not_overapply_one_invoice(self):
        _, bill = self.billed()
        activate(self.front2, 'FRONT_DESK', self.a)
        first = self.request(self.receipt(), [(bill.pk, '130.00')])
        second = self.request(self.receipt(reference='ALLOC-OTHER'), [(bill.pk, '130.00')], self.front2)
        self.assertIn('超过账单当前待付', self.compete([first, second]))
        self.assertEqual(invoice_balance(bill)['remaining'], D('69.98'))

    def test_database_requires_complete_batch_and_preserves_history(self):
        _, bill = self.billed()
        receipt = self.receipt()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AdvanceAllocation.objects.create(receipt=receipt, prepared_by=self.front,
                total='100.00', available_at_request='300.00', basis='合成缺少明细')
        self.assertFalse(AdvanceAllocation.objects.exists())
        row = self.request(receipt, [(bill.pk, '150.00')])
        with self.assertRaises(IntegrityError), transaction.atomic():
            AdvanceAllocationLine.objects.filter(allocation=row).update(amount='1.00')
        with self.assertRaises(IntegrityError), transaction.atomic():
            AdvanceAllocation.objects.filter(pk=row.pk).update(state='POSTED', reviewed_by=self.front,
                reviewed_at=timezone.now(), review_reason='合成违规自审', review_operation_id=uuid4())
        self.decide(row)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AdvanceAllocation.objects.filter(pk=row.pk).update(basis='重写已确认历史')
        self.assertEqual(allocation.available_amount(receipt), D('150.00'))
