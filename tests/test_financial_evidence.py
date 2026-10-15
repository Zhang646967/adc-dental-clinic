"""Real PostgreSQL evidence, import, permissions and concurrent review contracts."""
import csv,io,hashlib
from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction,IntegrityError
from django.test import TransactionTestCase,override_settings
from django.urls import reverse
from accounts.models import RoleAssignment,UserAccount
from care.models import AuditEvent
from finance.cash_models import CashEntry
from finance.cash_services import prepare_cash,confirm_cash_request
from finance.cash_selectors import invoice_balance
from finance.reconciliation_models import PaymentAccount,CashEvidenceVersion,StatementBatch,StatementLine,ReconciliationMatch
from finance.payment_account_services import prepare_account,confirm_account
from finance.cash_evidence_services import prepare_evidence,confirm_evidence,prepare_evidence_review,confirm_evidence_review,effective
from finance.statement_services import prepare_import,confirm_import
from finance.reconciliation_services import prepare_match,confirm_match,prepare_match_review,confirm_match_review
from finance.reconciliation_selectors import evidence_summary,candidates
from finance.statement_csv import HEADER
from adc_core.rules import RuleError
from tests.test_care_finance_equipment import CFEFixture,activate
from tests.workspace_client import WorkspaceClient

class EvidenceFixture(CFEFixture):
    def setup_evidence(self):
        self.setup_cfe()
        p=prepare_account(actor=self.fin,clinic_id=self.a.pk,code='BANK-A',method='BANK_TRANSFER')
        self.account=confirm_account(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)[0]
    def posted(self,reference='REF-A',amount='100'):
        _,bill=self.billed()
        return self.approve(self.cash(bill,amount=D(amount),reference=reference,payment_account_id=self.account.pk))
    def raw(self,**kw):
        row=dict(transaction_id='TX-A',booked_on=self.today.isoformat(),direction='IN',amount='100.00',currency='CNY',reference='REF-A');row.update(kw)
        buf=io.StringIO(newline='');w=csv.writer(buf);w.writerow(HEADER);w.writerow([row[k] for k in HEADER]);return buf.getvalue().encode()
    def imported(self,source=None):
        p=prepare_import(actor=self.manager,payment_account_id=self.account.pk,source_bytes=source or self.raw())
        b=confirm_import(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]
        return StatementLine.objects.get(batch=b) if b.new_count==1 else b
    def proposed(self,entry,line):
        p=prepare_match(actor=self.manager,line_id=line.pk,entry_id=entry.pk)
        return confirm_match(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True,expected_line_id=line.pk)[0]
    def match_review(self,row,decision='approve',actor=None):
        actor=actor or self.fin;p=prepare_match_review(actor=actor,match_id=row.pk,decision=decision,reason='合成独立逐笔核对')
        return confirm_match_review(actor=actor,proposal_token=p['proposal_token'],confirmed=True,expected_match_id=row.pk)[0]
    def amendment(self,entry,reference='REF-B'):
        p=prepare_evidence(actor=self.front,entry_id=entry.pk,payment_account_id=self.account.pk,reference=reference,reason='合成补证或纠错')
        return confirm_evidence(actor=self.front,proposal_token=p['proposal_token'],confirmed=True,expected_entry_id=entry.pk)[0]
    def evidence_review(self,row,decision='approve',actor=None):
        actor=actor or self.fin;p=prepare_evidence_review(actor=actor,evidence_id=row.pk,decision=decision,reason='合成独立补证核对')
        return confirm_evidence_review(actor=actor,proposal_token=p['proposal_token'],confirmed=True,expected_evidence_id=row.pk)[0]

class PaymentEvidenceTests(EvidenceFixture,TransactionTestCase):
    def setUp(self):self.setup_evidence()
    def test_pre_r1_cash_contracts_expire_without_business_effects(self):
        from finance.cash_services import prepare_review,confirm_cash_review
        _,bill=self.billed()
        with patch('finance.cash_services.REQUEST','adc.cash.request.v1'):
            old_request=self.cash_preview(bill)
        with self.assertRaises(RuleError):
            confirm_cash_request(actor=self.front,proposal_token=old_request['proposal_token'],confirmed=True)
        self.assertFalse(CashEntry.objects.exists())
        entry=self.cash(bill)
        with patch('finance.cash_services.REVIEW','adc.cash.review.v1'):
            old_review=prepare_review(actor=self.fin,entry_id=entry.pk,decision='approve',reason='旧版本预览')
        with self.assertRaises(RuleError):
            confirm_cash_review(actor=self.fin,proposal_token=old_review['proposal_token'],confirmed=True)
        entry.refresh_from_db()
        self.assertEqual(entry.state,'PENDING')
        self.assertEqual(entry.evidence_versions.get().state,'PENDING')
        self.assertEqual(invoice_balance(bill)['net_received'],0)
    def test_new_cash_requires_valid_clinic_account_and_reference(self):
        _,bill=self.billed()
        for values in ({'payment_account_id':None},{'reference':''},{'payment_account_id':999999}):
            with self.assertRaises(RuleError):self.cash_preview(bill,**values)
        self.assertFalse(CashEntry.objects.exists())
    def test_initial_evidence_and_money_review_are_atomic(self):
        _,bill=self.billed();entry=self.cash(bill,payment_account_id=self.account.pk,reference='REF-A')
        evidence=entry.evidence_versions.get();self.assertEqual(evidence.state,'PENDING');self.assertIsNone(effective(entry.pk))
        self.approve(entry);evidence.refresh_from_db();self.assertEqual(evidence.state,'APPROVED');self.assertEqual(evidence.reviewed_by_id,self.fin.pk)
        self.assertEqual(invoice_balance(bill)['net_received'],D('100'))
    def test_rejection_rejects_initial_evidence_without_money(self):
        _,bill=self.billed();entry=self.cash(bill);self.approve(entry,'reject')
        self.assertEqual(entry.evidence_versions.get().state,'REJECTED');self.assertEqual(invoice_balance(bill)['net_received'],0)
    def test_audit_failure_rolls_back_cash_and_initial_evidence(self):
        _,bill=self.billed();p=self.cash_preview(bill)
        with patch('finance.cash_services.emit',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):confirm_cash_request(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(CashEntry.objects.exists());self.assertFalse(CashEvidenceVersion.objects.exists())
    def test_account_disable_invalidates_old_cash_preview_and_retains_matching(self):
        entry=self.posted();line=self.imported();p=self.cash_preview(entry.invoice,amount='1.00',payment_account_id=self.account.pk)
        q=prepare_account(actor=self.fin,account_id=self.account.pk,active=False)
        confirm_account(actor=self.fin,proposal_token=q['proposal_token'],confirmed=True,expected_account_id=self.account.pk)
        with self.assertRaises(RuleError):confirm_cash_request(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.match_review(self.proposed(entry,line));self.assertEqual(ReconciliationMatch.objects.get().state,'CONFIRMED')
    def test_account_identity_and_evidence_decisions_are_sql_immutable(self):
        entry=self.posted()
        for fn in [lambda:PaymentAccount.objects.filter(pk=self.account.pk).update(code='REWRITE'),lambda:entry.evidence_versions.update(reference='REWRITE'),lambda:entry.evidence_versions.all().delete()]:
            with self.assertRaises(IntegrityError),transaction.atomic():fn()
    def test_account_creation_and_state_changes_replay_safely(self):
        p=prepare_account(actor=self.fin,clinic_id=self.a.pk,code='OTHER-A',method='OTHER')
        one=confirm_account(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)[0]
        two,repeated=confirm_account(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(repeated);self.assertEqual(one.pk,two.pk)
        p=prepare_account(actor=self.fin,account_id=one.pk,active=False)
        confirm_account(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True,expected_account_id=one.pk)
        _,repeated=confirm_account(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True,expected_account_id=one.pk);self.assertTrue(repeated)
    def test_historical_missing_evidence_is_not_backfilled(self):
        _,bill=self.billed()
        entry=CashEntry.objects.create(clinic=self.a,invoice=bill,based_record_version=bill.current_record_version,kind='RECEIPT',amount=100,occurred_on=self.today,prepared_by=self.front,reason='R1之前的合成历史')
        self.approve(entry);self.assertIsNone(effective(entry.pk));original=CashEntry.objects.values().get(pk=entry.pk)
        row=self.amendment(entry);self.evidence_review(row)
        self.assertEqual(CashEntry.objects.values().get(pk=entry.pk),original);self.assertEqual(effective(entry.pk).version,1)
    def test_correction_preserves_confirmed_decision_and_invalidates_match(self):
        entry=self.posted();line=self.imported();match=self.match_review(self.proposed(entry,line));original=CashEntry.objects.values().get(pk=entry.pk)
        row=self.amendment(entry);self.assertEqual(ReconciliationMatch.objects.get().state,'CONFIRMED')
        self.evidence_review(row);match.refresh_from_db()
        self.assertEqual(match.state,'STALE');self.assertEqual(match.reviewed_by_id,self.fin.pk);self.assertIsNotNone(match.reviewed_at)
        self.assertEqual(CashEntry.objects.values().get(pk=entry.pk),original);self.assertEqual(effective(entry.pk).version,2)
        self.assertEqual(candidates(self.manager,line),[])
    def test_rejected_amendment_keeps_effective_evidence_and_match(self):
        entry=self.posted();line=self.imported();self.match_review(self.proposed(entry,line))
        self.evidence_review(self.amendment(entry),'reject')
        self.assertEqual(effective(entry.pk).version,1);self.assertEqual(ReconciliationMatch.objects.get().state,'CONFIRMED')
    def test_no_self_review_by_switching_roles(self):
        entry=self.posted();row=self.amendment(entry)
        RoleAssignment.objects.create(user=self.front,role='FINANCE',scope_kind='CHAIN');activate(self.front,'FINANCE')
        with self.assertRaises(RuleError):self.evidence_review(row,actor=self.front)
    def test_revoked_supplement_preparer_cannot_be_approved(self):
        row=self.amendment(self.posted());p=prepare_evidence_review(actor=self.fin,evidence_id=row.pk,decision='approve',reason='合成')
        RoleAssignment.objects.filter(user=self.front,role='FRONT_DESK').update(is_active=False)
        with self.assertRaises(RuleError):confirm_evidence_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True,expected_evidence_id=row.pk)

class StatementImportTests(EvidenceFixture,TransactionTestCase):
    def setUp(self):self.setup_evidence()
    def test_stage_is_private_and_accept_has_no_money_effect(self):
        entry=self.posted();before=list(CashEntry.objects.values());raw=self.raw()
        p=prepare_import(actor=self.manager,payment_account_id=self.account.pk,source_bytes=raw)
        self.assertFalse(StatementLine.objects.exists());batch=p['batch'];self.assertEqual(bytes(batch.source_bytes),raw);self.assertEqual(batch.digest,hashlib.sha256(raw).hexdigest())
        confirm_import(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(list(CashEntry.objects.values()),before)
    def test_exact_duplicates_across_and_within_batches_are_skipped(self):
        self.imported();raw=self.raw();duplicate=raw+raw.split(b'\r\n')[1]+b'\r\n'
        p=prepare_import(actor=self.manager,payment_account_id=self.account.pk,source_bytes=duplicate)
        b=confirm_import(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]
        self.assertEqual((b.new_count,b.skipped_count),(0,2));self.assertEqual(StatementLine.objects.count(),1)
    def test_conflict_after_preview_accepts_nothing_in_batch(self):
        p=prepare_import(actor=self.manager,payment_account_id=self.account.pk,source_bytes=self.raw(amount='99.00'))
        self.imported()
        with self.assertRaises(RuleError):confirm_import(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(StatementLine.objects.count(),1);p['batch'].refresh_from_db();self.assertEqual(p['batch'].state,'DRAFT')
    def test_raw_bytes_rows_and_accepted_lines_cannot_be_rewritten(self):
        line=self.imported()
        for fn in [lambda:StatementBatch.objects.filter(pk=line.batch_id).update(source_bytes=b'rewrite'),lambda:StatementBatch.objects.filter(pk=line.batch_id).update(normalized_rows=[]),lambda:StatementLine.objects.filter(pk=line.pk).update(amount=1),lambda:StatementLine.objects.filter(pk=line.pk).delete()]:
            with self.assertRaises(IntegrityError),transaction.atomic():fn()
    def test_foreign_account_and_stale_workspace_cannot_import(self):
        RoleAssignment.objects.create(user=self.manager,role='MANAGER',scope_kind='CLINIC',clinic=self.b)
        p=prepare_import(actor=self.manager,payment_account_id=self.account.pk,source_bytes=self.raw())
        activate(self.manager,'MANAGER',self.b)
        with self.assertRaises((RuleError,PermissionDenied)):confirm_import(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        with self.assertRaises(RuleError):prepare_import(actor=self.manager,payment_account_id=self.account.pk,source_bytes=self.raw())
    def test_repeated_confirmation_returns_one_import(self):
        p=prepare_import(actor=self.manager,payment_account_id=self.account.pk,source_bytes=self.raw())
        b=confirm_import(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]
        again,repeated=confirm_import(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(repeated);self.assertEqual(b.pk,again.pk);self.assertEqual(StatementLine.objects.count(),1)
    def test_disabled_account_invalidates_import_preview_and_retains_source(self):
        raw=self.raw();p=prepare_import(actor=self.manager,payment_account_id=self.account.pk,source_bytes=raw)
        q=prepare_account(actor=self.fin,account_id=self.account.pk,active=False)
        confirm_account(actor=self.fin,proposal_token=q['proposal_token'],confirmed=True,expected_account_id=self.account.pk)
        with self.assertRaises(RuleError):confirm_import(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(StatementLine.objects.exists())
        p['batch'].refresh_from_db();self.assertEqual(p['batch'].state,'DRAFT');self.assertEqual(bytes(p['batch'].source_bytes),raw)
    def test_revoked_importer_cannot_accept_staged_source(self):
        p=prepare_import(actor=self.manager,payment_account_id=self.account.pk,source_bytes=self.raw())
        RoleAssignment.objects.filter(user=self.manager,role='MANAGER').update(is_active=False)
        with self.assertRaises(PermissionDenied):confirm_import(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(StatementLine.objects.exists())
        p['batch'].refresh_from_db();self.assertEqual(p['batch'].state,'DRAFT')
    def test_concurrent_overlapping_batches_keep_single_transaction(self):
        previews=[prepare_import(actor=self.manager,payment_account_id=self.account.pk,source_bytes=self.raw()) for _ in range(2)]
        def run(i):return confirm_import(actor=self.actor_copy(self.manager),proposal_token=previews[i]['proposal_token'],confirmed=True)[0].new_count
        self.assertEqual(sorted(self.race(run)),[0,1]);self.assertEqual(StatementLine.objects.count(),1)
    def test_audit_failure_rolls_back_lines_and_import_decision(self):
        p=prepare_import(actor=self.manager,payment_account_id=self.account.pk,source_bytes=self.raw())
        with patch('finance.statement_services.emit',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):confirm_import(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(StatementLine.objects.exists());p['batch'].refresh_from_db();self.assertEqual(p['batch'].state,'DRAFT')

class ReconciliationTests(EvidenceFixture,TransactionTestCase):
    def setUp(self):self.setup_evidence()
    def test_complete_exact_match_keeps_balance_and_has_independent_review(self):
        entry=self.posted();line=self.imported();before=list(CashEntry.objects.values());row=self.proposed(entry,line)
        self.assertEqual(row.state,'PENDING');self.match_review(row)
        self.assertEqual(evidence_summary(self.a.pk),dict(posted=1,evidenced=1,matched=1));self.assertEqual(list(CashEntry.objects.values()),before)
    def test_partial_receipts_refund_equipment_and_reversal_keep_exact_gross_facts(self):
        entry=self.posted();bill=entry.invoice;entries=[entry]
        for amount,reference in [('40.00','PART-1'),('59.98','PART-2')]:
            entries.append(self.approve(self.cash(bill,amount=amount,reference=reference,payment_account_id=self.account.pk)))
        entries.append(self.approve(self.cash(bill,kind='REFUND',amount='10.01',reference='REFUND-1',payment_account_id=self.account.pk)))
        event=self.asset(acquisition_cost='10.01').events.get(sequence=0)
        p=prepare_cash(actor=self.manager,source_type='equipment',source_id=event.pk,kind='EQUIPMENT_EXPENSE',occurred_on=self.today,reason='合成设备付款',payment_account_id=self.account.pk,reference='EQUIP-1')
        expense=self.approve(confirm_cash_request(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]);entries.append(expense)
        p=prepare_cash(actor=self.manager,source_type='equipment',source_id=event.pk,kind='EXPENSE_REVERSAL',reversal_id=expense.pk,occurred_on=self.today,reason='合成费用冲回',payment_account_id=self.account.pk,reference='EQUIP-REV')
        entries.append(self.approve(confirm_cash_request(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]))
        before=list(CashEntry.objects.values())
        for index,cash in enumerate(entries):
            direction='IN' if cash.kind in ('RECEIPT','EXPENSE_REVERSAL') else 'OUT'
            line=self.imported(self.raw(transaction_id='GROSS-'+str(index),amount=str(cash.amount),direction=direction,reference=effective(cash.pk).reference))
            self.match_review(self.proposed(cash,line))
        self.assertEqual(list(CashEntry.objects.values()),before)
        self.assertEqual(invoice_balance(bill)['net_received'],D('189.97'))
        self.assertEqual(evidence_summary(self.a.pk)['matched'],6)
    def test_database_rejects_approved_evidence_without_atomic_match_invalidation(self):
        entry=self.posted();self.match_review(self.proposed(entry,self.imported()));row=self.amendment(entry)
        from django.utils import timezone
        with self.assertRaises(IntegrityError),transaction.atomic():
            CashEvidenceVersion.objects.filter(pk=row.pk).update(state='APPROVED',reviewed_by=self.fin,reviewed_at=timezone.now(),review_reason='只更新凭据但漏失效匹配')
        self.assertEqual(ReconciliationMatch.objects.get().state,'CONFIRMED')
        row.refresh_from_db();self.assertEqual(row.state,'PENDING')
    def test_pending_cash_wrong_amount_direction_currency_and_reference_rejected(self):
        entry=self.posted()
        for n,kwargs in enumerate([dict(amount='99.00'),dict(direction='OUT'),dict(currency='USD'),dict(reference='OTHER')]):
            line=self.imported(self.raw(transaction_id='BAD-'+str(n),**kwargs))
            with self.assertRaises(RuleError):prepare_match(actor=self.manager,line_id=line.pk,entry_id=entry.pk)
        pending=self.cash(entry.invoice,amount='1.00',reference='REF-A',payment_account_id=self.account.pk);line=self.imported()
        with self.assertRaises(RuleError):prepare_match(actor=self.manager,line_id=line.pk,entry_id=pending.pk)
    def test_wrong_account_or_foreign_clinic_cannot_match(self):
        entry=self.posted();line=self.imported()
        p=prepare_account(actor=self.fin,clinic_id=self.a.pk,code='OTHER',method='CARD');other=confirm_account(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)[0]
        p=prepare_import(actor=self.manager,payment_account_id=other.pk,source_bytes=self.raw())
        b=confirm_import(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]
        with self.assertRaises(RuleError):prepare_match(actor=self.manager,line_id=b.lines.get().pk,entry_id=entry.pk)
        RoleAssignment.objects.create(user=self.manager,role='MANAGER',scope_kind='CLINIC',clinic=self.b);activate(self.manager,'MANAGER',self.b)
        with self.assertRaises(StatementLine.DoesNotExist):prepare_match(actor=self.manager,line_id=line.pk,entry_id=entry.pk)
    def test_match_self_review_and_revoked_preparer_refused(self):
        row=self.proposed(self.posted(),self.imported())
        RoleAssignment.objects.create(user=self.manager,role='FINANCE',scope_kind='CHAIN');activate(self.manager,'FINANCE')
        with self.assertRaises(RuleError):self.match_review(row,actor=self.manager)
        p=prepare_match_review(actor=self.fin,match_id=row.pk,decision='approve',reason='合成')
        RoleAssignment.objects.filter(user=self.manager,role='MANAGER').update(is_active=False)
        with self.assertRaises(RuleError):confirm_match_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True,expected_match_id=row.pk)
    def test_match_rejection_preserves_difference_and_can_be_reproposed(self):
        entry=self.posted();line=self.imported();self.match_review(self.proposed(entry,line),'reject')
        self.match_review(self.proposed(entry,line));self.assertEqual(list(ReconciliationMatch.objects.order_by('pk').values_list('state',flat=True)),['REJECTED','CONFIRMED'])
    def test_two_previews_cannot_match_same_cash_and_line_twice(self):
        entry=self.posted();line=self.imported();ps=[prepare_match(actor=self.manager,line_id=line.pk,entry_id=entry.pk) for _ in range(2)]
        def run(i):
            try:return confirm_match(actor=self.actor_copy(self.manager),proposal_token=ps[i]['proposal_token'],confirmed=True,expected_line_id=line.pk)[0].state
            except RuleError:return 'DENIED'
        self.assertEqual(sorted(self.race(run)),['DENIED','PENDING']);self.assertEqual(ReconciliationMatch.objects.count(),1)
    def test_review_replay_and_direct_history_tampering(self):
        row=self.proposed(self.posted(),self.imported());p=prepare_match_review(actor=self.fin,match_id=row.pk,decision='approve',reason='合成')
        for i in range(2):
            _,repeat=confirm_match_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True,expected_match_id=row.pk);self.assertEqual(repeat,i==1)
        with self.assertRaises(IntegrityError),transaction.atomic():ReconciliationMatch.objects.filter(pk=row.pk).update(state='REJECTED')
    def test_stale_evidence_preview_does_not_create_match(self):
        entry=self.posted();line=self.imported();p=prepare_match(actor=self.manager,line_id=line.pk,entry_id=entry.pk)
        self.evidence_review(self.amendment(entry))
        with self.assertRaises(RuleError):confirm_match(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True,expected_line_id=line.pk)
    def test_next_day_settlement_does_not_change_fact_date(self):
        entry=self.posted();line=self.imported(self.raw(booked_on=(self.today+timedelta(days=1)).isoformat()))
        self.match_review(self.proposed(entry,line));entry.refresh_from_db();self.assertEqual(entry.occurred_on,self.today)
    def test_correction_racing_match_review_cannot_leave_old_active_match(self):
        entry=self.posted();row=self.proposed(entry,self.imported());amend=self.amendment(entry)
        a=prepare_match_review(actor=self.fin,match_id=row.pk,decision='approve',reason='合成')
        b=prepare_evidence_review(actor=self.fin,evidence_id=amend.pk,decision='approve',reason='合成')
        def run(i):
            actor=self.actor_copy(self.fin)
            try:
                if i==0:return confirm_match_review(actor=actor,proposal_token=a['proposal_token'],confirmed=True,expected_match_id=row.pk)[0].state
                return confirm_evidence_review(actor=actor,proposal_token=b['proposal_token'],confirmed=True,expected_evidence_id=amend.pk)[0].state
            except RuleError:return 'STALE'
        self.race(run);row.refresh_from_db();self.assertEqual(row.state,'STALE');self.assertEqual(effective(entry.pk).version,2)

class FinancialEvidenceHTTPTests(EvidenceFixture,TransactionTestCase):
    def setUp(self):self.setup_evidence()
    def client_for(self,actor):
        c=WorkspaceClient();c.force_login(actor);return c
    def test_seven_roles_have_explicit_route_boundaries(self):
        for actor in (self.front,self.doctor,self.manager,self.fin,self.hq,self.pa,self.tech):
            c=self.client_for(actor)
            self.assertEqual(c.get(reverse('reconciliation_home')).status_code,200 if actor in (self.manager,self.fin,self.hq) else 403)
            self.assertEqual(c.get(reverse('statement_import')).status_code,200 if actor==self.manager else 403)
            self.assertEqual(c.get(reverse('payment_account_new')).status_code,200 if actor==self.fin else 403)
    def test_hq_gets_counts_without_references_or_import_bytes(self):
        self.posted(reference='PRIVATE-REF');line=self.imported(self.raw(reference='PRIVATE-REF'))
        c=self.client_for(self.hq);r=c.get(reverse('reconciliation_home'));self.assertNotContains(r,'PRIVATE-REF');self.assertNotContains(r,'TX-A')
        self.assertEqual(c.get(reverse('statement_batch',args=[line.batch_id])).status_code,403)
    def test_manager_projection_never_displays_patient_or_invoice_details(self):
        entry=self.posted();line=self.imported();row=self.proposed(entry,line)
        patient=entry.invoice.visit.patient;invoice=entry.invoice.invoice_no
        for route in [reverse('reconciliation_home'),reverse('statement_match',args=[line.pk]),reverse('reconciliation_match',args=[row.pk])]:
            r=self.client_for(self.manager).get(route);self.assertEqual(r.status_code,200);self.assertNotContains(r,patient.patient_no);self.assertNotContains(r,patient.name);self.assertNotContains(r,invoice)
    def test_multipart_preview_and_confirm_require_normal_signed_form(self):
        c=self.client_for(self.manager)
        r=c.post(reverse('statement_import'),{'action':'preview','payment_account_id':self.account.pk,'source':SimpleUploadedFile('synthetic.csv',self.raw())})
        self.assertEqual(r.status_code,200);self.assertFalse(StatementLine.objects.exists());self.assertContains(r,'尚未接受流水')
        r=c.post(reverse('statement_import'),{'action':'confirm','proposal_token':r.context['form'].initial['proposal_token'],'confirmed':'on'})
        self.assertEqual(r.status_code,302);self.assertEqual(StatementLine.objects.count(),1)
    def test_read_only_and_csrf_prevent_import(self):
        c=WorkspaceClient(enforce_csrf_checks=True);c.force_login(self.manager);c.get(reverse('statement_import'))
        self.assertEqual(c.post(reverse('statement_import'),{'action':'preview'}).status_code,403)
        with override_settings(ADC_READ_ONLY=True):self.assertEqual(self.client_for(self.manager).post(reverse('statement_import'),{'action':'preview'}).status_code,403)
        self.assertFalse(StatementBatch.objects.exists())
    def test_daily_handover_exposes_separate_channel_status(self):
        from finance.daily_services import prepare_close,confirm_close
        from finance.daily_facts import day_facts
        entry=self.posted();p=prepare_close(actor=self.manager,business_date=self.today,declared=day_facts(self.a.pk,self.today)['totals'],evidence='合成四类凭据',reason='合成交接')
        row=confirm_close(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]
        r=self.client_for(self.manager).get(reverse('daily_close_detail',args=[row.pk]));self.assertContains(r,'渠道对账状态');self.assertContains(r,'次日到账可继续待对账')
