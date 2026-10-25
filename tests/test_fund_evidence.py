"""Shared bank evidence ownership: C6 funds versus the existing R1 match."""
from uuid import uuid4
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, transaction
from django.test import TransactionTestCase, override_settings
from accounts.models import UserAccount, RoleAssignment
from adc_core.rules import RuleError
from finance.cash_models import CashEntry
from finance.fund_models import FundTransfer, StatementUse
from finance import fund_services as svc
from finance.reconciliation_models import ReconciliationMatch
from finance.reconciliation_services import prepare_match, confirm_match
from finance.cash_selectors import invoice_balance
from tests.test_financial_evidence import EvidenceFixture
from tests.test_care_finance_equipment import activate


@override_settings(ADC_CLINICAL_SYNTHETIC=True,ADC_READ_ONLY=False)
class FundEvidenceTests(EvidenceFixture,TransactionTestCase):
    def setUp(self):
        self.setup_evidence()
        self.fin2=UserAccount.objects.create_user(username='fund-independent-reviewer',password='synthetic-only')
        RoleAssignment.objects.create(user=self.fin2,role='FINANCE',scope_kind='CHAIN');activate(self.fin2,'FINANCE')

    def transfer_preview(self,line,**kw):
        d=dict(actor=self.fin,line_id=line.pk,kind='RECEIPT',basis='本地合成基金银行到账核对依据');d.update(kw)
        return svc.prepare_transfer(**d)

    def transfer(self,line,**kw):
        p=self.transfer_preview(line,**kw)
        return svc.confirm_transfer(actor=kw.get('actor',self.fin),proposal_token=p['proposal_token'],confirmed=True)[0]

    def transfer_review(self,row,**kw):
        d=dict(actor=self.fin2,transfer_id=row.pk,decision='approve',reason='另一财务账号核对原银行证据');d.update(kw)
        p=svc.prepare_transfer_review(**d)
        return svc.confirm_transfer_review(actor=d['actor'],proposal_token=p['proposal_token'],confirmed=True)[0]

    def test_preview_does_not_reserve_or_post_money(self):
        line=self.imported();self.transfer_preview(line)
        self.assertFalse(FundTransfer.objects.exists());self.assertFalse(StatementUse.objects.exists());self.assertFalse(CashEntry.objects.exists())

    def test_fund_transfer_has_one_retained_use_and_independent_review(self):
        row=self.transfer(self.imported());use=row.statement_use
        self.assertEqual(use.state,'ACTIVE');self.assertFalse(use.derived_from_existing)
        self.assertEqual(use.created_at,row.prepared_at)
        row=self.transfer_review(row);self.assertEqual(row.state,'CONFIRMED')
        self.assertEqual(StatementUse.objects.count(),1);self.assertFalse(CashEntry.objects.exists())

    def test_reviewed_bank_evidence_does_not_clear_patient_debt_or_increase_revenue(self):
        entry=self.posted();before=invoice_balance(entry.invoice)
        self.transfer_review(self.transfer(self.imported()))
        self.assertEqual(invoice_balance(entry.invoice),before);self.assertEqual(CashEntry.objects.count(),1)

    def test_incoming_and_outgoing_directions_must_agree(self):
        line=self.imported()
        with self.assertRaises(RuleError):self.transfer_preview(line,kind='RETURN')
        outgoing=self.imported(self.raw(transaction_id='OUT-A',direction='OUT'))
        with self.assertRaises(RuleError):self.transfer_preview(outgoing)
        row=self.transfer_review(self.transfer(outgoing,kind='RETURN'));self.assertEqual(row.kind,'RETURN')

    def test_cash_match_reserves_same_bank_line_against_fund_use(self):
        entry=self.posted();line=self.imported();match=self.proposed(entry,line)
        self.assertEqual(match.statement_use.state,'ACTIVE')
        with self.assertRaisesMessage(RuleError,'不能重复使用'):self.transfer_preview(line)
        self.match_review(match)
        with self.assertRaises(RuleError):self.transfer_preview(line)

    def test_fund_pending_use_blocks_r1_match_without_changing_cash(self):
        entry=self.posted();line=self.imported();self.transfer(line)
        with self.assertRaisesMessage(RuleError,'不能重复使用'):self.proposed(entry,line)
        entry.refresh_from_db();self.assertEqual(entry.state,'POSTED');self.assertFalse(ReconciliationMatch.objects.exists())
        from finance.reconciliation_selectors import candidates,dashboard
        self.assertEqual(candidates(self.manager,line),[])
        view=dashboard(self.manager);self.assertEqual(view['unmatched_count'],0);self.assertEqual(view['fund_used_count'],1)

    def test_rejected_fund_use_releases_for_fresh_r1_but_not_old_preview(self):
        entry=self.posted();line=self.imported()
        old=prepare_match(actor=self.manager,line_id=line.pk,entry_id=entry.pk)
        row=self.transfer_review(self.transfer(line),decision='reject')
        self.assertEqual(row.statement_use.state,'RELEASED')
        with self.assertRaisesMessage(RuleError,'用途历史已变化'):
            confirm_match(actor=self.manager,proposal_token=old['proposal_token'],confirmed=True,expected_line_id=line.pk)
        match=self.proposed(entry,line);self.assertEqual(match.statement_use.state,'ACTIVE')
        self.assertEqual(StatementUse.objects.filter(line=line).count(),2)

    def test_rejected_r1_match_releases_for_fund_review(self):
        entry=self.posted();line=self.imported();match=self.proposed(entry,line)
        self.match_review(match,decision='reject');match.refresh_from_db()
        self.assertEqual(match.statement_use.state,'RELEASED')
        self.transfer_review(self.transfer(line))
        self.assertEqual(StatementUse.objects.filter(line=line,state='ACTIVE').count(),1)

    def test_evidence_correction_releases_only_original_matching_use(self):
        entry=self.posted();line=self.imported();match=self.proposed(entry,line);self.match_review(match)
        self.evidence_review(self.amendment(entry))
        match.refresh_from_db();self.assertEqual(match.state,'STALE');self.assertEqual(match.statement_use.state,'RELEASED')
        self.transfer(line);self.assertEqual(StatementUse.objects.filter(line=line,state='ACTIVE').count(),1)

    def test_same_operation_and_review_replay_keep_single_evidence(self):
        line=self.imported();p=self.transfer_preview(line)
        row,_=svc.confirm_transfer(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        self.transfer_review(row)
        replay,repeated=svc.confirm_transfer(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(repeated);self.assertEqual(replay.state,'CONFIRMED');self.assertEqual(FundTransfer.objects.count(),1)
        self.assertEqual(StatementUse.objects.count(),1)

    def test_finance_cannot_self_review_and_other_roles_cannot_submit(self):
        line=self.imported();row=self.transfer(line)
        with self.assertRaises(PermissionDenied):self.transfer_review(row,actor=self.fin)
        for actor in (self.front,self.manager,self.hq,self.doctor,self.pa,self.tech):
            with self.subTest(role=actor._adc_workspace.role):
                with self.assertRaises(PermissionDenied):self.transfer_preview(line,actor=actor)

    def test_revoked_preparer_blocks_approval_but_allows_rejection(self):
        row=self.transfer(self.imported());RoleAssignment.objects.filter(user=self.fin,role='FINANCE').update(is_active=False)
        with self.assertRaises(RuleError):self.transfer_review(row)
        row=self.transfer_review(row,decision='reject');self.assertEqual(row.statement_use.state,'RELEASED')

    def test_revoked_reviewer_after_preview_has_no_effect(self):
        row=self.transfer(self.imported())
        p=svc.prepare_transfer_review(actor=self.fin2,transfer_id=row.pk,decision='approve',reason='合成核对')
        RoleAssignment.objects.filter(user=self.fin2,role='FINANCE').update(is_active=False)
        with self.assertRaises(PermissionDenied):svc.confirm_transfer_review(actor=self.fin2,proposal_token=p['proposal_token'],confirmed=True)
        row.refresh_from_db();self.assertEqual(row.state,'PENDING')

    def test_sql_rejects_cross_workflow_double_use_and_retains_terminal_facts(self):
        entry=self.posted();line=self.imported();self.proposed(entry,line)
        with self.assertRaises(DatabaseError),transaction.atomic():
            FundTransfer.objects.create(line=line,kind='RECEIPT',prepared_by=self.fin,basis='直接绕过命令试图重复使用')
        self.assertFalse(FundTransfer.objects.exists());self.assertEqual(StatementUse.objects.count(),1)
        use=StatementUse.objects.get()
        with self.assertRaises(DatabaseError),transaction.atomic():StatementUse.objects.filter(pk=use.pk).delete()

    def test_bank_evidence_source_and_terminal_review_are_immutable(self):
        row=self.transfer_review(self.transfer(self.imported()))
        for changes in (dict(basis='覆盖来源'),dict(state='REJECTED'),dict(review_reason='覆盖原决定')):
            with self.assertRaises(DatabaseError),transaction.atomic():FundTransfer.objects.filter(pk=row.pk).update(**changes)

    def test_audit_failure_rolls_back_bank_evidence_and_shared_use(self):
        line=self.imported();p=self.transfer_preview(line)
        with patch('finance.fund_services.emit',side_effect=RuntimeError('synthetic audit failure')):
            with self.assertRaises(RuntimeError):svc.confirm_transfer(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(FundTransfer.objects.exists());self.assertFalse(StatementUse.objects.exists())

    def test_concurrent_fund_and_r1_confirm_have_one_winner(self):
        entry=self.posted();line=self.imported()
        fund=self.transfer_preview(line);cash=prepare_match(actor=self.manager,line_id=line.pk,entry_id=entry.pk)
        def call(index):
            try:
                if index==0:svc.confirm_transfer(actor=self.actor_copy(self.fin),proposal_token=fund['proposal_token'],confirmed=True)
                else:confirm_match(actor=self.actor_copy(self.manager),proposal_token=cash['proposal_token'],confirmed=True,expected_line_id=line.pk)
                return 'ok'
            except RuleError:return 'conflict'
        self.assertEqual(sorted(self.race(call)),['conflict','ok'])
        self.assertEqual(StatementUse.objects.filter(line=line,state='ACTIVE').count(),1)
        self.assertEqual(FundTransfer.objects.count()+ReconciliationMatch.objects.count(),1)

    def test_concurrent_fund_confirmations_have_one_winner(self):
        line=self.imported();previews=[self.transfer_preview(line,actor=a) for a in (self.fin,self.fin2)]
        def call(index):
            try:svc.confirm_transfer(actor=self.actor_copy((self.fin,self.fin2)[index]),proposal_token=previews[index]['proposal_token'],confirmed=True);return 'ok'
            except RuleError:return 'conflict'
        self.assertEqual(sorted(self.race(call)),['conflict','ok']);self.assertEqual(FundTransfer.objects.count(),1)

    @override_settings(ADC_CLINICAL_SYNTHETIC=False)
    def test_live_mode_cannot_activate_local_fund_adapter(self):
        p=self.transfer_preview(self.imported())
        with self.assertRaises(PermissionDenied):svc.confirm_transfer(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)

    def test_existing_r1_ownership_is_derived_on_upgrade_without_rewriting_match(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        from finance.cash_evidence_services import effective
        targets=MigrationExecutor(connection).loader.graph.leaf_nodes()
        MigrationExecutor(connection).migrate([('finance','0009_evidence_history_guards')])
        try:
            entry=self.posted();line=self.imported()
            # A pre-increment retained R1 row, validated by the original SQL
            # guards. The current commands require the new ownership table.
            match=ReconciliationMatch.objects.create(cash_entry=entry,evidence=effective(entry.pk),line=line,prepared_by=self.manager)
            before=ReconciliationMatch.objects.values().get(pk=match.pk)
        finally:
            MigrationExecutor(connection).migrate(targets)
        self.assertEqual(ReconciliationMatch.objects.values().get(pk=match.pk),before)
        use=StatementUse.objects.get(cash_match=match)
        self.assertTrue(use.derived_from_existing);self.assertEqual(use.created_at,match.prepared_at)
        with self.assertRaises(RuleError):self.transfer_preview(line)
        self.match_review(match);use.refresh_from_db();self.assertEqual(use.state,'ACTIVE')

    def test_bank_evidence_http_preview_confirm_and_review(self):
        from django.urls import reverse
        line=self.imported();self.client.force_login(self.fin)
        url=reverse('fund_transfer_new',args=[line.pk])
        self.assertContains(self.client.get(url),'核对基金银行到账')
        p=self.client.post(url,dict(action='preview',basis='合成基金用途逐项核对'))
        self.assertEqual(p.status_code,200);self.assertFalse(FundTransfer.objects.exists())
        response=self.client.post(url,dict(action='confirm',proposal_token=p.context['form'].initial['proposal_token'],confirmed='on'))
        row=FundTransfer.objects.get();self.assertRedirects(response,reverse('fund_transfer_detail',args=[row.pk]))
        self.client.force_login(self.fin2);url=reverse('fund_transfer_review',args=[row.pk])
        p=self.client.post(url,dict(action='preview',decision='approve',reason='独立核对合成银行事实'))
        self.assertEqual(p.status_code,200)
        response=self.client.post(url,dict(action='confirm',proposal_token=p.context['form'].initial['proposal_token'],confirmed='on'))
        self.assertRedirects(response,reverse('fund_transfer_detail',args=[row.pk]))
        row.refresh_from_db();self.assertEqual(row.state,'CONFIRMED');self.assertFalse(CashEntry.objects.exists())

    def test_fund_http_role_boundary_and_manager_usage_projection(self):
        from django.urls import reverse
        line=self.imported();row=self.transfer(line)
        for actor in (self.front,self.manager,self.hq,self.doctor,self.pa,self.tech):
            self.client.force_login(actor)
            self.assertEqual(self.client.get(reverse('fund_transfers')).status_code,403)
            self.assertEqual(self.client.get(reverse('fund_transfer_detail',args=[row.pk])).status_code,403)
        self.client.force_login(self.manager)
        response=self.client.get(reverse('statement_batch',args=[line.batch_id]))
        self.assertContains(response,'已用于基金办理');self.assertNotContains(response,'核对基金银行用途')
