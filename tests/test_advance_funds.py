"""Advance dispositions through the normal website, commands and PostgreSQL."""
from datetime import timedelta
from decimal import Decimal as D
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import RoleAssignment, UserAccount
from adc_core.rules import RuleError
from care.corrections import request_line_correction, review_correction
from finance import advance_reversal_services as reversals
from finance import advance_services as allocations
from finance.advance_models import AdvanceAllocation, AdvanceAllocationReversal
from finance.cash_evidence_services import confirm_evidence, prepare_evidence
from finance.cash_models import CashEntry
from finance.cash_selectors import invoice_balance, receivables
from finance.cash_services import confirm_cash_request, confirm_cash_review, prepare_cash, prepare_review
from finance.daily_facts import advance_receipts_on_day, advance_refunds_on_day, day_facts
from finance.payment_account_services import confirm_account, prepare_account
from portal import relationships as rel
from portal.models import PatientAccess
from tests.test_advance_allocation import AdvanceAllocationFixture
from tests.test_care_finance_equipment import activate


class AdvanceFundsTests(AdvanceAllocationFixture, TransactionTestCase):
    def refund_preview(self, receipt, amount='50.00', *, reference='REFUND-SYNTH-01', actor=None, **extra):
        values = dict(actor=actor or self.front, source_type='advance_refund', source_id=receipt.pk,
                      kind='REFUND', amount=amount, occurred_on=self.today, reason='PRIVATE_SYNTH_BASIS',
                      reference=reference)
        return prepare_cash(**dict(values, **extra))

    def refund(self, receipt, amount='50.00', **extra):
        p = self.refund_preview(receipt, amount, **extra)
        return confirm_cash_request(actor=extra.get('actor', self.front), proposal_token=p['proposal_token'],
                                    confirmed=True)[0]

    def reversal(self, line):
        p = reversals.prepare_reversal(actor=self.front, line_id=line.pk, basis='PRIVATE_SYNTH_REVERSAL')
        return reversals.confirm_reversal(actor=self.front, line_id=line.pk,
                                          proposal_token=p['proposal_token'], confirmed=True)[0]

    def review_reversal(self, row, decision='approve', actor=None):
        actor = actor or self.fin
        p = reversals.prepare_review(actor=actor, reversal_id=row.pk, decision=decision, reason='合成独立复核')
        return reversals.confirm_review(actor=actor, reversal_id=row.pk,
                                        proposal_token=p['proposal_token'], confirmed=True)[0]

    def make_account(self, code):
        p = prepare_account(actor=self.fin, clinic_id=self.a.pk, code=code, method='BANK_TRANSFER')
        return confirm_account(actor=self.fin, proposal_token=p['proposal_token'], confirmed=True)[0]

    def confirm_web(self, url, preview, expected_url=None):
        self.assertEqual(preview.status_code, 200)
        token = preview.context['form'].initial['proposal_token']
        request = {'action': 'confirm', 'confirmed': 'on', 'proposal_token': token}
        response = self.client.post(url, request)
        self.assertEqual(response.status_code, 302, response.content)
        if expected_url:
            self.assertEqual(response.url, expected_url)
        self.assertEqual(self.client.post(url, request).url, response.url)
        return response.url

    def test_web_reverses_one_line_then_refunds_and_matches_patient_totals(self):
        _, first = self.billed()
        second = self.other_bill()
        receipt = self.receipt()
        posted = self.decide(self.request(receipt, [(first.pk, '120.00'), (second.pk, '80.00')]))
        line = posted.lines.get(invoice=second)
        base_day = day_facts(self.a.pk, self.today)
        self.assertEqual(allocations.available_amount(receipt), D('100'))
        self.client.force_login(self.front)
        request_url = reverse('advance_reverse_line', args=[line.pk])
        self.assertContains(self.client.get(reverse('advance_allocation_detail', args=[posted.pk])), request_url)
        detail_url = self.confirm_web(request_url, self.client.post(request_url, {'basis':'PRIVATE_SYNTH_REVERSAL'}))
        row = AdvanceAllocationReversal.objects.get()
        self.assertEqual(row.state, 'PENDING')
        self.assertEqual(allocations.available_amount(receipt), D('100'))
        self.client.force_login(self.fin)
        self.assertContains(self.client.get(reverse('advance_reversal_list'), {'state':'PENDING'}), detail_url)
        review_url = reverse('advance_reversal_review', args=[row.pk])
        review = self.client.post(review_url, {'decision':'approve', 'reason':'核对原分配金额'})
        self.assertContains(review, '180.00')
        self.confirm_web(review_url, review, detail_url)
        self.assertEqual(allocations.available_amount(receipt), D('180'))
        self.assertEqual(day_facts(self.a.pk, self.today), base_day)
        self.assertEqual(invoice_balance(first)['remaining'], D('79.98'))
        self.assertEqual(invoice_balance(second)['remaining'], D('199.98'))

        self.client.force_login(self.front)
        request_url = reverse('cash_advance_refund', args=[receipt.pk])
        self.assertContains(self.client.get(reverse('cash_detail', args=[receipt.pk])), request_url)
        refund_preview = self.client.post(request_url, {'occurred_on':self.today, 'amount':'50.00',
            'reference':'REFUND-SYNTH-01', 'reason':'PRIVATE_SYNTH_BASIS'})
        self.assertContains(refund_preview, '130.00')
        refund_url = self.confirm_web(request_url, refund_preview)
        refund = CashEntry.objects.get(kind='REFUND')
        self.assertEqual((refund.reversal_of_id, refund.state), (receipt.pk, 'PENDING'))
        self.assertEqual(allocations.available_amount(receipt), D('180'))
        self.client.force_login(self.fin)
        review_url = reverse('cash_review', args=[refund.pk])
        self.confirm_web(review_url, self.client.post(review_url, {'decision':'approve','reason':'核对本笔原渠道退款'}), refund_url)
        self.assertEqual(allocations.available_amount(receipt), D('130'))
        self.assertEqual(day_facts(self.a.pk, self.today)['totals']['REFUND'], '50.00')
        self.assertEqual(advance_receipts_on_day(self.a.pk, self.today), D('300'))
        self.assertEqual(advance_refunds_on_day(self.a.pk, self.today), D('50'))
        self.assertEqual(CashEntry.objects.count(), 2)
        self.assertEqual(AdvanceAllocation.objects.get().total, D('200'))
        self.assertEqual(posted.lines.count(), 2)

        self.client.force_login(self.pa)
        website = self.client.get(reverse('portal_funds'))
        mini = self.client.get(reverse('mini_funds'))
        self.assertEqual(mini.status_code, 200, mini.content)
        data = mini.json()['data']
        self.assertEqual([r['event'] for r in data['entries']], ['REFUND', 'REVERSAL', 'ALLOCATION', 'ALLOCATION', 'RECEIPT'])
        self.assertEqual((data['selected']['received'], data['selected']['applied'], data['selected']['refunded'],
                          data['selected']['available']), ('300.00','120.00','50.00','130.00'))
        self.assertEqual(website.context['selected']['available'], D('130'))
        self.assertContains(website, '原渠道退款')
        self.assertNotContains(website, 'PRIVATE_SYNTH')
        self.assertNotIn('REFUND-SYNTH', mini.content.decode())
        self.assertEqual(self.client.get(reverse('mini_invoice', args=[second.pk])).json()['data']['cash_balance']['advance_applied'], '0.00')

    def test_refund_channel_date_reference_and_multiple_partial_refunds(self):
        receipt = self.receipt()
        account = self.make_account('BANK-OTHER')
        for parameters, message in [
            ({'payment_account_id':account.pk}, '原预收款当前核实'),
            ({'reference':'ALLOC-ADVANCE'}, '独立凭据编号'),
            ({'occurred_on':self.today-timedelta(days=1)}, '不能早于原预收'),
            ({'amount':'300.01'}, '超过本笔预收可用额'),
        ]:
            with self.assertRaisesRegex(RuleError, message):
                self.refund_preview(receipt, **parameters)
        first = self.approve(self.refund(receipt))
        with self.assertRaisesRegex(RuleError, '独立凭据编号'):
            self.refund(receipt)
        second = self.approve(self.refund(receipt, '20.00', reference='REFUND-SYNTH-02'))
        self.assertEqual(first.evidence_versions.get().account, self.account)
        self.assertEqual(second.reversal_of_id, receipt.pk)
        self.assertEqual(allocations.available_amount(receipt), D('230'))
        with self.assertRaisesRegex(RuleError, '保留该笔退款原有'):
            prepare_evidence(actor=self.front, entry_id=first.pk, payment_account_id=account.pk,
                             reference='REFUND-CORRECTION', reason='合成补证')
        with self.assertRaisesRegex(RuleError, '独立凭据编号'):
            self.receipt(reference='REFUND-SYNTH-02')
        line = self.imported(self.raw(direction='OUT', amount='20.00', reference='REFUND-SYNTH-02'))
        self.assertEqual(self.match_review(self.proposed(second, line)).state, 'CONFIRMED')

    def test_changed_original_channel_requires_new_request_and_refusal_has_no_effect(self):
        receipt = self.receipt()
        pending = self.refund(receipt)
        preview = prepare_review(actor=self.fin, entry_id=pending.pk, decision='approve', reason='拟核对')
        account = self.make_account('BANK-CORRECTED')
        evidence = prepare_evidence(actor=self.front, entry_id=receipt.pk, payment_account_id=account.pk,
                                    reference='CORRECTED-RECEIPT', reason='合成原渠道更正')
        row = confirm_evidence(actor=self.front, proposal_token=evidence['proposal_token'],
                               confirmed=True, expected_entry_id=receipt.pk)[0]
        self.evidence_review(row)
        with self.assertRaisesRegex(RuleError, '状态已变化'):
            confirm_cash_review(actor=self.fin, proposal_token=preview['proposal_token'], confirmed=True)
        self.client.force_login(self.fin)
        url = reverse('cash_review', args=[pending.pk])
        self.assertContains(self.client.get(url), '当前核实的渠道账户')
        self.confirm_web(url, self.client.post(url, {'decision':'reject','reason':'原渠道已更正'}))
        self.assertEqual(allocations.available_amount(receipt), D('300'))
        new = self.approve(self.refund(receipt))
        self.assertEqual(new.evidence_versions.get().account_id, account.pk)

    def test_revoked_or_self_reviewer_cannot_release_applied_money(self):
        _, bill = self.billed()
        receipt = self.receipt()
        allocation = self.decide(self.request(receipt, [(bill.pk,'80.00')]))
        row = self.reversal(allocation.lines.get())
        RoleAssignment.objects.create(user=self.front, role='FINANCE', scope_kind='CHAIN')
        activate(self.front, 'FINANCE')
        with self.assertRaises(PermissionDenied):
            self.review_reversal(row, actor=self.front)
        RoleAssignment.objects.filter(user=self.front, role='FRONT_DESK').update(is_active=False)
        with self.assertRaisesRegex(RuleError, '原申请人'):
            self.review_reversal(row)
        self.assertEqual(self.review_reversal(row, decision='reject').state, 'REJECTED')
        self.assertEqual(allocations.available_amount(receipt), D('220'))

    def test_rollback_of_application_amount_does_not_validate_an_old_refund_preview(self):
        _, bill = self.billed()
        receipt = self.receipt()
        stale = self.refund_preview(receipt)
        old_invoice_preview = self.cash_preview(bill, amount='50.00')
        posted = self.decide(self.request(receipt, [(bill.pk,'80.00')]))
        line = posted.lines.get()
        self.review_reversal(self.reversal(line))
        with self.assertRaisesRegex(RuleError, '已有待审或已记账'):
            self.reversal(line)
        self.assertEqual(allocations.available_amount(receipt), D('300'))
        with self.assertRaisesRegex(RuleError, '记账申请已变化'):
            confirm_cash_request(actor=self.front, proposal_token=stale['proposal_token'], confirmed=True)
        with self.assertRaisesRegex(RuleError, '记账申请已变化'):
            confirm_cash_request(actor=self.front, proposal_token=old_invoice_preview['proposal_token'], confirmed=True)
        self.decide(self.request(receipt, [(bill.pk,'150.00')]))
        self.assertEqual(allocations.available_amount(receipt), D('150'))
        self.assertEqual(receivables(self.fin, 'due')['rows'][0].remaining, D('49.98'))

    def test_reversal_after_new_invoice_version_releases_original_amount_and_excess(self):
        visit, bill = self.billed()
        receipt = self.receipt()
        original = self.decide(self.request(receipt, [(bill.pk,'120.00')])).lines.get()
        visit.refresh_from_db()
        req = request_line_correction(actor=self.doctor, visit_id=visit.pk, expected_version=visit.lock_version,
            line_id=bill.current_record_version.treatment_lines.get().pk, quantity=D('1'), unit_price=D('70.00'),
            reason='合成收费更正')
        revised = review_correction(actor=self.fin, request_id=req.pk, decision='approve', reason='独立审核合成更正')
        self.assertEqual(invoice_balance(revised)['advance_excess'], D('50'))
        row = self.review_reversal(self.reversal(original))
        self.assertEqual(row.line.record_version_id, original.record_version_id)
        self.assertEqual(invoice_balance(revised)['advance_excess'], 0)
        self.assertEqual(invoice_balance(revised)['remaining'], D('70'))
        self.assertEqual(allocations.available_amount(receipt), D('300'))

    def test_competing_refund_and_application_cannot_consume_the_same_balance(self):
        _, bill = self.billed()
        receipt = self.receipt()
        pending = self.request(receipt, [(bill.pk,'160.00')])
        activate(self.front2, 'FRONT_DESK', self.a)
        refund = self.refund(receipt, '160.00', actor=self.front2)
        other_fin = UserAccount.objects.create_user(username='funds_second_fin')
        RoleAssignment.objects.create(user=other_fin, role='FINANCE', scope_kind='CHAIN')
        activate(other_fin, 'FINANCE')
        a = self.review_preview(pending)
        b = prepare_review(actor=other_fin, entry_id=refund.pk, decision='approve', reason='合成复核')

        def compete(index):
            try:
                if index == 0:
                    allocations.confirm_allocation_review(actor=self.actor_copy(self.fin), allocation_id=pending.pk,
                                                          proposal_token=a, confirmed=True)
                else:
                    confirm_cash_review(actor=self.actor_copy(other_fin), proposal_token=b['proposal_token'], confirmed=True)
            except RuleError:
                return 'changed'
            return 'posted'

        self.assertCountEqual(self.race(compete), ['posted','changed'])
        self.assertEqual(allocations.available_amount(receipt), D('140'))

    def test_posted_only_pagination_and_account_and_store_isolation(self):
        for index in range(21):
            self.receipt(amount='1.00', reference=f'FUND-PAGE-{index}')
        self.receipt(amount='77.00', reference='FUND-PAGE-PENDING', posted=False)
        self.client.force_login(self.pa)
        url = reverse('mini_funds')
        a = self.client.get(url).json()['data']
        b = self.client.get(url, {'page':2,'clinic':self.a.pk}).json()['data']
        self.assertEqual((len(a['entries']), len(b['entries']), b['count'], b['selected']['available']),
                         (20, 1, 21, '21.00'))
        self.assertFalse({r['key'] for r in a['entries']} & {r['key'] for r in b['entries']})
        self.assertEqual(self.client.get(url, {'clinic':self.b.pk}).status_code, 404)
        other = PatientAccess.objects.exclude(user=self.pa).first().user
        self.client.force_login(other)
        self.assertEqual(self.client.get(url).json()['data']['entries'], [])
        self.assertEqual(self.client.get(url, {'clinic':self.a.pk}).status_code, 404)
        RoleAssignment.objects.filter(user=self.front,role='FRONT_DESK',clinic=self.a).update(can_verify_patient_relationships=True)
        token = rel.prepare_create(actor=self.front, patient_no=self.p1.patient_no, related_name='合成代约',
                                   kind='DELEGATE', username=other.username, note='合成关系')
        case, _ = rel.confirm(actor=self.front, token=token, confirmed=True)
        token = rel.prepare_action(actor=self.front, case_id=case.pk, action='VERIFY', basis='IN_PERSON',
                                   reference='SYNTH-FUNDS-AUTH', note='合成核验', valid_until=timezone.now()+timedelta(days=5))
        case, _ = rel.confirm(actor=self.front, token=token, confirmed=True)
        session = self.client.get(reverse('mini_session')).json()['data']
        selection = self.client.post(reverse('mini_subject_select'), {'subject':f'grant:{case.appointment_grant.pk}'},
                                     HTTP_X_ADC_WORKSPACE=session['workspace_token'])
        self.assertEqual(selection.status_code, 200, selection.content)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(reverse('portal_funds')).status_code, 403)

    def test_database_preserves_reversal_and_rejects_unrelated_refund_origin(self):
        _, bill = self.billed()
        receipt = self.receipt()
        pending = self.request(receipt, [(bill.pk,'50.00')])
        with self.assertRaises(IntegrityError), transaction.atomic():
            AdvanceAllocationReversal.objects.create(line=pending.lines.get(), prepared_by=self.front, basis='错误来源')
        self.decide(pending)
        row = self.review_reversal(self.reversal(pending.lines.get()))
        with self.assertRaises(IntegrityError), transaction.atomic():
            AdvanceAllocationReversal.objects.filter(pk=row.pk).update(basis='覆盖原撤销历史')
        with self.assertRaises(IntegrityError), transaction.atomic():
            CashEntry.objects.create(advance_patient=self.p2, clinic=self.a, reversal_of=receipt, kind='REFUND',
                amount='10.00', occurred_on=self.today, reason='错误患者', prepared_by=self.front, operation_id=uuid4())
