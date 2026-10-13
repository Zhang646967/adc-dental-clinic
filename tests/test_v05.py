"""v0.5 PostgreSQL tests. Authored, not executed in dependency-limited build runtime."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError,transaction
from django.test import TransactionTestCase,override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from adc_core.rules import RuleError
from finance.models import Quarter,DentistQuarterCost
from finance import services as fs
from finance.selectors import quarter_report
from care.models import Invoice,CorrectionRequest,VisitRecordVersion,AuditEvent
from care.corrections import request_line_correction,review_correction
from operations.selectors import operation_report
from scheduling.models import Visit
from scheduling.services import change_appointment
from tests.test_v04 import V04Fixture
D=Decimal

class V05Fixture(V04Fixture):
    def setup05(self):
        self.set_up_v04()
        self.fin=UserAccount.objects.create_user(username='fin05',password='synthetic-test-only')
        self.hq=UserAccount.objects.create_user(username='hq05',password='synthetic-test-only')
        RoleAssignment.objects.create(user=self.fin,role='FINANCE',scope_kind='CHAIN')
        RoleAssignment.objects.create(user=self.hq,role='HQ',scope_kind='CHAIN')
    def make_quarter(self):
        now=timezone.localdate()
        return fs.create_quarter(actor=self.fin,year=now.year,quarter_no=(now.month-1)//3+1)
    def member(self,q,dentist=None):
        q.refresh_from_db()
        return fs.add_member(actor=self.fin,quarter_id=q.pk,expected_version=q.lock_version,dentist_id=(dentist or self.d1).pk)
    def savecost(self,q,c,amount='10',operating='20'):
        q.refresh_from_db()
        return fs.save_cost(actor=self.fin,quarter_id=q.pk,cost_id=c.pk,expected_version=q.lock_version,supply_cost=D(amount),operating_expense=D(operating),notes='合成测试凭据')
    def confirmcost(self,q,c):
        q.refresh_from_db();return fs.confirm_cost(actor=self.fin,quarter_id=q.pk,cost_id=c.pk,expected_version=q.lock_version)
    def roster(self,q):
        q.refresh_from_db();return fs.confirm_roster(actor=self.fin,quarter_id=q.pk,expected_version=q.lock_version)
    def billed(self):
        v=self.arrived();self.review(v);self.line(v,quantity=D('2'));return v,self.finish(v)
    def correction(self):
        v,i=self.billed();v.refresh_from_db();line=i.current_record_version.treatment_lines.first()
        req=request_line_correction(actor=self.doctor,visit_id=v.pk,expected_version=v.lock_version,line_id=line.pk,quantity=D('1'),unit_price=D('99.99'),reason='数量误录：实际一单位')
        return v,i,req

class FinancialAcceptanceTests(V05Fixture,TransactionTestCase):
    def setUp(self):self.setup05()
    def test_quarter_create_idempotent(self):self.assertEqual(self.make_quarter().pk,self.make_quarter().pk)
    def test_hq_has_no_write_permission(self):
        with self.assertRaises(PermissionDenied):fs.create_quarter(actor=self.hq,year=2026,quarter_no=3)
    def test_front_has_no_financial_read(self):
        q=self.make_quarter()
        with self.assertRaises(PermissionDenied):quarter_report(self.front,q.pk)
    def test_hq_read_works(self):
        q=self.make_quarter();self.assertEqual(quarter_report(self.hq,q.pk).id,q.pk)
    def test_membership_invalidates_roster(self):
        q=self.make_quarter();self.member(q);self.roster(q);self.member(q,self.d2);q.refresh_from_db();self.assertEqual(q.roster_status,'DRAFT');self.assertIsNone(q.roster_confirmed_at)
    def test_missing_cost_blocks_profit(self):
        q=self.make_quarter();self.member(q);self.roster(q);r=quarter_report(self.fin,q.pk);self.assertIsNone(r.result.profit)
    def test_explicit_zero_is_confirmed(self):
        q=self.make_quarter();c=self.member(q);self.savecost(q,c,'0','0');self.confirmcost(q,c);self.roster(q);r=quarter_report(self.fin,q.pk);self.assertTrue(r.result.ready);self.assertEqual(r.result.profit,D('0'));self.assertIsNone(r.result.fund)
    def test_cannot_confirm_missing(self):
        q=self.make_quarter();c=self.member(q)
        with self.assertRaises(RuleError):self.confirmcost(q,c)
    def test_edit_resets_cost_confirmation(self):
        q=self.make_quarter();c=self.member(q);self.savecost(q,c);self.confirmcost(q,c);self.savecost(q,c,'30');c.refresh_from_db();self.assertEqual(c.cost_status,'DRAFT');self.assertIsNone(c.confirmed_by)
    def test_stale_cost_form_rejected(self):
        q=self.make_quarter();c=self.member(q);q.refresh_from_db();old=q.lock_version;self.savecost(q,c)
        with self.assertRaises(RuleError):fs.save_cost(actor=self.fin,quarter_id=q.pk,cost_id=c.pk,expected_version=old,supply_cost=D('90'),operating_expense=D('20'),notes='过期表单')
    def test_finance_revocation_rechecked(self):
        q=self.make_quarter();c=self.member(q);RoleAssignment.objects.filter(user=self.fin).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.savecost(q,c)
    @override_settings(ADC_READ_ONLY=True)
    def test_readonly_finance_service(self):
        with self.assertRaises(PermissionDenied):self.make_quarter()
    def test_unlisted_earner_blocks_report(self):
        v,i=self.billed();q=self.make_quarter();c=self.member(q,self.d2);self.savecost(q,c,'0','0');self.confirmcost(q,c)
        r=quarter_report(self.fin,q.pk);self.assertIn(self.d1.pk,r.result.off_roster_ids);self.assertFalse(r.result.ready)
    def test_unlisted_earner_blocks_roster_confirmation(self):
        self.billed();q=self.make_quarter();self.member(q,self.d2)
        with self.assertRaises(RuleError):self.roster(q)
    def test_multiple_treatment_rows_do_not_duplicate_cost(self):
        v=self.arrived();self.review(v);self.line(v,D('1'));self.line(v,D('1'));self.finish(v)
        q=self.make_quarter();c=self.member(q);self.savecost(q,c);self.confirmcost(q,c);self.roster(q)
        r=quarter_report(self.fin,q.pk);self.assertEqual(r.result.income,D('199.98'));self.assertEqual(r.result.supply,D('10'));self.assertEqual(r.result.profit,D('169.98'))
    def test_zero_income_dentist_cost_retained(self):
        self.billed();q=self.make_quarter();c=self.member(q);self.savecost(q,c,'0','0');self.confirmcost(q,c);c2=self.member(q,self.d2);self.savecost(q,c2,'50','50');self.confirmcost(q,c2);self.roster(q)
        self.assertEqual(quarter_report(self.fin,q.pk).result.profit,D('99.98'))
    def test_audit_failure_rolls_back_cost(self):
        q=self.make_quarter();c=self.member(q)
        with patch('finance.services.emit',side_effect=RuntimeError('test audit failure')):
            with self.assertRaises(RuntimeError):self.savecost(q,c)
        c.refresh_from_db();self.assertEqual(c.cost_status,'MISSING');self.assertIsNone(c.supply_cost)
    def test_cross_quarter_cost_not_editable(self):
        q=self.make_quarter();c=self.member(q);other=fs.create_quarter(actor=self.fin,year=2000,quarter_no=1)
        with self.assertRaises(DentistQuarterCost.DoesNotExist):fs.save_cost(actor=self.fin,quarter_id=other.pk,cost_id=c.pk,expected_version=other.lock_version,supply_cost=D('1'),operating_expense=D('2'),notes='错误归属')
    def test_finance_pages_and_export(self):
        q=self.make_quarter();c=self.member(q);self.client.force_login(self.fin)
        for name,kw in [('finance_quarters',{}),('quarter_detail',{'pk':q.pk}),('quarter_cost',{'pk':q.pk,'cost_pk':c.pk}),('quarter_export',{'pk':q.pk})]:
            with self.subTest(route=name):self.assertEqual(self.client.get(reverse(name,kwargs=kw)).status_code,200)
    def test_csv_does_not_include_patient_phone(self):
        self.billed();q=self.make_quarter();self.client.force_login(self.fin)
        content=self.client.get(reverse('quarter_export',args=[q.pk])).content.decode('utf-8-sig')
        self.assertNotIn(self.p1.name,content);self.assertNotIn(self.p1.patient_no,content)
    def test_report_snapshot_is_readonly(self):
        from adc_core.snapshots import reporting_snapshot
        from django.db import DatabaseError
        with self.assertRaises(DatabaseError):
            with reporting_snapshot():Quarter.objects.create(year=1999,quarter_no=1)
    def test_cost_negative_rejected(self):
        q=self.make_quarter();c=self.member(q)
        with self.assertRaises(RuleError):self.savecost(q,c,'-1')
    def test_duplicate_member_rejected(self):
        q=self.make_quarter();self.member(q)
        with self.assertRaises(RuleError):self.member(q)
    def test_inactive_historical_dentist_can_be_included(self):
        self.d2.is_active=False;self.d2.save();q=self.make_quarter();c=self.member(q,self.d2);self.assertEqual(c.dentist_id,self.d2.pk)

class CorrectionAcceptanceTests(V05Fixture,TransactionTestCase):
    def setUp(self):self.setup05()
    def test_request_does_not_publish(self):
        v,i,r=self.correction();i.refresh_from_db();self.assertEqual(i.current_record_version.revision_no,1);self.assertEqual(r.new_version.state,'DRAFT')
    def test_approval_one_invoice_two_versions(self):
        v,i,r=self.correction();old=i.current_record_version_id;review_correction(actor=self.fin,request_id=r.pk,decision='approve',reason='已核对数量');i.refresh_from_db()
        self.assertNotEqual(old,i.current_record_version_id);self.assertEqual(Invoice.objects.count(),1);self.assertEqual(i.current_record_version.total_amount,D('99.99'));self.assertEqual(VisitRecordVersion.objects.filter(state='PUBLISHED').count(),2)
    def test_approval_preserves_original(self):
        v,i,r=self.correction();old=i.current_record_version;review_correction(actor=self.fin,request_id=r.pk,decision='approve',reason='核对');old.refresh_from_db();self.assertEqual(old.total_amount,D('199.98'));self.assertEqual(old.state,'PUBLISHED')
    def test_approval_retry_idempotent(self):
        v,i,r=self.correction();a=review_correction(actor=self.fin,request_id=r.pk,decision='approve',reason='核对');b=review_correction(actor=self.fin,request_id=r.pk,decision='approve',reason='重试');self.assertEqual(a.pk,b.pk);self.assertEqual(VisitRecordVersion.objects.count(),2)
    def test_self_approval_denied_even_with_finance_role(self):
        v,i,r=self.correction();RoleAssignment.objects.create(user=self.doctor,role='FINANCE',scope_kind='CHAIN')
        with self.assertRaises(RuleError):review_correction(actor=self.doctor,request_id=r.pk,decision='approve',reason='自审')
    def test_front_cannot_review(self):
        v,i,r=self.correction()
        with self.assertRaises(PermissionDenied):review_correction(actor=self.front,request_id=r.pk,decision='approve',reason='越权')
    def test_preparer_revoked_blocks_approval(self):
        v,i,r=self.correction();RoleAssignment.objects.filter(user=self.doctor).update(is_active=False)
        with self.assertRaises(RuleError):review_correction(actor=self.fin,request_id=r.pk,decision='approve',reason='核对')
    def test_reject_preserves_current_and_abandons_draft(self):
        v,i,r=self.correction();review_correction(actor=self.fin,request_id=r.pk,decision='reject',reason='依据不足');i.refresh_from_db();r.refresh_from_db()
        self.assertEqual(i.current_record_version.revision_no,1);self.assertEqual(r.status,'REJECTED');self.assertEqual(r.new_version.state,'ABANDONED')
    def test_front_cannot_request(self):
        v,i=self.billed();v.refresh_from_db()
        with self.assertRaises(PermissionDenied):request_line_correction(actor=self.front,visit_id=v.pk,expected_version=v.lock_version,line_id=i.current_record_version.treatment_lines.first().pk,quantity=D('1'),unit_price=D('99.99'),reason='越权')
    def test_noop_request_rejected(self):
        v,i=self.billed();v.refresh_from_db()
        with self.assertRaises(RuleError):request_line_correction(actor=self.doctor,visit_id=v.pk,expected_version=v.lock_version,line_id=i.current_record_version.treatment_lines.first().pk,quantity=D('2'),unit_price=D('99.99'),reason='未改动')
    def test_duplicate_open_request_rejected(self):
        v,i,r=self.correction();v.refresh_from_db()
        with self.assertRaises(RuleError):request_line_correction(actor=self.doctor,visit_id=v.pk,expected_version=v.lock_version,line_id=i.current_record_version.treatment_lines.first().pk,quantity=D('1.5'),unit_price=D('99.99'),reason='第二请求')
    def test_audit_failure_rolls_back_publication(self):
        v,i,r=self.correction()
        with patch('care.corrections.emit',side_effect=RuntimeError('test failure')):
            with self.assertRaises(RuntimeError):review_correction(actor=self.fin,request_id=r.pk,decision='approve',reason='核对')
        i.refresh_from_db();r.refresh_from_db();self.assertEqual(i.current_record_version.revision_no,1);self.assertEqual(r.status,'OPEN')
    def test_restatement_counts_only_current_version(self):
        v,i,r=self.correction();review_correction(actor=self.fin,request_id=r.pk,decision='approve',reason='核对');q=self.make_quarter();c=self.member(q);self.savecost(q,c,'0','0');self.confirmcost(q,c);self.roster(q)
        self.assertEqual(quarter_report(self.fin,q.pk).result.income,D('99.99'))
    def test_cannot_roll_back_invoice_pointer_directly(self):
        v,i,r=self.correction();old=i.current_record_version_id;review_correction(actor=self.fin,request_id=r.pk,decision='approve',reason='核对')
        with self.assertRaises(IntegrityError),transaction.atomic():Invoice.objects.filter(pk=i.pk).update(current_record_version_id=old)
    def test_applied_request_immutable_in_database(self):
        v,i,r=self.correction();review_correction(actor=self.fin,request_id=r.pk,decision='approve',reason='核对')
        with self.assertRaises(IntegrityError),transaction.atomic():CorrectionRequest.objects.filter(pk=r.pk).update(reason='覆盖历史')
    def test_patient_historical_invoice_access(self):
        v,i,r=self.correction();review_correction(actor=self.fin,request_id=r.pk,decision='approve',reason='核对');self.client.force_login(self.pa)
        response=self.client.get(reverse('portal_invoice',args=[i.pk])+'?revision=1');self.assertEqual(response.status_code,200);self.assertContains(response,'历史版本')
    def test_patient_cannot_see_draft_revision(self):
        v,i,r=self.correction();self.client.force_login(self.pa)
        self.assertEqual(self.client.get(reverse('portal_invoice',args=[i.pk])+'?revision=2').status_code,404)
    def test_another_patient_cannot_read_history(self):
        v,i,r=self.correction();self.client.force_login(self.pb);self.assertEqual(self.client.get(reverse('portal_invoice',args=[i.pk])+'?revision=1').status_code,404)
    def test_finance_correction_pages(self):
        v,i,r=self.correction();self.client.force_login(self.fin)
        self.assertEqual(self.client.get(reverse('corrections')).status_code,200);self.assertEqual(self.client.get(reverse('correction_detail',args=[r.pk])).status_code,200)
    def test_finance_cannot_read_care_workspace(self):
        v,i,r=self.correction();self.client.force_login(self.fin);self.assertEqual(self.client.get(reverse('care_workspace',args=[v.pk])).status_code,403)

class OperationsAcceptanceTests(V05Fixture,TransactionTestCase):
    def setUp(self):self.setup05()
    def report(self,actor=None,clinic=None,as_of=None):
        day=timezone.localtime(self.t).date()
        with patch('operations.selectors.timezone.now',return_value=as_of or self.t+timedelta(hours=5)):
            return operation_report(actor or self.hq,day,day,clinic)
    def test_future_not_denominator(self):
        self.book();r=self.report(as_of=self.t-timedelta(hours=1));self.assertEqual(r['future'],1);self.assertEqual(r['metrics'].denominator,0)
    def test_due_unresolved_is_pending(self):
        self.book();r=self.report();self.assertEqual(r['metrics'].pending,1);self.assertIsNone(r['metrics'].cancel_rate)
    def test_clinic_cancel_not_patient_failure(self):
        v=self.book();change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='cancel',party='CLINIC',reason='停诊');r=self.report();self.assertEqual(r['metrics'].clinic_cancel,1);self.assertEqual(r['metrics'].denominator,0)
    def test_no_treatment_is_arrival(self):
        v=self.arrived();self.finish(v,'NO_TREATMENT','未实施治疗');self.assertEqual(self.report()['metrics'].arrived,1)
    def test_manager_cannot_select_other_clinic(self):
        with self.assertRaises(PermissionDenied):self.report(actor=self.manager,clinic=self.b.pk)
    def test_technical_admin_no_operational_bypass(self):
        with self.assertRaises(PermissionDenied):self.report(actor=self.tech)
    def test_patient_no_operational_access(self):
        with self.assertRaises(PermissionDenied):self.report(actor=self.pa)
    def test_manager_summary_omits_other_clinic(self):
        self.book(slot_id=self.slot2.pk);r=self.report(actor=self.manager);self.assertEqual(len(r['rows']),1);self.assertEqual(r['metrics'].pending,0)
    def test_aggregate_contains_no_patient_identity(self):
        self.book();r=self.report();self.assertNotIn(self.p1.patient_no,str(r));self.assertNotIn(self.p1.name,str(r))
    def test_operation_page_renders(self):
        self.client.force_login(self.hq);response=self.client.get(reverse('operations_dashboard'));self.assertEqual(response.status_code,200)
    def test_operation_invalid_date_filter(self):
        self.client.force_login(self.hq);response=self.client.get(reverse('operations_dashboard'),{'start':'invalid','end':'2026-09-30'});self.assertEqual(response.status_code,200);self.assertContains(response,'errorlist')
