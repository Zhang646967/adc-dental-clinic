"""Real PostgreSQL closure: reservations, original reversals and actual cash."""
from datetime import timedelta
from decimal import Decimal as D
from uuid import uuid4
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from accounts.models import RoleAssignment
from adc_core.rules import RuleError
from care.models import TreatmentRecord, Invoice
from finance.cash_models import CashEntry
from finance.payment_account_services import prepare_account, confirm_account
from finance import fund_services as bank
from finance import allocation_services as alloc
from finance import fund_issue_services as issues
from finance.allocation_models import FundAllocation, FundAllocationLine, FundIssue, FundIssueEvent
from finance.allocation_projection import claim_funds, transfer_funds
from insurance import cancellation_services as cancel
from insurance.cancellation_models import CancellationRequest, ReversalOutcome, CancellationReview
from insurance.settlement_models import SettlementRequest
from tests.test_insurance_settlement import SettlementFixture
from tests.test_financial_evidence import EvidenceFixture
from tests.test_care_finance_equipment import activate


class FundClosureFixture(SettlementFixture, EvidenceFixture):
    def setup_closure(self):
        self.setup_settlement()
        p = prepare_account(actor=self.fin, clinic_id=self.a.pk, code='BANK-FUND', method='BANK_TRANSFER')
        self.account = confirm_account(actor=self.fin, proposal_token=p['proposal_token'], confirmed=True)[0]
        self.claim = self.review_settlement(self.settlement())

    def bank_transfer(self, amount='500.00', kind='RECEIPT', booked_on=None):
        line = self.imported(self.raw(transaction_id=uuid4().hex, amount=amount,
            direction='IN' if kind == 'RECEIPT' else 'OUT', booked_on=(booked_on or self.today).isoformat()))
        p = bank.prepare_transfer(actor=self.fin, line_id=line.pk, kind=kind, basis='合成基金银行事实')
        row = bank.confirm_transfer(actor=self.fin, proposal_token=p['proposal_token'], confirmed=True)[0]
        p = bank.prepare_transfer_review(actor=self.second_fin, transfer_id=row.pk, decision='approve', reason='独立核对原流水')
        return bank.confirm_transfer_review(actor=self.second_fin, proposal_token=p['proposal_token'], confirmed=True)[0]

    def allocation_preview(self, transfer, amount='500', claim=None, **kw):
        d = dict(actor=self.fin, transfer_id=transfer.pk,
            allocations=[dict(claim=(claim or self.claim).pk, amount=amount)], basis='按原申报逐笔核对')
        d.update(kw)
        return alloc.prepare_allocation(**d)

    def allocate(self, transfer, **kw):
        p = self.allocation_preview(transfer, **kw)
        return alloc.confirm_allocation(actor=kw.get('actor', self.fin), proposal_token=p['proposal_token'], confirmed=True)[0]

    def allocation_review(self, row, decision='approve', actor=None):
        actor = actor or self.second_fin
        p = alloc.prepare_allocation_review(actor=actor, allocation_id=row.pk, decision=decision, reason='独立核对本次逐笔分配')
        return alloc.confirm_allocation_review(actor=actor, proposal_token=p['proposal_token'], confirmed=True)[0]

    def start_cancel(self, row=None, mode='ACCEPT', actor=None):
        actor = actor or self.front
        p = cancel.prepare_cancellation(actor=actor, request_id=(row or self.claim).pk, simulation_mode=mode, reason='合成撤销原结算')
        return cancel.confirm_cancellation(actor=actor, proposal_token=p['proposal_token'], confirmed=True)[0]

    def cancellation_review(self, row=None, decision='APPROVE', actor=None):
        actor = actor or self.fin
        p = cancel.prepare_cancellation_review(actor=actor, request_id=(row or self.claim).pk,
            decision=decision, reason='独立核对原撤销及退回依据')
        return cancel.confirm_cancellation_review(actor=actor, proposal_token=p['proposal_token'], confirmed=True)[0]

    def new_issue(self, **kw):
        d = dict(actor=self.fin, claim_id=self.claim.pk, kind='SHORTFALL', amount='100',
            owner_id=self.fin.pk, due_at=timezone.now()+timedelta(days=1), basis='等待核实合成扣减依据')
        d.update(kw)
        p = issues.prepare_issue(**d)
        return issues.confirm_issue(actor=d['actor'], proposal_token=p['proposal_token'], confirmed=True)[0]


@override_settings(ADC_CLINICAL_SYNTHETIC=True, ADC_READ_ONLY=False)
class FundAllocationTests(FundClosureFixture, TransactionTestCase):
    def setUp(self): self.setup_closure()

    def test_preview_and_review_separate_bank_receipt_from_patient_cash_and_revenue(self):
        transfer = self.bank_transfer()
        before = self.balance(self.invoice)
        self.allocation_preview(transfer)
        self.assertFalse(FundAllocation.objects.exists())
        row = self.allocate(transfer, amount='300')
        self.assertEqual(claim_funds(self.claim.pk)['reserved_in'], D('300'))
        self.assertEqual(claim_funds(self.claim.pk)['net_received'], D('0'))
        self.allocation_review(row)
        self.assertEqual(claim_funds(self.claim.pk)['net_received'], D('300'))
        self.assertEqual(transfer_funds(transfer)['available'], D('200'))
        self.assertEqual(self.balance(self.invoice), before)
        self.assertFalse(CashEntry.objects.exists())
        self.assertEqual((Invoice.objects.count(), TreatmentRecord.objects.count()), (1, 1))

    def test_batch_can_allocate_one_bank_payment_to_two_claims(self):
        self.t += timedelta(hours=1)
        _, invoice = self.billed()
        second = self.review_settlement(self.settlement(invoice_id=invoice.pk, allocations=[
            dict(treatment_record=invoice.current_record_version.treatment_lines.get().pk,
                patient_cash='300', personal_account='200', fund_amount='500')]))
        transfer = self.bank_transfer('800.00')
        row = self.allocate(transfer, allocations=[dict(claim=second.pk, amount='450'), dict(claim=self.claim.pk, amount='350')])
        self.allocation_review(row)
        self.assertEqual(row.lines.count(), 2)
        self.assertEqual(claim_funds(second.pk)['net_received'], D('450'))
        self.assertEqual(transfer_funds(transfer)['available'], D('0'))

    def test_pending_reservations_block_transfer_and_claim_overallocation(self):
        transfer = self.bank_transfer('400.00'); self.allocate(transfer, amount='350')
        with self.assertRaises(RuleError): self.allocation_preview(transfer, amount='100')
        another = self.bank_transfer()
        with self.assertRaises(RuleError): self.allocation_preview(another, amount='200')
        self.assertEqual(FundAllocation.objects.count(), 1)

    def test_rejection_releases_reservation_and_obsoletes_old_preview(self):
        transfer = self.bank_transfer()
        old = self.allocation_preview(transfer, amount='100')
        row = self.allocate(transfer, amount='400'); self.allocation_review(row, 'reject')
        with self.assertRaisesMessage(RuleError, '进度已变化'):
            alloc.confirm_allocation(actor=self.fin, proposal_token=old['proposal_token'], confirmed=True)
        self.allocation_review(self.allocate(transfer))
        self.assertEqual(claim_funds(self.claim.pk)['net_received'], D('500'))

    def test_return_must_have_original_confirmed_receipt(self):
        transfer = self.bank_transfer(kind='RETURN')
        with self.assertRaises(RuleError): self.allocation_preview(transfer)
        self.allocation_review(self.allocate(self.bank_transfer()))
        row = self.allocate(transfer, amount='200')
        with self.assertRaises(RuleError): self.allocation_preview(self.bank_transfer(kind='RETURN'), amount='400')
        self.allocation_review(row)
        self.assertEqual(claim_funds(self.claim.pk)['net_received'], D('300'))

    def test_disabled_old_mapping_does_not_erase_confirmed_receivable(self):
        self.disable_source(self.cat, 'catalogue')
        self.allocation_review(self.allocate(self.bank_transfer()))
        self.assertEqual(claim_funds(self.claim.pk)['net_received'], D('500'))

    def test_wrong_clinic_currency_and_unreviewed_claim_are_rejected(self):
        transfer = self.bank_transfer()
        from insurance.fund_contract import allocation_source
        with self.assertRaises(RuleError): allocation_source(self.claim, kind='RECEIPT', clinic_id=self.b.pk, currency='CNY')
        with self.assertRaises(RuleError): allocation_source(self.claim, kind='RECEIPT', clinic_id=self.a.pk, currency='USD')
        self.t += timedelta(hours=1)
        _, invoice = self.billed()
        pending = self.settlement(invoice_id=invoice.pk, allocations=[
            dict(treatment_record=invoice.current_record_version.treatment_lines.get().pk,
                patient_cash='300', personal_account='200', fund_amount='500')])
        with self.assertRaises(RuleError): self.allocation_preview(transfer, claim=pending)

    def test_non_finance_and_self_review_rejected(self):
        transfer = self.bank_transfer(); row = self.allocate(transfer)
        with self.assertRaises(PermissionDenied): self.allocation_review(row, actor=self.fin)
        for actor in (self.front, self.manager, self.hq, self.pa, self.tech, self.doctor):
            with self.assertRaises(PermissionDenied): self.allocation_preview(transfer, actor=actor)

    def test_revoked_preparer_cannot_get_approval_but_rejection_is_available(self):
        row = self.allocate(self.bank_transfer())
        RoleAssignment.objects.filter(user=self.fin, role='FINANCE').update(is_active=False)
        with self.assertRaises(RuleError): self.allocation_review(row)
        self.allocation_review(row, 'reject')
        self.assertEqual(claim_funds(self.claim.pk)['reserved_in'], D('0'))

    def test_duplicate_operation_returns_current_record_after_review(self):
        transfer = self.bank_transfer(); p = self.allocation_preview(transfer)
        row, _ = alloc.confirm_allocation(actor=self.fin, proposal_token=p['proposal_token'], confirmed=True)
        self.allocation_review(row)
        replay, repeated = alloc.confirm_allocation(actor=self.fin, proposal_token=p['proposal_token'], confirmed=True)
        self.assertTrue(repeated); self.assertEqual(replay.state, 'CONFIRMED')
        self.assertEqual(FundAllocationLine.objects.count(), 1)

    def test_actual_day_and_bank_booking_day_remain_distinct(self):
        from finance.daily_facts import day_facts
        from finance.allocation_projection import daily_fund_summary
        original_day = self.claim.service_on
        original_cash_day = day_facts(self.a.pk, original_day)
        transfer = self.bank_transfer(booked_on=self.today+timedelta(days=1))
        row = self.allocation_review(self.allocate(transfer))
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.service_on, original_day)
        self.assertEqual(row.source_snapshot['bank_date'], (self.today+timedelta(days=1)).isoformat())
        self.assertNotEqual(row.source_snapshot['bank_date'], original_day.isoformat())
        self.assertEqual(day_facts(self.a.pk, original_day), original_cash_day)
        service_day = daily_fund_summary(self.a.pk, original_day)
        bank_day = daily_fund_summary(self.a.pk, self.today+timedelta(days=1))
        self.assertEqual((service_day['receivable'], service_day['net_received'], service_day['bank_in']), (D('500'), D('500'), D('0')))
        self.assertEqual((bank_day['receivable'], bank_day['bank_in']), (D('0'), D('500')))

    def test_sql_rejects_unbalanced_batch_and_immutable_history(self):
        transfer = self.bank_transfer()
        with self.assertRaises(DatabaseError), transaction.atomic():
            FundAllocation.objects.create(transfer=transfer, total=D('100'), source_snapshot={},
                source_digest='0'*64, basis='无逐笔来源', prepared_by=self.fin)
        row = self.allocation_review(self.allocate(transfer))
        with self.assertRaises(DatabaseError), transaction.atomic(): row.lines.update(amount=D('499'))
        with self.assertRaises(DatabaseError), transaction.atomic(): FundAllocation.objects.filter(pk=row.pk).update(basis='覆盖原凭据')
        with self.assertRaises(DatabaseError), transaction.atomic(): FundAllocation.objects.filter(pk=row.pk).delete()

    def test_audit_failure_rolls_back_all_lines_and_reservations(self):
        transfer = self.bank_transfer(); p = self.allocation_preview(transfer)
        with patch('finance.allocation_services.emit', side_effect=RuntimeError('synthetic audit error')):
            with self.assertRaises(RuntimeError):
                alloc.confirm_allocation(actor=self.fin, proposal_token=p['proposal_token'], confirmed=True)
        self.assertFalse(FundAllocation.objects.exists()); self.assertEqual(transfer_funds(transfer)['available'], D('500'))

    def test_sql_rejects_over_receivable_even_with_sufficient_bank_amount(self):
        transfer = self.bank_transfer('800.00')
        with self.assertRaises(DatabaseError), transaction.atomic():
            row = FundAllocation.objects.create(transfer=transfer, total=D('600'), source_snapshot={},
                source_digest='0'*64, basis='绕过预览试图多分配', prepared_by=self.fin)
            FundAllocationLine.objects.create(allocation=row, claim=self.claim, amount=D('600'))
        self.assertFalse(FundAllocation.objects.exists())

    def test_concurrent_bank_allocation_has_one_effect(self):
        transfer = self.bank_transfer()
        actors = [self.fin, self.second_fin]
        previews = [self.allocation_preview(transfer, actor=a) for a in actors]
        def call(i):
            try:
                alloc.confirm_allocation(actor=self.actor_copy(actors[i]), proposal_token=previews[i]['proposal_token'], confirmed=True)
                return 'saved'
            except RuleError: return 'changed'
        self.assertCountEqual(self.race(call), ['saved', 'changed'])
        self.assertEqual(FundAllocationLine.objects.count(), 1)

    def test_two_bank_payments_cannot_overallocate_same_claim(self):
        transfers = [self.bank_transfer(), self.bank_transfer()]
        actors = [self.fin, self.second_fin]
        previews = [self.allocation_preview(t, actor=a) for t, a in zip(transfers, actors)]
        def call(i):
            try:
                alloc.confirm_allocation(actor=self.actor_copy(actors[i]), proposal_token=previews[i]['proposal_token'], confirmed=True)
                return 'saved'
            except RuleError: return 'changed'
        self.assertCountEqual(self.race(call), ['saved', 'changed'])
        self.assertEqual(claim_funds(self.claim.pk)['reserved_in'], D('500'))


@override_settings(ADC_CLINICAL_SYNTHETIC=True, ADC_READ_ONLY=False)
class FundIssueTests(FundClosureFixture, TransactionTestCase):
    def setUp(self): self.setup_closure()

    def test_issue_and_closure_never_change_patient_or_fund_amounts(self):
        before = self.balance(self.invoice); fund = claim_funds(self.claim.pk)
        row = self.new_issue()
        p = issues.prepare_followup(actor=self.fin, issue_id=row.pk, state='CLOSED', owner_id=self.fin.pk,
            due_at=None, basis='已取得扣减依据，继续按原结算承担，未作金额核销')
        issues.confirm_followup(actor=self.fin, proposal_token=p['proposal_token'], confirmed=True)
        self.assertEqual(row.events.latest('sequence').state, 'CLOSED')
        self.assertEqual(before, self.balance(self.invoice)); self.assertEqual(fund, claim_funds(self.claim.pk))
        self.assertFalse(CashEntry.objects.exists())

    def test_missing_amount_stays_unknown_and_owner_must_be_active(self):
        row = self.new_issue(kind='UNKNOWN', amount=None); self.assertIsNone(row.amount)
        with self.assertRaises(RuleError): self.new_issue(owner_id=self.front.pk)
        with self.assertRaises(RuleError): self.new_issue(due_at=timezone.now()-timedelta(days=1))

    def test_reassign_unavailable_owner_retains_history_and_rejects_stale_followup(self):
        row = self.new_issue(); due = timezone.now()+timedelta(days=2)
        p = issues.prepare_followup(actor=self.second_fin, issue_id=row.pk, state='OPEN',
            owner_id=self.second_fin.pk, due_at=due, basis='重新安排联系责任')
        RoleAssignment.objects.filter(user=self.fin, role='FINANCE').update(is_active=False)
        issues.confirm_followup(actor=self.second_fin, proposal_token=p['proposal_token'], confirmed=True)
        self.assertEqual(list(row.events.order_by('sequence').values_list('owner_id', flat=True)), [self.fin.pk, self.second_fin.pk])
        again, repeated = issues.confirm_followup(actor=self.second_fin, proposal_token=p['proposal_token'], confirmed=True)
        self.assertTrue(repeated); self.assertEqual(again.pk, row.pk)
        with self.assertRaises(DatabaseError), transaction.atomic(): row.events.update(basis='重写沟通')

    def test_revoked_owner_after_preview_and_other_roles_cannot_create(self):
        p = issues.prepare_issue(actor=self.second_fin, claim_id=self.claim.pk, kind='UNKNOWN', amount=None,
            owner_id=self.fin.pk, due_at=timezone.now()+timedelta(days=1), basis='用途待核实')
        RoleAssignment.objects.filter(user=self.fin, role='FINANCE').update(is_active=False)
        with self.assertRaises(RuleError): issues.confirm_issue(actor=self.second_fin, proposal_token=p['proposal_token'], confirmed=True)
        self.assertFalse(FundIssue.objects.exists())
        for actor in (self.front, self.manager, self.hq, self.pa):
            with self.assertRaises(PermissionDenied): self.new_issue(actor=actor)


@override_settings(ADC_CLINICAL_SYNTHETIC=True, ADC_READ_ONLY=False)
class InsuranceCancellationTests(FundClosureFixture, TransactionTestCase):
    def setUp(self): self.setup_closure()

    def test_cancel_without_bank_receipt_withdraws_credit_only_after_review(self):
        row = self.start_cancel()
        self.assertEqual(row.state, 'CANCEL_PENDING')
        self.assertEqual(self.balance(self.invoice)['remaining'], D('300'))
        row = self.cancellation_review()
        self.assertEqual(row.state, 'CANCELLED')
        self.assertEqual(self.balance(self.invoice)['remaining'], D('1000'))
        self.assertFalse(CashEntry.objects.exists())
        self.assertEqual(self.claim.simulation_outcome.result, 'ACCEPTED')
        self.assertEqual(TreatmentRecord.objects.count(), 1)

    def test_paid_fund_must_be_returned_and_return_must_be_independently_reviewed(self):
        self.allocation_review(self.allocate(self.bank_transfer()))
        self.start_cancel()
        with self.assertRaises(RuleError): self.cancellation_review()
        with self.assertRaises(RuleError): self.allocation_preview(self.bank_transfer(), amount='1')
        returned = self.allocate(self.bank_transfer(kind='RETURN'))
        with self.assertRaises(RuleError): self.cancellation_review()
        self.allocation_review(returned)
        row = self.cancellation_review(); self.assertEqual(row.state, 'CANCELLED')
        self.assertEqual(claim_funds(row.pk)['net_received'], D('0'))
        self.assertEqual(self.balance(self.invoice)['billed'], D('1000'))

    def test_partial_return_keeps_original_credit_and_cancellation_pending(self):
        self.allocation_review(self.allocate(self.bank_transfer()))
        self.start_cancel()
        self.allocation_review(self.allocate(self.bank_transfer('200.00', 'RETURN'), amount='200'))
        with self.assertRaises(RuleError): self.cancellation_review()
        self.assertEqual(self.balance(self.invoice)['remaining'], D('300'))
        self.assertEqual(claim_funds(self.claim.pk)['net_received'], D('300'))

    def test_lost_reversal_reply_queries_same_original_id(self):
        row = self.start_cancel(mode='LOST_SUCCESS')
        original = row.cancellation.cancellation_id
        with self.assertRaises(RuleError): self.cancellation_review()
        with self.assertRaises(RuleError): self.start_cancel()
        p = cancel.prepare_cancellation_query(actor=self.front, request_id=row.pk)
        for _ in range(2):
            cancel.confirm_cancellation_query(actor=self.front, proposal_token=p['proposal_token'], confirmed=True)
        self.cancellation_review()
        row.refresh_from_db()
        self.assertEqual(row.cancellation.cancellation_id, original)
        self.assertEqual((CancellationRequest.objects.count(), ReversalOutcome.objects.count()), (1, 1))
        self.assertEqual(row.events.get(action='CANCEL_START').snapshot['cancellation_state'], 'UNKNOWN')
        self.assertEqual(row.events.get(action='CANCEL_QUERY').snapshot['cancellation_state'], 'AWAITING_REVIEW')

    def test_processing_and_rejected_review_can_continue_original_cancellation(self):
        row = self.start_cancel(mode='PROCESSING')
        p = cancel.prepare_cancellation_query(actor=self.fin, request_id=row.pk)
        cancel.confirm_cancellation_query(actor=self.fin, proposal_token=p['proposal_token'], confirmed=True)
        self.cancellation_review(decision='REJECT')
        self.assertEqual(self.balance(self.invoice)['remaining'], D('300'))
        self.cancellation_review()
        self.assertEqual(CancellationReview.objects.count(), 2)

    def test_unreviewed_and_rejected_settlements_never_gain_credit_during_cancel(self):
        self.start_cancel(); self.cancellation_review()
        row = self.review_settlement(self.settlement(), decision='REJECT')
        self.assertEqual(self.balance(self.invoice)['remaining'], D('1000'))
        self.start_cancel(row)
        self.assertEqual(self.balance(self.invoice)['remaining'], D('1000'))
        self.cancellation_review(row)
        self.assertEqual(self.balance(self.invoice)['remaining'], D('1000'))

    def test_unknown_original_settlement_must_be_queried_before_cancelling(self):
        self.start_cancel(); self.cancellation_review()
        row = self.settlement(simulation_mode='LOST_SUCCESS')
        with self.assertRaises(RuleError): self.start_cancel(row)
        self.query(row); self.start_cancel(row); self.cancellation_review(row)

    def test_pending_allocation_or_cash_blocks_cancellation_start(self):
        allocation = self.allocate(self.bank_transfer())
        with self.assertRaises(RuleError): self.start_cancel()
        self.allocation_review(allocation, 'reject')
        cash = self.cash(self.invoice, amount='100')
        with self.assertRaises(RuleError): self.start_cancel()
        self.approve(cash, 'reject'); self.start_cancel()

    def test_cash_is_preserved_after_cancellation_and_no_automatic_refund_is_posted(self):
        self.approve(self.cash(self.invoice, amount='300'))
        self.start_cancel(); self.cancellation_review()
        balance = self.balance(self.invoice)
        self.assertEqual((balance['billed'], balance['net_received'], balance['remaining']), (D('1000'), D('300'), D('700')))
        self.assertEqual(CashEntry.objects.count(), 1)
        self.approve(self.cash(self.invoice, amount='700'))
        self.assertEqual(self.balance(self.invoice)['remaining'], D('0'))

    def test_cross_clinic_non_financial_and_same_account_cannot_cancel_or_review(self):
        for actor in (self.front2, self.manager, self.hq, self.doctor, self.pa, self.tech):
            with self.assertRaises((PermissionDenied, SettlementRequest.DoesNotExist)): self.start_cancel(actor=actor)
        self.start_cancel()
        RoleAssignment.objects.create(user=self.front, role='FINANCE', scope_kind='CHAIN')
        activate(self.front, 'FINANCE')
        with self.assertRaises(PermissionDenied): self.cancellation_review(actor=self.front)

    def test_duplicate_confirm_and_review_return_original_current_state(self):
        p = cancel.prepare_cancellation(actor=self.front, request_id=self.claim.pk, simulation_mode='ACCEPT', reason='合成原撤销')
        row, _ = cancel.confirm_cancellation(actor=self.front, proposal_token=p['proposal_token'], confirmed=True)
        self.cancellation_review()
        replay, repeated = cancel.confirm_cancellation(actor=self.front, proposal_token=p['proposal_token'], confirmed=True)
        self.assertTrue(repeated); self.assertEqual(replay.state, 'CANCELLED')
        self.assertEqual(CancellationRequest.objects.count(), 1)

    def test_revoked_reviewer_cannot_apply_old_preview(self):
        self.start_cancel()
        p = cancel.prepare_cancellation_review(actor=self.fin, request_id=self.claim.pk, decision='APPROVE', reason='合成核对')
        RoleAssignment.objects.filter(user=self.fin, role='FINANCE').update(is_active=False)
        with self.assertRaises(PermissionDenied):
            cancel.confirm_cancellation_review(actor=self.fin, proposal_token=p['proposal_token'], confirmed=True)
        self.claim.refresh_from_db(); self.assertEqual(self.claim.state, 'CANCEL_PENDING')

    def test_sql_cannot_cancel_without_return_proof_or_rewrite_reversal(self):
        self.allocation_review(self.allocate(self.bank_transfer()))
        row = self.start_cancel()
        with self.assertRaises(DatabaseError), transaction.atomic():
            CancellationReview.objects.create(cancellation=row.cancellation, operation_id=uuid4(), sequence=1,
                decision='APPROVE', reviewed_by=self.fin, reason='绕过已到账退回', clearance_snapshot={})
        with self.assertRaises(DatabaseError), transaction.atomic(): ReversalOutcome.objects.update(payload={})
        with self.assertRaises(DatabaseError), transaction.atomic():
            SettlementRequest.objects.filter(pk=row.pk).update(state='CANCELLED', lock_version=row.lock_version+1)
        with self.assertRaises(DatabaseError), transaction.atomic(): CancellationRequest.objects.filter(pk=row.cancellation.pk).delete()

    def test_allocation_and_cancellation_race_keep_one_legal_effect(self):
        transfer = self.bank_transfer()
        p = self.allocation_preview(transfer)
        c = cancel.prepare_cancellation(actor=self.front, request_id=self.claim.pk, simulation_mode='ACCEPT', reason='合成并发撤销')
        def call(i):
            try:
                if i == 0:
                    alloc.confirm_allocation(actor=self.actor_copy(self.fin), proposal_token=p['proposal_token'], confirmed=True)
                else:
                    cancel.confirm_cancellation(actor=self.actor_copy(self.front), proposal_token=c['proposal_token'], confirmed=True)
                return 'saved'
            except RuleError: return 'changed'
        self.assertCountEqual(self.race(call), ['saved', 'changed'])
        self.assertEqual(FundAllocation.objects.count()+CancellationRequest.objects.count(), 1)

    def test_audit_failure_rolls_back_reversal_and_source_state(self):
        p = cancel.prepare_cancellation(actor=self.front, request_id=self.claim.pk, simulation_mode='ACCEPT', reason='合成撤销')
        with patch('insurance.settlement_services.emit', side_effect=RuntimeError('synthetic audit')):
            with self.assertRaises(RuntimeError):
                cancel.confirm_cancellation(actor=self.front, proposal_token=p['proposal_token'], confirmed=True)
        self.claim.refresh_from_db(); self.assertEqual(self.claim.state, 'CONFIRMED')
        self.assertFalse(CancellationRequest.objects.exists()); self.assertFalse(ReversalOutcome.objects.exists())
