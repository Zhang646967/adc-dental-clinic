"""Daily reconciliation: real PostgreSQL, signed HTTP, history and concurrency."""
from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import patch
from uuid import uuid4
from django.core.exceptions import PermissionDenied
from django.db import transaction, IntegrityError, connection
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount, RoleAssignment
from adc_core.rules import RuleError
from care.models import AuditEvent
from finance.daily_models import DailyClose
from finance.daily_facts import day_facts, KINDS
from finance.daily_services import (prepare_close,confirm_close,prepare_close_review,confirm_close_review,blocker,close_scope)
from finance.cash_services import prepare_cash,confirm_cash_request,prepare_review,confirm_cash_review
from tests.test_care_finance_equipment import CFEFixture,activate
from tests.workspace_client import WorkspaceClient

class DailyCloseTests(CFEFixture,TransactionTestCase):
    def setUp(self):self.setup_cfe()
    def preview(self,**kw):
        data=dict(actor=self.manager,business_date=self.today,declared=day_facts(self.a.pk,self.today)['totals'],evidence='SYNTHETIC-DAY-001 四类凭据',reason='合成营业日交接')
        data.update(kw);return prepare_close(**data)
    def submit(self,**kw):
        p=self.preview(**kw)
        return confirm_close(actor=kw.get('actor',self.manager),proposal_token=p['proposal_token'],confirmed=True)[0]
    def decision_preview(self,row,**kw):
        data=dict(actor=self.fin,close_id=row.pk,decision='approve',reason='合成独立核实四类凭据')
        data.update(kw);return prepare_close_review(**data)
    def decide(self,row,**kw):
        p=self.decision_preview(row,**kw)
        return confirm_close_review(actor=kw.get('actor',self.fin),proposal_token=p['proposal_token'],confirmed=True)[0]
    def client_for(self,user):
        c=WorkspaceClient(enforce_csrf_checks=True);c.force_login(user);return c
    def test_preview_no_business_mutation(self):
        before=AuditEvent.objects.count();self.preview()
        self.assertFalse(DailyClose.objects.exists());self.assertEqual(AuditEvent.objects.count(),before)
    def test_four_legs_use_posted_facts_not_bills_or_pending(self):
        v,invoice=self.billed();self.approve(self.cash(invoice,amount='100.01'));self.approve(self.cash(invoice,kind='REFUND',amount='20.01'))
        a=self.asset(acquisition_cost='9.99');expense=self.approve(self.expense(a))
        p=prepare_cash(actor=self.manager,source_type='equipment',source_id=expense.equipment_event_id,kind='EXPENSE_REVERSAL',reversal_id=expense.pk,occurred_on=self.today,reason='合成冲回',**self.evidence())
        self.approve(confirm_cash_request(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0])
        row=self.decide(self.submit());self.assertEqual(row.snapshot['totals'],dict(zip(KINDS,['100.01','20.01','9.99','9.99'])));self.assertEqual(row.state,'APPROVED')
    def test_pending_blocks_approval_and_is_not_posted_total(self):
        a=self.asset();self.expense(a);row=self.submit()
        self.assertEqual(row.snapshot['pending'],1);self.assertEqual(row.snapshot['totals']['EQUIPMENT_EXPENSE'],'0.00')
        with self.assertRaises(RuleError):self.decide(row)
    def test_offsetting_differences_cannot_hide_in_net(self):
        values={k:'0.00' for k in KINDS};values.update(RECEIPT='10.00',REFUND='10.00')
        row=self.submit(declared=values)
        with self.assertRaises(RuleError):self.decide(row)
        row.refresh_from_db();self.assertEqual(row.state,'PENDING')
    def test_rejection_new_version_then_independent_handover(self):
        values={k:'0.00' for k in KINDS};values['REFUND']='1.00';first=self.submit(declared=values)
        self.decide(first,decision='reject');second=self.decide(self.submit(reason='合成差异回查后重新核对'))
        self.assertEqual((second.version,second.previous_id,second.state),(2,first.pk,'APPROVED'))
        first.refresh_from_db();self.assertEqual(first.declared['REFUND'],'1.00');self.assertEqual(first.state,'REJECTED')
    def test_late_posting_marks_prior_approval_stale_without_rewrite(self):
        old=self.decide(self.submit());snapshot=old.snapshot
        self.approve(self.expense(self.asset()));old.refresh_from_db()
        self.assertEqual(old.snapshot,snapshot);self.assertNotEqual(old.snapshot,day_facts(self.a.pk,self.today))
        new=self.decide(self.submit(reason='晚到设备付款重新核对'));self.assertEqual(new.previous_id,old.pk)
    def test_occurred_date_instead_of_approval_date(self):
        day=self.today-timedelta(days=1);a=self.asset();event=a.events.get(sequence=0)
        p=prepare_cash(actor=self.manager,source_type='equipment',source_id=event.pk,kind='EQUIPMENT_EXPENSE',occurred_on=day,reason='合成晚到付款',**self.evidence())
        self.approve(confirm_cash_request(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0])
        self.assertEqual(day_facts(self.a.pk,day)['totals']['EQUIPMENT_EXPENSE'],'500.00');self.assertEqual(day_facts(self.a.pk,self.today)['posted_count'],0)
    def test_stale_request_and_stale_review_fail(self):
        p=self.preview();self.expense(self.asset())
        with self.assertRaises(RuleError):confirm_close(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        row=self.submit();self.decide(row,decision='reject')
        cash=self.asset(asset_code='SECOND');self.approve(self.expense(cash))
        # Existing first pending cash still blocks; settle it before testing the review race.
        from finance.cash_models import CashEntry
        self.approve(CashEntry.objects.get(state='PENDING'))
        row=self.submit();review=self.decision_preview(row);self.expense(self.asset(asset_code='THIRD'))
        with self.assertRaises(RuleError):confirm_close_review(actor=self.fin,proposal_token=review['proposal_token'],confirmed=True)
    def test_only_one_pending_version(self):
        self.submit()
        with self.assertRaises(RuleError):self.preview()
    def test_successful_request_replay_returns_later_state(self):
        p=self.preview();row=confirm_close(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0];self.decide(row)
        got,repeated=confirm_close(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(repeated);self.assertEqual(got.state,'APPROVED');self.assertEqual(DailyClose.objects.count(),1)
    def test_review_replay_and_conflicting_decision(self):
        row=self.submit();p=self.decision_preview(row);reject=self.decision_preview(row,decision='reject')
        confirm_close_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        got,repeated=confirm_close_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(repeated)
        with self.assertRaises(RuleError):confirm_close_review(actor=self.fin,proposal_token=reject['proposal_token'],confirmed=True)
    def test_same_person_switching_roles_cannot_review(self):
        row=self.submit();RoleAssignment.objects.create(user=self.manager,role='FINANCE',scope_kind='CHAIN');activate(self.manager,'FINANCE')
        with self.assertRaises(RuleError):self.decision_preview(row,actor=self.manager)
    def test_revoked_preparer_blocks_approval_allows_rejection(self):
        row=self.submit();p=self.decision_preview(row);RoleAssignment.objects.filter(user=self.manager,role='MANAGER').update(is_active=False)
        with self.assertRaises(RuleError):confirm_close_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(self.decide(row,decision='reject').state,'REJECTED')
    def test_inactive_preparer_blocks_approval(self):
        row=self.submit();UserAccount.objects.filter(pk=self.manager.pk).update(is_active=False)
        with self.assertRaises(RuleError):self.decision_preview(row)
    def test_revoked_reviewer_cannot_confirm(self):
        row=self.submit();p=self.decision_preview(row);RoleAssignment.objects.filter(user=self.fin,role='FINANCE').update(is_active=False)
        with self.assertRaises(PermissionDenied):confirm_close_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
    def test_other_roles_cannot_prepare(self):
        for actor in (self.front,self.fin,self.hq,self.doctor,self.pa,self.tech):
            with self.assertRaises(PermissionDenied):self.preview(actor=actor)
    def test_current_clinic_scope_and_stale_context(self):
        p=self.preview();row=confirm_close(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]
        RoleAssignment.objects.create(user=self.manager,role='MANAGER',scope_kind='CLINIC',clinic=self.b);activate(self.manager,'MANAGER',self.b)
        self.assertFalse(close_scope(self.manager).filter(pk=row.pk).exists())
        with self.assertRaises(RuleError):confirm_close(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
    @override_settings(ADC_READ_ONLY=True)
    def test_readonly_rejects_direct_write(self):
        p=self.preview()
        with self.assertRaises(PermissionDenied):confirm_close(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
    def test_invalid_dates_money_evidence(self):
        for day in (self.today+timedelta(days=1),'bad',True):
            with self.assertRaises(RuleError):self.preview(business_date=day)
        for value in ('-1','0.001','NaN','Infinity',True,1.1):
            data={k:'0.00' for k in KINDS};data['RECEIPT']=value
            with self.assertRaises(RuleError):self.preview(declared=data)
        for value in ('',' ', 'x'*501):
            with self.assertRaises(RuleError):self.preview(evidence=value)
        with self.assertRaises(RuleError):self.preview(declared={'RECEIPT':'0.00'})
    def test_explicit_confirmation_route_and_signature_required(self):
        p=self.preview()
        with self.assertRaises(RuleError):confirm_close(actor=self.manager,proposal_token=p['proposal_token'],confirmed=False)
        with self.assertRaises(RuleError):confirm_close(actor=self.manager,proposal_token=p['proposal_token']+'x',confirmed=True)
        row=self.submit();p=self.decision_preview(row)
        with self.assertRaises(RuleError):confirm_close_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True,expected_close_id=row.pk+1)
    def test_audit_failure_rolls_back_request_and_review(self):
        p=self.preview()
        with patch('finance.daily_services.emit',side_effect=RuntimeError('synthetic audit failure')):
            with self.assertRaises(RuntimeError):confirm_close(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(DailyClose.objects.exists());row=self.submit();p=self.decision_preview(row)
        with patch('finance.daily_services.emit',side_effect=RuntimeError('synthetic audit failure')):
            with self.assertRaises(RuntimeError):confirm_close_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        row.refresh_from_db();self.assertEqual(row.state,'PENDING')
    def test_audit_does_not_store_raw_evidence(self):
        self.decide(self.submit(evidence='PRIVATE_SYNTHETIC_REFERENCE'))
        self.assertNotIn('PRIVATE_SYNTHETIC_REFERENCE',str(list(AuditEvent.objects.values('reason','change_summary'))))
    def test_sql_protects_prepared_and_terminal_facts(self):
        row=self.submit()
        for values in ({'reason':'rewrite'},{'business_date':self.today-timedelta(days=1)},{'declared':{k:'1.00' for k in KINDS}}):
            with self.assertRaises(IntegrityError),transaction.atomic():DailyClose.objects.filter(pk=row.pk).update(**values)
        self.decide(row)
        with self.assertRaises(IntegrityError),transaction.atomic():DailyClose.objects.filter(pk=row.pk).update(review_reason='rewrite')
        with self.assertRaises(IntegrityError),transaction.atomic():DailyClose.objects.filter(pk=row.pk).delete()
    def test_sql_rejects_approval_with_difference_or_self_review(self):
        values={k:'0.00' for k in KINDS};values['RECEIPT']='1.00';row=self.submit(declared=values)
        for actor in (self.manager,self.fin):
            with self.assertRaises(IntegrityError),transaction.atomic():DailyClose.objects.filter(pk=row.pk).update(state='APPROVED',lock_version=1,reviewed_by=actor,reviewed_at=timezone.now(),review_reason='direct')
    def test_sql_rejects_forged_snapshot_and_lineage(self):
        fields=dict(operation_id=uuid4(),clinic=self.a,business_date=self.today,version=1,prepared_by=self.manager,declared={k:'0.00' for k in KINDS},evidence='synthetic',reason='synthetic')
        with self.assertRaises(IntegrityError),transaction.atomic():DailyClose.objects.create(snapshot={},**fields)
        fields['version']=2
        with self.assertRaises(IntegrityError),transaction.atomic():DailyClose.objects.create(snapshot=day_facts(self.a.pk,self.today),**fields)
    def test_sql_and_python_snapshot_match(self):
        self.approve(self.expense(self.asset()))
        with connection.cursor() as c:
            c.execute('SELECT adc_daily_facts(%s,%s)',[self.a.pk,self.today]);value=c.fetchone()[0]
        import json
        self.assertEqual(json.loads(value) if isinstance(value,str) else value,day_facts(self.a.pk,self.today))
    def test_concurrent_duplicate_request_one_history(self):
        p=self.preview();results=self.race(lambda i:confirm_close(actor=self.actor_copy(self.manager),proposal_token=p['proposal_token'],confirmed=True))
        self.assertEqual(sorted(r[1] for r in results),[False,True]);self.assertEqual(DailyClose.objects.count(),1)
    def test_concurrent_duplicate_review_one_decision(self):
        row=self.submit();p=self.decision_preview(row)
        results=self.race(lambda i:confirm_close_review(actor=self.actor_copy(self.fin),proposal_token=p['proposal_token'],confirmed=True))
        self.assertEqual(sorted(r[1] for r in results),[False,True])
    def test_concurrent_cash_submission_and_close_review(self):
        row=self.submit();p=self.decision_preview(row);asset=self.asset();event=asset.events.get(sequence=0)
        cash=prepare_cash(actor=self.manager,source_type='equipment',source_id=event.pk,kind='EQUIPMENT_EXPENSE',occurred_on=self.today,reason='合成并发付款',**self.evidence())
        def run(i):
            try:
                if i:return confirm_cash_request(actor=self.actor_copy(self.manager),proposal_token=cash['proposal_token'],confirmed=True)[0].state
                return confirm_close_review(actor=self.actor_copy(self.fin),proposal_token=p['proposal_token'],confirmed=True)[0].state
            except RuleError:return 'STALE'
        results=self.race(run);self.assertEqual(results[1],'PENDING');self.assertIn(results[0],('APPROVED','STALE'))
        row.refresh_from_db();self.assertNotEqual(row.snapshot,day_facts(self.a.pk,self.today))
    def test_http_roles_read_and_write_boundary(self):
        row=self.submit()
        for actor,allowed in ((self.manager,True),(self.fin,True),(self.hq,True),(self.front,False),(self.doctor,False),(self.pa,False),(self.tech,False)):
            client=self.client_for(actor);response=client.get(reverse('daily_close_list'));self.assertEqual(response.status_code,200 if allowed else 403)
            if allowed:self.assertEqual(client.get(reverse('daily_close_detail',args=[row.pk])).status_code,200)
            if actor!=self.manager:self.assertEqual(client.get(reverse('daily_close_request')).status_code,403)
            if actor!=self.fin:self.assertEqual(client.get(reverse('daily_close_review',args=[row.pk])).status_code,403)
    def test_http_csrf_stale_workspace_and_get_safety(self):
        c=self.client_for(self.manager);url=reverse('daily_close_request');before=AuditEvent.objects.count();response=c.get(url)
        self.assertContains(response,'type="date"');self.assertFalse(DailyClose.objects.exists());self.assertEqual(before,AuditEvent.objects.count())
        self.assertEqual(c.post(url,{'action':'preview'}).status_code,403)
        self.assertIn(c.post(url,{'action':'preview','csrfmiddlewaretoken':c.cookies['csrftoken'].value,'workspace_token':'bad'}).status_code,(403,409))
    def test_http_approval_stale_warning_and_aggregate_only(self):
        v,invoice=self.billed();self.approve(self.cash(invoice));row=self.decide(self.submit());self.expense(self.asset())
        c=self.client_for(self.manager);response=c.get(reverse('daily_close_detail',args=[row.pk]));self.assertContains(response,'现金账已变化')
        self.assertNotContains(response,invoice.invoice_no);self.assertNotContains(response,'/invoices/')
        self.assertContains(c.get(reverse('daily_close_list')),'需重新核对')
    def test_http_invalid_filters_and_cross_clinic_404(self):
        c=self.client_for(self.fin)
        for suffix in ('?day=bad','?state=bad'):self.assertEqual(c.get(reverse('daily_close_list')+suffix).status_code,400)
        row=self.submit();other=UserAccount.objects.create_user(username='day-other-manager');RoleAssignment.objects.create(user=other,role='MANAGER',scope_kind='CLINIC',clinic=self.b)
        c=self.client_for(other);self.assertEqual(c.get(reverse('daily_close_detail',args=[row.pk])).status_code,404)

    def test_inactive_clinic_cannot_approve_but_can_reject(self):
        row=self.submit();p=self.decision_preview(row);type(self.a).objects.filter(pk=self.a.pk).update(is_active=False)
        with self.assertRaises(RuleError):confirm_close_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(self.decide(row,decision='reject').state,'REJECTED')
    def test_signed_zero_normalizes_to_explicit_zero(self):
        row=self.decide(self.submit(declared={k:'-0.00' for k in KINDS}))
        self.assertEqual(row.declared,{k:'0.00' for k in KINDS})
