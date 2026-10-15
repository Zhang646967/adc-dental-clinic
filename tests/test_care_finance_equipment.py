"""Executed only by the real PostgreSQL gate; synthetic actors and business facts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal as D
from threading import Barrier
from unittest.mock import patch
import time
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction,IntegrityError,connections,close_old_connections
from django.test import TransactionTestCase,override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from care.models import Invoice,AuditEvent,VisitRecordVersion
from care.services import save_clinical_note
from care.progress import care_progress
from care.corrections import request_line_correction,review_correction
from equipment.models import EquipmentAsset,EquipmentEvent
from equipment.services import prepare_registration,prepare_change,confirm_equipment,CONTRACT
from equipment.selectors import equipment_listing,equipment_detail
from finance.cash_models import CashEntry
from finance.cash_services import prepare_cash,confirm_cash_request,prepare_review,confirm_cash_review,REQUEST,REVIEW
from finance.cash_selectors import invoice_balance,cash_listing,cash_detail,receivables,event_net
from finance.selectors import quarter_report
from scheduling.models import Visit
from workspaces.models import WorkspaceContext
from tests.test_v05 import V05Fixture
from tests.workspace_client import WorkspaceClient

def activate(actor,role,clinic=None):
    actor._adc_workspace=WorkspaceContext.objects.create(user=actor,role=role,clinic=clinic,revision=1)

class CFEFixture(V05Fixture):
    def setup_cfe(self):
        self.setup05()
        self.today=timezone.localdate()
        for actor,role,clinic in [(self.front,'FRONT_DESK',self.a),(self.front2,'FRONT_DESK',self.b),
                (self.manager,'MANAGER',self.a),(self.doctor,'DENTIST',None),(self.fin,'FINANCE',None),
                (self.hq,'HQ',None),(self.pa,'PATIENT',None),(self.tech,'SYSADMIN',None)]:
            activate(actor,role,clinic)
    def register_preview(self,**kwargs):
        data=dict(actor=self.manager,asset_code='EQ-1',name='合成牙椅',category='CHAIR',location='演示一区',
            acquired_on=self.today-timedelta(days=30),acquisition_cost=D('500'),next_service_due=self.today,note='合成设备接收依据')
        data.update(kwargs);return prepare_registration(**data)
    def asset(self,**kwargs):
        p=self.register_preview(**kwargs);return confirm_equipment(actor=kwargs.get('actor',self.manager),proposal_token=p['proposal_token'],confirmed=True)[0]
    def change_preview(self,asset,**kwargs):
        data=dict(actor=self.manager,asset_id=asset.pk,kind='MAINTENANCE',performed_on=self.today,cost=None,next_service_due=None,note='合成设备送修')
        data.update(kwargs);return prepare_change(**data)
    def change(self,asset,**kwargs):
        p=self.change_preview(asset,**kwargs)
        return confirm_equipment(actor=kwargs.get('actor',self.manager),proposal_token=p['proposal_token'],confirmed=True)[0]
    def cash_preview(self,invoice,**kwargs):
        data=dict(actor=self.front,source_type='invoice',source_id=invoice.pk,kind='RECEIPT',amount=D('100'),
                  occurred_on=self.today,reason='合成收款核对')
        data.update(kwargs);return prepare_cash(**data)
    def cash(self,invoice,**kwargs):
        p=self.cash_preview(invoice,**kwargs)
        return confirm_cash_request(actor=kwargs.get('actor',self.front),proposal_token=p['proposal_token'],confirmed=True)[0]
    def approve(self,entry,decision='approve',actor=None):
        actor=actor or self.fin
        p=prepare_review(actor=actor,entry_id=entry.pk,decision=decision,reason='合成独立审核')
        return confirm_cash_review(actor=actor,proposal_token=p['proposal_token'],confirmed=True)[0]
    def expense(self,asset):
        event=asset.events.get(sequence=0)
        p=prepare_cash(actor=self.manager,source_type='equipment',source_id=event.pk,kind='EQUIPMENT_EXPENSE',
            occurred_on=self.today,reason='合成设备费用依据')
        return confirm_cash_request(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]
    def balance(self,invoice):
        invoice.refresh_from_db()
        with reporting_snapshot():return invoice_balance(invoice)
    def race(self,call):
        barrier=Barrier(2,timeout=15)
        def runner(index):
            close_old_connections()
            try:barrier.wait();return call(index)
            finally:connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(runner,(0,1)))
    def actor_copy(self,actor):
        copy=UserAccount.objects.get(pk=actor.pk)
        copy._adc_workspace=WorkspaceContext.objects.get(pk=actor._adc_workspace.pk)
        return copy

class CareFlowOptimizationTests(CFEFixture,TransactionTestCase):
    def setUp(self):self.setup_cfe()
    def test_read_checklist_never_creates_draft(self):
        v=self.arrived();before=AuditEvent.objects.count()
        info=care_progress(self.doctor,v.pk)
        self.assertFalse(info['allergy_current']);self.assertTrue(info['no_treatment_allowed'])
        self.assertFalse(VisitRecordVersion.objects.exists());self.assertEqual(AuditEvent.objects.count(),before)
    def test_save_note_does_not_confirm_care_or_bill(self):
        v=self.arrived();draft=save_clinical_note(actor=self.doctor,visit_id=v.pk,expected_version=v.lock_version,clinical_note='合成接诊记录')
        v.refresh_from_db()
        self.assertEqual((v.status,v.lock_version,draft.clinical_note),('CHECKED_IN',2,'合成接诊记录'))
        self.assertFalse(Invoice.objects.exists());self.assertFalse(CashEntry.objects.exists())
        self.assertEqual(draft.treatment_lines.count(),0)
    def test_stale_note_cannot_overwrite_new_note(self):
        v=self.arrived();old=v.lock_version
        save_clinical_note(actor=self.doctor,visit_id=v.pk,expected_version=old,clinical_note='第一份合成记录')
        with self.assertRaises(RuleError):save_clinical_note(actor=self.doctor,visit_id=v.pk,expected_version=old,clinical_note='过期内容')
        self.assertEqual(v.record_versions.get().clinical_note,'第一份合成记录')
    def test_note_maximum_and_audit_rollback(self):
        v=self.arrived()
        with self.assertRaises(RuleError):save_clinical_note(actor=self.doctor,visit_id=v.pk,expected_version=v.lock_version,clinical_note='x'*4001)
        with patch('care.services.emit',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):save_clinical_note(actor=self.doctor,visit_id=v.pk,expected_version=v.lock_version,clinical_note='合成记录')
        self.assertFalse(v.record_versions.exists());v.refresh_from_db();self.assertEqual(v.lock_version,1)
    def test_front_and_other_dentist_cannot_write_note(self):
        v=self.arrived()
        for actor in (self.front,self.manager,self.tech):
            with self.assertRaises(PermissionDenied):save_clinical_note(actor=actor,visit_id=v.pk,expected_version=v.lock_version,clinical_note='无授权')
        other=UserAccount.objects.create_user(username='other_cfe_doctor',dentist=self.d2)
        RoleAssignment.objects.create(user=other,role='DENTIST',scope_kind='SELF_DENTIST');activate(other,'DENTIST')
        with self.assertRaises(PermissionDenied):save_clinical_note(actor=other,visit_id=v.pk,expected_version=v.lock_version,clinical_note='其他医生')
    def test_published_note_retained_and_not_exposed_on_bill(self):
        v=self.arrived();save_clinical_note(actor=self.doctor,visit_id=v.pk,expected_version=v.lock_version,clinical_note='PRIVATE_CFE_NOTE')
        self.review(v);self.line(v);invoice=self.finish(v)
        self.assertEqual(invoice.current_record_version.clinical_note,'PRIVATE_CFE_NOTE')
        for actor,url in [(self.fin,'invoice_detail'),(self.pa,'portal_invoice')]:
            self.client.force_login(actor)
            response=self.client.get(reverse(url,args=[invoice.pk]))
            self.assertEqual(response.status_code,200);self.assertNotContains(response,'PRIVATE_CFE_NOTE')
        self.client.force_login(self.doctor)
        self.assertContains(self.client.get(reverse('care_workspace',args=[v.pk])),'PRIVATE_CFE_NOTE')
    def test_treated_blockers_clear_after_real_review_and_lines(self):
        v=self.arrived();self.line(v)
        self.assertTrue(care_progress(self.doctor,v.pk)['treated_blockers'])
        self.review(v)
        self.assertEqual(care_progress(self.doctor,v.pk)['treated_blockers'],[])
    def test_patient_allergy_revision_reopens_checklist_blocker(self):
        v=self.arrived();self.review(v);self.line(v)
        self.p1.refresh_from_db()
        self.p1.allergy_info_version+=1;self.p1.save(update_fields=['allergy_info_version'])
        self.assertFalse(care_progress(self.doctor,v.pk)['allergy_current'])
        with self.assertRaises(RuleError):self.finish(v)
        self.assertFalse(Invoice.objects.exists())
    def test_no_treatment_remains_zero_and_does_not_need_known_allergy(self):
        v=self.arrived();invoice=self.finish(v,outcome='NO_TREATMENT',reason='合成未实施治疗')
        self.assertEqual(invoice.current_record_version.total_amount,D('0'))
        with self.assertRaises(RuleError):self.cash(invoice,amount=D('0.01'))
        self.assertEqual(CashEntry.objects.count(),0)
    def test_published_note_cannot_be_changed_by_command_or_orm(self):
        v,invoice=self.billed();v.refresh_from_db()
        with self.assertRaises(RuleError):save_clinical_note(actor=self.doctor,visit_id=v.pk,expected_version=v.lock_version,clinical_note='重写')
        with self.assertRaises(IntegrityError),transaction.atomic():
            VisitRecordVersion.objects.filter(pk=invoice.current_record_version_id).update(clinical_note='绕过发布保护')
    def test_note_audit_has_no_raw_content(self):
        v=self.arrived();save_clinical_note(actor=self.doctor,visit_id=v.pk,expected_version=v.lock_version,clinical_note='PRIVATE_CFE_AUDIT')
        event=AuditEvent.objects.get(event_type='CARE_NOTE_SAVED')
        self.assertNotIn('PRIVATE_CFE_AUDIT',str(event.change_summary)+event.reason)
    def test_readonly_blocks_note(self):
        v=self.arrived()
        with override_settings(ADC_READ_ONLY=True):
            with self.assertRaises(PermissionDenied):save_clinical_note(actor=self.doctor,visit_id=v.pk,expected_version=v.lock_version,clinical_note='只读')
    def test_closed_care_review_shows_published_facts_without_close_form(self):
        v,invoice=self.billed();self.client.force_login(self.doctor)
        response=self.client.get(reverse('care_complete',args=[v.pk]))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['record'].pk,invoice.current_record_version_id)
        self.assertContains(response,'199.98')
        self.assertNotContains(response,'确认关闭并发布结算单')
        self.assertContains(response,'查看已发布结算单')
        self.assertContains(response,'已发布接诊与结算结果')
        self.assertContains(response,'复核结果随历史版本保留')
        self.assertNotContains(response,'过敏资料未知、未复核或已变化')

class EquipmentManagementTests(CFEFixture,TransactionTestCase):
    def setUp(self):self.setup_cfe()
    def test_registration_preview_is_readonly(self):
        self.register_preview();self.assertFalse(EquipmentAsset.objects.exists());self.assertFalse(EquipmentEvent.objects.exists())
    def test_registration_and_duplicate_confirmation_are_one_event(self):
        p=self.register_preview()
        a,repeated=confirm_equipment(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        again,repeated=confirm_equipment(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(a.pk,again.pk);self.assertTrue(repeated);self.assertEqual(EquipmentEvent.objects.count(),1)
        self.assertEqual(a.events.get().cost,D('500'))
    def test_invalid_registration_and_future_dates_rejected(self):
        for fields in [dict(asset_code='bad code'),dict(acquired_on=self.today+timedelta(days=1)),dict(acquisition_cost=D('-1')),dict(category='UNKNOWN')]:
            with self.assertRaises(RuleError):self.register_preview(**fields)
        self.assertFalse(EquipmentAsset.objects.exists())
    def test_global_duplicate_code_rejected(self):
        self.asset()
        with self.assertRaises(RuleError):self.register_preview(asset_code='eq-1')
    def test_unknown_and_zero_costs_and_due_dates_are_distinct(self):
        self.asset(acquisition_cost=None,next_service_due=None)
        self.asset(asset_code='EQ-2',acquisition_cost=D('0'),next_service_due=self.today+timedelta(days=1))
        r=equipment_listing(self.manager)
        self.assertEqual((r['totals']['unknown_cost'],r['totals']['unknown_due'],r['totals']['known_acquisition']),(1,1,D('0')))
    def test_overdue_filter_excludes_retired_assets(self):
        a=self.asset();self.assertEqual(len(equipment_listing(self.manager,due='overdue')['rows']),1)
        self.change(a,kind='RETIRE')
        self.assertEqual(equipment_listing(self.manager,due='overdue')['rows'],[])
    def test_maintenance_service_retirement_preserve_events(self):
        a=self.asset();self.change(a)
        a.refresh_from_db();self.assertEqual(a.state,'MAINTENANCE')
        self.change(a,kind='SERVICE',cost=D('25'),next_service_due=self.today+timedelta(days=90),note='合成保养完成')
        a.refresh_from_db();self.assertEqual((a.state,a.lock_version),('IN_SERVICE',2))
        self.assertEqual(a.events.get(sequence=2).cost,D('25'))
        self.change(a,kind='RETIRE');a.refresh_from_db()
        self.assertEqual((a.state,a.events.count()),('RETIRED',4))
        with self.assertRaises(RuleError):self.change_preview(a,kind='SERVICE')
    def test_stale_change_and_replay_never_restore_later_state(self):
        a=self.asset();p=self.change_preview(a)
        confirm_equipment(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.change(a,kind='SERVICE',note='合成恢复',next_service_due=self.today+timedelta(days=7))
        self.change(a,kind='RETIRE')
        current,repeated=confirm_equipment(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(repeated);self.assertEqual(current.state,'RETIRED');self.assertEqual(current.events.count(),4)
    def test_other_preview_is_invalid_after_maintenance_return(self):
        a=self.asset();p=self.change_preview(a,kind='RETIRE')
        self.change(a);self.change(a,kind='SERVICE',note='合成恢复')
        with self.assertRaises(RuleError):confirm_equipment(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        a.refresh_from_db();self.assertEqual(a.state,'IN_SERVICE')
    def test_other_clinic_and_roles_cannot_manage_equipment(self):
        a=self.asset()
        RoleAssignment.objects.create(user=self.manager,role='MANAGER',scope_kind='CLINIC',clinic=self.b)
        activate(self.manager,'MANAGER',self.b)
        with self.assertRaises(EquipmentAsset.DoesNotExist):equipment_detail(self.manager,a.pk)
        for actor in (self.front,self.doctor,self.tech,self.fin,self.hq):
            with self.assertRaises(PermissionDenied):self.register_preview(actor=actor)
    def test_revoked_manager_grant_blocks_old_proposal(self):
        p=self.register_preview();RoleAssignment.objects.filter(user=self.manager,role='MANAGER').update(is_active=False)
        with self.assertRaises(PermissionDenied):confirm_equipment(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(EquipmentAsset.objects.exists())
    def test_workspace_switch_invalidates_proposal(self):
        p=self.register_preview();ctx=self.manager._adc_workspace
        WorkspaceContext.objects.filter(pk=ctx.pk).update(revision=ctx.revision+2)
        self.manager._adc_workspace=WorkspaceContext.objects.get(pk=ctx.pk)
        with self.assertRaises(RuleError):confirm_equipment(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
    def test_tampered_expired_and_unconfirmed_proposals(self):
        p=self.register_preview()
        for token in (p['proposal_token']+'x',):
            with self.assertRaises(RuleError):confirm_equipment(actor=self.manager,proposal_token=token,confirmed=True)
        with patch('django.core.signing.time.time',return_value=time.time()+901):
            with self.assertRaises(RuleError):confirm_equipment(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        with self.assertRaises(RuleError):confirm_equipment(actor=self.manager,proposal_token=p['proposal_token'],confirmed=False)
        self.assertFalse(EquipmentAsset.objects.exists())
    def test_device_url_binding_checked_before_writing(self):
        p=self.register_preview()
        with self.assertRaises(RuleError):confirm_equipment(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True,expected_action='change',expected_asset_id=99)
        self.assertFalse(EquipmentAsset.objects.exists())
    def test_actor_without_workspace_cannot_register(self):
        actor=UserAccount.objects.get(pk=self.manager.pk)
        with self.assertRaises(PermissionDenied):self.register_preview(actor=actor)
    def test_readonly_registration_rejected(self):
        p=self.register_preview()
        with override_settings(ADC_READ_ONLY=True):
            with self.assertRaises(PermissionDenied):confirm_equipment(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
    def test_audit_failure_rolls_back_asset_and_event(self):
        p=self.register_preview()
        with patch('equipment.services.emit',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):confirm_equipment(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(EquipmentAsset.objects.exists());self.assertFalse(EquipmentEvent.objects.exists())
    def test_equipment_does_not_pause_or_cancel_visits_or_create_expense(self):
        v=self.book();a=self.asset();self.change(a)
        v.refresh_from_db();self.slot1.refresh_from_db()
        self.assertEqual(v.status,'SCHEDULED');self.assertFalse(self.slot1.booking_paused);self.assertFalse(CashEntry.objects.exists())
    def test_equipment_history_and_identity_sql_guards(self):
        a=self.asset();event=a.events.get()
        for operation in [lambda:EquipmentEvent.objects.filter(pk=event.pk).update(note='重写'),
                          lambda:EquipmentEvent.objects.filter(pk=event.pk).delete(),
                          lambda:EquipmentAsset.objects.filter(pk=a.pk).update(clinic=self.b),
                          lambda:EquipmentAsset.objects.filter(pk=a.pk).update(state='RETIRED',lock_version=1)]:
            with self.assertRaises(IntegrityError),transaction.atomic():operation()
    def test_concurrent_duplicate_registration_has_one_asset(self):
        p=self.register_preview()
        rows=self.race(lambda i:confirm_equipment(actor=self.actor_copy(self.manager),proposal_token=p['proposal_token'],confirmed=True)[0].pk)
        self.assertEqual(rows[0],rows[1]);self.assertEqual(EquipmentAsset.objects.count(),1);self.assertEqual(EquipmentEvent.objects.count(),1)
    def test_invalid_filter_never_returns_all_assets(self):
        self.asset()
        with self.assertRaises(RuleError):equipment_listing(self.manager,state='garbage')
    def test_finance_and_hq_read_assets_without_mutating(self):
        self.asset();before=AuditEvent.objects.count()
        for actor in (self.fin,self.hq):self.assertEqual(equipment_listing(actor)['totals']['total'],1)
        self.assertEqual(AuditEvent.objects.count(),before)

class CashManagementTests(CFEFixture,TransactionTestCase):
    def setUp(self):self.setup_cfe();self.visit,self.invoice=self.billed()
    def test_preview_and_pending_request_are_not_cash(self):
        p=self.cash_preview(self.invoice)
        self.assertFalse(CashEntry.objects.exists())
        entry=confirm_cash_request(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)[0]
        self.assertEqual(entry.state,'PENDING')
        self.assertEqual(self.balance(self.invoice)['net_received'],D('0'))
        self.assertEqual(self.balance(self.invoice)['remaining'],D('199.98'))
    def test_request_and_review_replays_are_current_terminal_result(self):
        p=self.cash_preview(self.invoice)
        entry=confirm_cash_request(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)[0]
        r=prepare_review(actor=self.fin,entry_id=entry.pk,decision='approve',reason='合成独立审核')
        confirm_cash_review(actor=self.fin,proposal_token=r['proposal_token'],confirmed=True)
        again,repeated=confirm_cash_review(actor=self.fin,proposal_token=r['proposal_token'],confirmed=True)
        request_again,repeated_request=confirm_cash_request(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(repeated and repeated_request);self.assertEqual(request_again.state,'POSTED')
        self.assertEqual(CashEntry.objects.count(),1);self.assertEqual(AuditEvent.objects.filter(event_type='CASH_POSTED').count(),1)
    def test_self_review_denied_even_after_role_switch(self):
        entry=self.cash(self.invoice)
        RoleAssignment.objects.create(user=self.front,role='FINANCE',scope_kind='CHAIN');activate(self.front,'FINANCE')
        with self.assertRaises(RuleError):prepare_review(actor=self.front,entry_id=entry.pk,decision='approve',reason='本人审核')
        entry.refresh_from_db();self.assertEqual(entry.state,'PENDING')
    def test_rejected_request_never_counts_as_cash(self):
        entry=self.cash(self.invoice);self.approve(entry,'reject')
        self.assertEqual(self.balance(self.invoice)['net_received'],D('0'))
    def test_overcollection_overrefund_zero_and_future_date_refused(self):
        for kwargs in [dict(amount=D('200')),dict(kind='REFUND',amount=D('1')),dict(amount=D('0')),dict(occurred_on=self.today+timedelta(days=1))]:
            with self.assertRaises(RuleError):self.cash_preview(self.invoice,**kwargs)
        self.assertFalse(CashEntry.objects.exists())
    def test_partial_collection_and_refund_use_exact_cents(self):
        entry=self.cash(self.invoice,amount=D('99.99'));self.approve(entry)
        refund=self.cash(self.invoice,kind='REFUND',amount=D('0.01'));self.approve(refund)
        b=self.balance(self.invoice)
        self.assertEqual((b['net_received'],b['remaining'],b['refund_due']),(D('99.98'),D('100.00'),D('0')))
    def test_stale_request_preview_after_another_request_has_no_duplicate(self):
        p=self.cash_preview(self.invoice);self.cash(self.invoice,amount=D('1'))
        with self.assertRaises(RuleError):confirm_cash_request(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(CashEntry.objects.count(),1)
    def test_cash_and_bill_url_binding_checked_before_write(self):
        p=self.cash_preview(self.invoice)
        with self.assertRaises(RuleError):confirm_cash_request(actor=self.front,proposal_token=p['proposal_token'],confirmed=True,expected_source_type='invoice',expected_source_id=999)
        self.assertFalse(CashEntry.objects.exists())
    def test_request_reversal_url_binding_prevents_post_write_failure(self):
        p=self.cash_preview(self.invoice)
        with self.assertRaises(RuleError):confirm_cash_request(actor=self.front,proposal_token=p['proposal_token'],confirmed=True,expected_source_type='invoice',expected_source_id=self.invoice.pk,expected_reversal_id=999)
        self.assertFalse(CashEntry.objects.exists())
    def test_cross_clinic_and_wrong_role_refused(self):
        with self.assertRaises(PermissionDenied):self.cash_preview(self.invoice,actor=self.front2)
        for actor in (self.doctor,self.manager,self.fin,self.tech,self.pa):
            with self.assertRaises(PermissionDenied):self.cash_preview(self.invoice,actor=actor)
    def test_no_workspace_actor_cannot_prepare(self):
        with self.assertRaises(PermissionDenied):self.cash_preview(self.invoice,actor=UserAccount.objects.get(pk=self.front.pk))
    def test_grant_revoked_after_pending_blocks_posting_but_allows_rejection(self):
        entry=self.cash(self.invoice);p=prepare_review(actor=self.fin,entry_id=entry.pk,decision='approve',reason='合成独立审核')
        RoleAssignment.objects.filter(user=self.front,role='FRONT_DESK').update(is_active=False)
        with self.assertRaises(RuleError):confirm_cash_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        entry.refresh_from_db();self.assertEqual(entry.state,'PENDING')
        self.assertEqual(self.approve(entry,'reject').state,'REJECTED')
    def test_revoked_finance_grant_blocks_confirmation(self):
        entry=self.cash(self.invoice);p=prepare_review(actor=self.fin,entry_id=entry.pk,decision='approve',reason='合成独立审核')
        RoleAssignment.objects.filter(user=self.fin,role='FINANCE').update(is_active=False)
        with self.assertRaises(PermissionDenied):confirm_cash_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(self.balance(self.invoice)['net_received'],D('0'))
    def correct_bill(self):
        self.visit.refresh_from_db();line=self.invoice.current_record_version.treatment_lines.get()
        request=request_line_correction(actor=self.doctor,visit_id=self.visit.pk,expected_version=self.visit.lock_version,line_id=line.pk,quantity=D('1'),unit_price=D('99.99'),reason='合成独立更正')
        review_correction(actor=self.fin,request_id=request.pk,decision='approve',reason='合成独立核对')
        self.invoice.refresh_from_db()
    def test_bill_change_invalidates_pending_receipt_approval(self):
        entry=self.cash(self.invoice);p=prepare_review(actor=self.fin,entry_id=entry.pk,decision='approve',reason='合成独立审核')
        self.correct_bill()
        with self.assertRaises(RuleError):confirm_cash_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        entry.refresh_from_db();self.assertEqual(entry.state,'PENDING')
        self.assertEqual(self.approve(entry,'reject').state,'REJECTED')
    def test_bill_correction_after_receipt_exposes_credit_and_refund_closes_it(self):
        entry=self.cash(self.invoice,amount=D('199.98'));self.approve(entry);self.correct_bill()
        b=self.balance(self.invoice);self.assertEqual((b['billed'],b['net_received'],b['refund_due']),(D('99.99'),D('199.98'),D('99.99')))
        refund=self.cash(self.invoice,kind='REFUND',amount=D('99.99'));self.approve(refund)
        self.assertEqual((self.balance(self.invoice)['remaining'],self.balance(self.invoice)['refund_due']),(D('0'),D('0')))
        self.assertEqual(Invoice.objects.filter(visit=self.visit).count(),1)
    def test_receipt_reversal_appends_history_and_is_unique(self):
        entry=self.cash(self.invoice);self.approve(entry)
        reverse=self.cash(self.invoice,reversal_id=entry.pk,amount=None);self.approve(reverse)
        self.assertEqual(self.balance(self.invoice)['net_received'],D('0'))
        entry.refresh_from_db();self.assertEqual(entry.state,'POSTED')
        self.assertEqual(CashEntry.objects.count(),2)
        with self.assertRaises(RuleError):self.cash_preview(self.invoice,reversal_id=entry.pk)
    def test_refund_reversal_restores_credit_after_bill_correction(self):
        entry=self.cash(self.invoice,amount=D('199.98'));self.approve(entry);self.correct_bill()
        refund=self.cash(self.invoice,kind='REFUND',amount=D('99.99'));self.approve(refund)
        reverse=self.cash(self.invoice,reversal_id=refund.pk);self.approve(reverse)
        self.assertEqual(self.balance(self.invoice)['refund_due'],D('99.99'))
    def test_equipment_expense_requires_independent_review_and_separate_net(self):
        a=self.asset();entry=self.expense(a)
        self.assertEqual(event_net(a.events.get(sequence=0).pk),D('0'))
        self.approve(entry)
        self.assertEqual(event_net(a.events.get(sequence=0).pk),D('500'))
        self.assertEqual(self.balance(self.invoice)['net_received'],D('0'))
        with self.assertRaises(RuleError):self.expense(a)
    def test_equipment_expense_reversal_retains_source_and_can_repost_after_void(self):
        a=self.asset();entry=self.expense(a);self.approve(entry);event=a.events.get(sequence=0)
        p=prepare_cash(actor=self.manager,source_type='equipment',source_id=event.pk,kind='EXPENSE_REVERSAL',reversal_id=entry.pk,occurred_on=self.today,reason='合成误记冲回')
        reverse=confirm_cash_request(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0];self.approve(reverse)
        self.assertEqual(event_net(event.pk),D('0'))
        replacement=self.expense(a);self.approve(replacement);self.assertEqual(event_net(event.pk),D('500'))
        self.assertEqual(CashEntry.objects.count(),3)
    def test_unknown_and_zero_device_fees_cannot_be_cash_expenses(self):
        for code,cost in [('EQ-NONE',None),('EQ-ZERO',D('0'))]:
            a=self.asset(asset_code=code,acquisition_cost=cost)
            with self.assertRaises(RuleError):self.expense(a)
        self.assertFalse(CashEntry.objects.exists())
    def test_scope_list_separates_front_receipts_and_manager_expenses(self):
        self.cash(self.invoice);self.expense(self.asset())
        self.assertEqual(len(cash_listing(self.front)['rows']),1);self.assertEqual(len(cash_listing(self.manager)['rows']),1)
        self.assertEqual(len(cash_listing(self.front2)['rows']),0);self.assertEqual(len(cash_listing(self.fin)['rows']),2)
    def test_receivables_include_unpaid_bills_and_ignore_pending(self):
        self.cash(self.invoice)
        r=receivables(self.fin,state='due')
        self.assertEqual((r['totals']['bills'],r['totals']['billed'],r['totals']['remaining']),(1,D('199.98'),D('199.98')))
        self.assertEqual(len(r['rows']),1)
        self.assertEqual(receivables(self.front2)['totals']['bills'],0)
    def test_receivables_current_revision_does_not_count_history_twice(self):
        self.approve(self.cash(self.invoice,amount=D('199.98')));self.correct_bill()
        r=receivables(self.fin,state='credit')
        self.assertEqual((r['totals']['bills'],r['totals']['billed'],r['totals']['refund_due']),(1,D('99.99'),D('99.99')))
    def test_cash_does_not_change_existing_quarter_profit_basis(self):
        q=self.make_quarter();c=self.member(q);self.savecost(q,c,'10','20');self.confirmcost(q,c);self.roster(q)
        before=quarter_report(self.fin,q.pk).result.profit
        self.approve(self.cash(self.invoice));self.approve(self.expense(self.asset()))
        self.assertEqual(quarter_report(self.fin,q.pk).result.profit,before)
    def test_readonly_and_unconfirmed_cash_writes_denied(self):
        p=self.cash_preview(self.invoice)
        with self.assertRaises(RuleError):confirm_cash_request(actor=self.front,proposal_token=p['proposal_token'],confirmed=False)
        with override_settings(ADC_READ_ONLY=True):
            with self.assertRaises(PermissionDenied):confirm_cash_request(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(CashEntry.objects.exists())
    def test_bad_and_expired_request_tokens(self):
        p=self.cash_preview(self.invoice)
        with self.assertRaises(RuleError):confirm_cash_request(actor=self.front,proposal_token=p['proposal_token']+'x',confirmed=True)
        with patch('django.core.signing.time.time',return_value=time.time()+901):
            with self.assertRaises(RuleError):confirm_cash_request(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
    def test_malformed_signed_source_boolean_rejected(self):
        p=self.cash_preview(self.invoice);data=signing.loads(p['proposal_token'],salt=REQUEST)
        data['data']['source']=True
        token=signing.dumps(data,salt=REQUEST,compress=True)
        with self.assertRaises(RuleError):confirm_cash_request(actor=self.front,proposal_token=token,confirmed=True)
        self.assertFalse(CashEntry.objects.exists())
    def test_cash_audit_failure_rolls_back_request_and_post(self):
        p=self.cash_preview(self.invoice)
        with patch('finance.cash_services.emit',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):confirm_cash_request(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(CashEntry.objects.exists())
        entry=self.cash(self.invoice);p=prepare_review(actor=self.fin,entry_id=entry.pk,decision='approve',reason='合成审核')
        with patch('finance.cash_services.emit',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):confirm_cash_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        entry.refresh_from_db();self.assertEqual(entry.state,'PENDING')
    def test_terminal_cash_facts_sql_immutable(self):
        entry=self.cash(self.invoice);self.approve(entry)
        for operation in [lambda:CashEntry.objects.filter(pk=entry.pk).update(amount=D('1')),
                          lambda:CashEntry.objects.filter(pk=entry.pk).delete(),
                          lambda:CashEntry.objects.filter(pk=entry.pk).update(state='PENDING',lock_version=0)]:
            with self.assertRaises(IntegrityError),transaction.atomic():operation()
    def test_cash_raw_source_and_initial_posting_sql_denied(self):
        fields=dict(invoice=self.invoice,based_record_version=self.invoice.current_record_version,clinic=self.b,kind='RECEIPT',amount=D('1'),occurred_on=self.today,reason='错误来源',prepared_by=self.front)
        with self.assertRaises(IntegrityError),transaction.atomic():CashEntry.objects.create(**fields)
        fields['clinic']=self.a;fields.update(state='POSTED',lock_version=1,reviewed_by=self.fin,reviewed_at=timezone.now(),review_reason='跳过申请')
        with self.assertRaises(IntegrityError),transaction.atomic():CashEntry.objects.create(**fields)
    def test_concurrent_same_request_and_review_have_one_entry(self):
        p=self.cash_preview(self.invoice)
        rows=self.race(lambda i:confirm_cash_request(actor=self.actor_copy(self.front),proposal_token=p['proposal_token'],confirmed=True)[0].pk)
        self.assertEqual(rows[0],rows[1]);self.assertEqual(CashEntry.objects.count(),1)
        r=prepare_review(actor=self.fin,entry_id=rows[0],decision='approve',reason='合成独立审核')
        reviews=self.race(lambda i:confirm_cash_review(actor=self.actor_copy(self.fin),proposal_token=r['proposal_token'],confirmed=True)[0].pk)
        self.assertEqual(reviews[0],reviews[1]);self.assertEqual(self.balance(self.invoice)['net_received'],D('100'))
    def test_competing_approvals_do_not_overcollect(self):
        one=self.cash(self.invoice,amount=D('150'));two=self.cash(self.invoice,amount=D('150'))
        previews=[prepare_review(actor=self.fin,entry_id=e.pk,decision='approve',reason='合成审核') for e in [one,two]]
        def call(i):
            try:confirm_cash_review(actor=self.actor_copy(self.fin),proposal_token=previews[i]['proposal_token'],confirmed=True);return 'posted'
            except RuleError:return 'stale'
        self.assertEqual(sorted(self.race(call)),['posted','stale'])
        self.assertEqual(self.balance(self.invoice)['net_received'],D('150'))
    def test_review_url_binding_and_duplicate_rejected_request(self):
        entry=self.cash(self.invoice);p=prepare_review(actor=self.fin,entry_id=entry.pk,decision='reject',reason='合成独立拒绝')
        with self.assertRaises(RuleError):confirm_cash_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True,expected_entry_id=999)
        self.assertEqual(confirm_cash_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)[0].state,'REJECTED')
        self.assertTrue(confirm_cash_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)[1])

class CFEHTTPTests(CFEFixture,TransactionTestCase):
    def setUp(self):self.setup_cfe()
    def test_clinical_note_http_preserves_draft_and_clear_blockers(self):
        v=self.arrived();self.client.force_login(self.doctor)
        r=self.client.post(reverse('care_workspace',args=[v.pk]),{'action':'note','expected_version':v.lock_version,'clinical_note':'合成网页接诊记录','confirmed':'on'})
        self.assertEqual(r.status_code,302)
        self.assertContains(self.client.get(reverse('care_workspace',args=[v.pk])),'合成网页接诊记录')
        self.assertFalse(Invoice.objects.exists())
    def test_equipment_http_preview_confirmation_and_scope(self):
        self.client.force_login(self.manager)
        r=self.client.post(reverse('equipment_register'),{'action':'preview','asset_code':'WEB-EQ','name':'合成消毒设备','category':'STERILIZER','location':'二区','acquired_on':self.today.isoformat(),'acquisition_cost':'100','next_service_due':'','note':'合成登记'})
        self.assertEqual(r.status_code,200);self.assertFalse(EquipmentAsset.objects.exists())
        r=self.client.post(reverse('equipment_register'),{'action':'confirm','proposal_token':r.context['form'].initial['proposal_token'],'confirmed':'on'})
        self.assertEqual(r.status_code,302);a=EquipmentAsset.objects.get()
        self.client.force_login(self.fin);self.assertEqual(self.client.get(reverse('equipment_detail',args=[a.pk])).status_code,200)
        self.assertEqual(self.client.post(reverse('equipment_register'),{}).status_code,403)
    def test_cash_http_two_person_flow(self):
        v,invoice=self.billed();self.client.force_login(self.front)
        r=self.client.post(reverse('cash_invoice_request',args=[invoice.pk]),{'action':'preview','kind':'RECEIPT','amount':'100','occurred_on':self.today.isoformat(),'reason':'合成网页收款'})
        self.assertEqual(r.status_code,200);self.assertFalse(CashEntry.objects.exists())
        r=self.client.post(reverse('cash_invoice_request',args=[invoice.pk]),{'action':'confirm','proposal_token':r.context['form'].initial['proposal_token'],'confirmed':'on'})
        self.assertEqual(r.status_code,302);entry=CashEntry.objects.get()
        self.client.force_login(self.fin)
        r=self.client.post(reverse('cash_review',args=[entry.pk]),{'action':'preview','decision':'approve','reason':'合成网页独立审核'})
        self.assertEqual(r.status_code,200);entry.refresh_from_db();self.assertEqual(entry.state,'PENDING')
        self.assertContains(r,invoice.invoice_no);self.assertContains(r,self.a.name)
        r=self.client.post(reverse('cash_review',args=[entry.pk]),{'action':'confirm','proposal_token':r.context['form'].initial['proposal_token'],'confirmed':'on'})
        self.assertEqual(r.status_code,302);entry.refresh_from_db();self.assertEqual(entry.state,'POSTED')
    def test_patient_and_dentist_cannot_access_cash_or_equipment_workspaces(self):
        for actor in [self.pa,self.doctor,self.tech]:
            self.client.force_login(actor)
            for route in ['cash_list','cash_receivables','equipment_list']:
                self.assertEqual(self.client.get(reverse(route)).status_code,403)
    def test_front_cross_clinic_bill_request_has_no_foreign_details(self):
        v,i=self.billed();self.client.force_login(self.front2)
        # Switch the fixture account to the other authorized clinic explicitly.
        self.client.post(reverse('activate_clinic'),{'clinic':self.b.pk})
        self.assertEqual(self.client.get(reverse('cash_invoice_request',args=[i.pk])).status_code,404)
    def test_missing_confirmation_checkbox_never_writes_equipment(self):
        self.client.force_login(self.manager);p=self.register_preview()
        r=self.client.post(reverse('equipment_register'),{'action':'confirm','proposal_token':p['proposal_token']})
        self.assertEqual(r.status_code,409);self.assertFalse(EquipmentAsset.objects.exists())
    def test_csrf_is_still_required_for_new_equipment_commands(self):
        c=WorkspaceClient(enforce_csrf_checks=True);c.force_login(self.manager);c.get(reverse('equipment_register'))
        r=c.post(reverse('equipment_register'),{'action':'preview'})
        self.assertEqual(r.status_code,403);self.assertFalse(EquipmentAsset.objects.exists())
    def test_invalid_filters_are_explicit_and_do_not_return_all_rows(self):
        self.client.force_login(self.manager);self.assertEqual(self.client.get(reverse('equipment_list')+'?state=invalid').status_code,400)
        self.client.force_login(self.fin);self.assertEqual(self.client.get(reverse('cash_list')+'?state=invalid').status_code,400)
        self.assertEqual(self.client.get(reverse('cash_receivables')+'?state=invalid').status_code,400)
    def test_portal_invoice_reads_own_current_cash_status_only(self):
        v,i=self.billed();self.approve(self.cash(i,amount=D('100')))
        self.client.force_login(self.pa)
        r=self.client.get(reverse('portal_invoice',args=[i.pk]))
        self.assertEqual(r.status_code,200);self.assertContains(r,'100.00');self.assertNotContains(r,'申请模拟收款或退款')
        self.client.force_login(self.pb);self.assertEqual(self.client.get(reverse('portal_invoice',args=[i.pk])).status_code,404)
