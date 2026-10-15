"""Real PostgreSQL projections and existing-command handoffs; no payment gateway."""
from datetime import timedelta
from decimal import Decimal as D
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TransactionTestCase,override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from accounts.models import RoleAssignment
from adc_core.rules import RuleError
from care.models import Invoice,AuditEvent
from care.corrections import request_line_correction,review_correction
from coordination.models import CoordinationTask
from coordination.task_rules import ACTION_REASONS
from coordination.task_services import inspect_task,prepare_task,confirm_task
from scheduling.models import AvailabilitySlot,Visit
from scheduling.intake_services import inspect_intake,prepare_intake,confirm_intake
from equipment.forms import EquipmentActionForm
from equipment.fees import fee_worklist
from equipment.schedule import maintenance_schedule
from equipment.selectors import equipment_detail
from finance.cash_models import CashEntry
from finance.cash_selectors import cash_listing,cash_detail
from finance.cash_services import prepare_review,confirm_cash_review
from tests.test_care_finance_equipment import CFEFixture,activate
from tests.workspace_client import WorkspaceClient

class CashWorkflowFollowupTests(CFEFixture,TransactionTestCase):
    def setUp(self):
        self.setup_cfe();self.visit,self.invoice=self.billed()
    def correct(self):
        self.visit.refresh_from_db();line=self.invoice.current_record_version.treatment_lines.get()
        req=request_line_correction(actor=self.doctor,visit_id=self.visit.pk,expected_version=self.visit.lock_version,
            line_id=line.pk,quantity=D('1'),unit_price=D('99.99'),reason='合成实际一单位')
        review_correction(actor=self.fin,request_id=req.pk,decision='approve',reason='合成独立复核')
        self.invoice.refresh_from_db()
    def client_for(self,actor):
        c=WorkspaceClient();c.force_login(actor);return c
    def test_pending_amounts_are_separate_from_posted_cash(self):
        self.approve(self.cash(self.invoice));self.cash(self.invoice,amount=D('30'))
        self.cash(self.invoice,kind='REFUND',amount=D('20'))
        b=self.balance(self.invoice)
        self.assertEqual((b['net_received'],b['remaining'],b['pending_receipts'],b['pending_refunds'],b['pending']),
                         (D('100'),D('99.98'),D('30'),D('20'),2))
    def test_receipt_preview_is_exact_cent_and_creates_no_request(self):
        p=self.cash_preview(self.invoice,amount=D('99.99'))
        self.assertEqual((p['projected']['net_received'],p['projected']['remaining']),(D('99.99'),D('99.99')))
        self.assertFalse(CashEntry.objects.exists())
    def test_partial_refund_preview_explains_reopened_receivable(self):
        self.approve(self.cash(self.invoice));p=self.cash_preview(self.invoice,kind='REFUND',amount=D('40'))
        self.assertEqual((p['projected']['net_received'],p['projected']['remaining'],p['projected']['refund_due']),
                         (D('60'),D('139.98'),D('0')))
        self.assertEqual(self.balance(self.invoice)['net_received'],D('100'))
    def test_default_receipt_is_remaining_not_original_bill(self):
        self.approve(self.cash(self.invoice))
        r=self.client_for(self.front).get(reverse('cash_invoice_request',args=[self.invoice.pk]))
        self.assertEqual(r.context['form'].initial['amount'],D('99.98'))
        self.assertEqual(r.context['form'].initial['kind'],'RECEIPT')
    def test_native_cash_and_expense_dates_render_a_valid_business_day(self):
        r=self.client_for(self.front).get(reverse('cash_invoice_request',args=[self.invoice.pk]))
        self.assertContains(r,'value="'+self.today.isoformat()+'"')
        a=self.asset();event=a.events.get(sequence=0)
        r=self.client_for(self.manager).get(reverse('cash_equipment_request',args=[event.pk]))
        self.assertContains(r,'value="'+self.today.isoformat()+'"')
    def test_corrected_overpayment_defaults_to_refund_balance(self):
        self.approve(self.cash(self.invoice,amount=D('199.98')));self.correct()
        r=self.client_for(self.front).get(reverse('cash_invoice_request',args=[self.invoice.pk]))
        self.assertEqual(r.context['form'].initial['kind'],'REFUND')
        self.assertEqual(r.context['form'].initial['amount'],D('99.99'))
    def test_rejection_projection_does_not_change_cash(self):
        e=self.cash(self.invoice);p=prepare_review(actor=self.fin,entry_id=e.pk,decision='reject',reason='合成依据不足')
        self.assertEqual(p['projected'],p['balance']);self.assertEqual(self.balance(self.invoice)['net_received'],D('0'))
    def test_revoked_preparer_is_identified_before_approval_preview(self):
        e=self.cash(self.invoice);RoleAssignment.objects.filter(user=self.front,role='FRONT_DESK').update(is_active=False)
        data=cash_detail(self.fin,e.pk);self.assertIn('授权已失效',data['approval_blocker']);self.assertIsNone(data['projected'])
        with self.assertRaises(RuleError):prepare_review(actor=self.fin,entry_id=e.pk,decision='approve',reason='合成核对')
        self.assertEqual(self.approve(e,'reject').state,'REJECTED')
    def test_corrected_pending_request_is_rejectable_and_cash_unchanged(self):
        e=self.cash(self.invoice);self.correct();data=cash_detail(self.fin,e.pk)
        self.assertIn('账单已更正',data['approval_blocker']);self.assertIsNone(data['projected'])
        r=self.client_for(self.fin).get(reverse('cash_review',args=[e.pk]))
        self.assertEqual(list(r.context['form'].fields['decision'].choices),[('reject','拒绝失效申请并保留历史')])
        self.assertEqual(self.approve(e,'reject').state,'REJECTED');self.assertEqual(self.balance(self.invoice)['net_received'],D('0'))
    def test_candidate_projection_does_not_promise_competing_pending_approval(self):
        a=self.cash(self.invoice,amount=D('199.98'));b=self.cash(self.invoice,amount=D('199.98'))
        self.assertEqual(cash_detail(self.fin,b.pk)['projected']['remaining'],D('0'))
        self.approve(a);data=cash_detail(self.fin,b.pk)
        self.assertIn('超过当前待收',data['approval_blocker']);self.assertIsNone(data['projected'])
        self.assertEqual(self.approve(b,'reject').state,'REJECTED')
    def test_source_filters_stay_inside_role_scope(self):
        self.cash(self.invoice);a=self.asset();e=self.expense(a)
        self.assertEqual(len(cash_listing(self.fin,event=str(e.equipment_event_id))['rows']),1)
        self.assertEqual(len(cash_listing(self.front,event=str(e.equipment_event_id))['rows']),0)
        self.assertEqual(len(cash_listing(self.manager,invoice=str(self.invoice.pk))['rows']),0)
        self.assertEqual(len(cash_listing(self.front2,invoice=str(self.invoice.pk))['rows']),0)
    def test_source_and_kind_filters_validate_input(self):
        for data in [dict(kind='OTHER'),dict(invoice='1',event='1'),dict(invoice='0'),dict(event=str(2**63)),dict(invoice='9'*5000)]:
            with self.assertRaises(RuleError):cash_listing(self.fin,**data)
    def test_filter_pagination_keeps_source_and_kind(self):
        for n in range(21):self.cash(self.invoice,amount=D('1'))
        c=self.client_for(self.fin);params={'invoice':str(self.invoice.pk),'kind':'RECEIPT','state':'PENDING'}
        first=c.get(reverse('cash_list'),params);second=c.get(reverse('cash_list'),dict(params,page='2'))
        self.assertEqual(len(first.context['rows']),20);self.assertEqual(len(second.context['rows']),1)
        self.assertContains(first,'invoice='+str(self.invoice.pk));self.assertContains(first,'kind=RECEIPT')
    def test_final_preview_shows_single_candidate_effect(self):
        e=self.cash(self.invoice);c=self.client_for(self.fin)
        r=c.post(reverse('cash_review',args=[e.pk]),dict(action='preview',decision='approve',reason='合成独立复核'))
        self.assertEqual(r.status_code,200);self.assertContains(r,'本条单独获批后待收');self.assertContains(r,'99.98')
        e.refresh_from_db();self.assertEqual(e.state,'PENDING')

class EquipmentFeeFollowupTests(CFEFixture,TransactionTestCase):
    def setUp(self):self.setup_cfe()
    def test_known_unrequested_fee_is_visible_to_finance(self):
        a=self.asset();d=fee_worklist(self.fin)
        self.assertEqual((d['totals']['events'],d['totals']['recorded_cost'],d['totals']['net_expense']),(1,D('500'),D('0')))
        self.assertEqual(d['rows'][0].fee_state,'UNREQUESTED');self.assertFalse(CashEntry.objects.exists())
    def test_pending_expense_is_visible_without_cash_effect(self):
        a=self.asset();self.expense(a);d=fee_worklist(self.manager)
        self.assertEqual((d['rows'][0].fee_state,d['totals']['pending_sources'],d['totals']['net_expense']),('PENDING',1,D('0')))
    def test_reversal_pending_then_repost_does_not_duplicate_source_cost(self):
        a=self.asset();e=self.expense(a);self.approve(e)
        from finance.cash_services import prepare_cash,confirm_cash_request
        p=prepare_cash(actor=self.manager,source_type='equipment',source_id=e.equipment_event_id,kind='EXPENSE_REVERSAL',
            occurred_on=self.today,reason='合成冲回原笔误记',reversal_id=e.pk,**self.evidence())
        reversal=confirm_cash_request(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]
        d=fee_worklist(self.fin);self.assertEqual((d['rows'][0].fee_state,d['rows'][0].net_expense),('PENDING',D('500')))
        self.approve(reversal);self.assertEqual(fee_worklist(self.fin)['rows'][0].fee_state,'REVERSED')
        self.approve(self.expense(a));d=fee_worklist(self.fin)
        self.assertEqual((d['totals']['recorded_cost'],d['totals']['net_expense'],d['totals']['events']),(D('500'),D('500'),1))
    def test_unknown_and_confirmed_zero_are_distinct(self):
        self.asset(asset_code='UNKNOWN',acquisition_cost=None);self.asset(asset_code='ZERO',acquisition_cost=D('0'))
        d=fee_worklist(self.fin);self.assertEqual((d['totals']['unknown_cost'],d['totals']['zero_cost'],d['totals']['events']),(1,1,0))
    def test_unknown_fee_can_be_traced_to_its_source(self):
        a=self.asset(acquisition_cost=None);d=fee_worklist(self.fin,'UNKNOWN')
        self.assertEqual(d['rows'][0].asset_id,a.pk);self.assertIsNone(d['rows'][0].cost)
        self.assertEqual(d['rows'][0].fee_state,'UNKNOWN');self.assertEqual(d['totals']['recorded_cost'],D('0'))
    def test_zero_fee_filter_does_not_offer_an_expense(self):
        self.asset(acquisition_cost=D('0'));c=WorkspaceClient();c.force_login(self.manager)
        r=c.get(reverse('equipment_expenses'),{'state':'ZERO'})
        self.assertEqual(r.status_code,200);self.assertContains(r,'明确零费用');self.assertNotContains(r,'申请此笔费用')
    def test_service_fees_and_retired_assets_remain_sources(self):
        a=self.asset();a=self.change(a,kind='SERVICE',cost=D('20'),next_service_due=self.today+timedelta(days=30));a=self.change(a,kind='RETIRE')
        d=fee_worklist(self.fin);self.assertEqual((d['totals']['events'],d['totals']['recorded_cost']),(2,D('520')))
        self.assertEqual({row.asset_id for row in d['rows']},{a.pk});self.assertEqual(self.expense(a).amount,D('500'))
    def test_manager_fee_scope_and_chain_readers(self):
        self.asset();RoleAssignment.objects.create(user=self.manager,role='MANAGER',scope_kind='CLINIC',clinic=self.b)
        activate(self.manager,'MANAGER',self.b);b=self.asset(asset_code='EQ-B');activate(self.manager,'MANAGER',self.a)
        self.assertEqual(len(fee_worklist(self.manager)['rows']),1);self.assertEqual(len(fee_worklist(self.fin)['rows']),2)
        self.assertEqual(len(fee_worklist(self.hq)['rows']),2);self.assertFalse(fee_worklist(self.manager,asset=str(b.pk))['rows'])
    def test_fee_queries_have_no_per_source_database_reads(self):
        a=self.asset()
        with CaptureQueriesContext(connection) as first:fee_worklist(self.fin)
        for n in range(21):a=self.change(a,kind='SERVICE',cost=D('1'),next_service_due=None)
        with CaptureQueriesContext(connection) as many:fee_worklist(self.fin)
        self.assertEqual(len(first),len(many))
    def test_equipment_history_shows_reconciliation_without_requesting_again(self):
        a=self.asset();self.approve(self.expense(a));data=equipment_detail(self.manager,a.pk)
        self.assertEqual((data['events'][0].fee_state,data['events'][0].net_expense),('POSTED',D('500')))
        c=WorkspaceClient();c.force_login(self.manager);r=c.get(reverse('equipment_detail',args=[a.pk]))
        self.assertContains(r,'已核对记账');self.assertNotContains(r,'申请此笔设备费用记账')
    def test_fee_filters_preserve_unknown_vs_unrequested(self):
        a=self.asset();self.expense(a)
        self.assertFalse(fee_worklist(self.fin,'UNREQUESTED')['rows']);self.assertEqual(len(fee_worklist(self.fin,'PENDING')['rows']),1)
        with self.assertRaises(RuleError):fee_worklist(self.fin,state='PAID')
        with self.assertRaises(RuleError):fee_worklist(self.fin,asset='-1')
    @override_settings(ADC_READ_ONLY=True)
    def test_readonly_fee_projection_does_not_emit_audit_or_cash(self):
        # Source creation is outside the read-only operation being verified.
        with override_settings(ADC_READ_ONLY=False):self.asset()
        before=AuditEvent.objects.count();fee_worklist(self.fin)
        self.assertEqual(AuditEvent.objects.count(),before);self.assertFalse(CashEntry.objects.exists())
    def test_fee_http_role_matrix(self):
        for actor,expected in [(self.manager,200),(self.fin,200),(self.hq,200),(self.front,403),(self.doctor,403),(self.pa,403),(self.tech,403)]:
            c=WorkspaceClient();c.force_login(actor);self.assertEqual(c.get(reverse('equipment_expenses')).status_code,expected)

class MaintenanceHandoffFollowupTests(CFEFixture,TransactionTestCase):
    def setUp(self):self.setup_cfe();self.a1=self.asset()
    def pause(self):
        _,token=inspect_intake(actor=self.manager,slot_id=self.slot1.pk)
        p=prepare_intake(actor=self.manager,slot_id=self.slot1.pk,state_token=token,action='pause',reason='COORDINATION')
        confirm_intake(actor=self.manager,slot_id=self.slot1.pk,proposal_token=p['proposal_token'],confirmed=True)
    def test_planning_lists_current_clinic_only(self):
        d=maintenance_schedule(self.manager,self.a1.pk)
        self.assertIn(self.slot1.pk,[s.pk for s in d['rows']]);self.assertNotIn(self.slot2.pk,[s.pk for s in d['rows']])
    def test_selected_slot_uses_existing_protected_visit_impact(self):
        self.book();d=maintenance_schedule(self.manager,self.a1.pk,slot=str(self.slot1.pk))
        self.assertEqual((d['impact'].visit_count,d['impact'].blocking_visits),(1,1));self.assertTrue(d['blocked'])
    def test_maintenance_and_planning_do_not_change_booking_or_money(self):
        v=self.book();self.change(self.a1);before=AuditEvent.objects.count()
        maintenance_schedule(self.manager,self.a1.pk,slot=str(self.slot1.pk));v.refresh_from_db();self.slot1.refresh_from_db()
        self.assertEqual(v.status,'SCHEDULED');self.assertFalse(self.slot1.booking_paused)
        self.assertFalse(Invoice.objects.exists());self.assertFalse(CashEntry.objects.exists());self.assertEqual(AuditEvent.objects.count(),before)
    def test_cross_clinic_slot_is_rejected(self):
        with self.assertRaises(AvailabilitySlot.DoesNotExist):maintenance_schedule(self.manager,self.a1.pk,slot=str(self.slot2.pk))
    def test_malformed_slot_is_rejected(self):
        for slot in ['-1','0',str(2**63),'//evil.example','9'*5000]:
            with self.assertRaises(RuleError):maintenance_schedule(self.manager,self.a1.pk,slot=slot)
    def test_only_active_manager_can_plan(self):
        for actor in [self.fin,self.hq,self.front,self.doctor,self.pa,self.tech]:
            with self.assertRaises(PermissionDenied):maintenance_schedule(actor,self.a1.pk)
    def test_task_path_requires_explicit_pause(self):
        self.assertFalse(maintenance_schedule(self.manager,self.a1.pk,slot=str(self.slot1.pk))['task_eligible'])
        self.pause();d=maintenance_schedule(self.manager,self.a1.pk,slot=str(self.slot1.pk))
        self.assertTrue(d['task_eligible']);self.assertFalse(CoordinationTask.objects.exists())
    def test_existing_task_is_returned_without_creating_another(self):
        self.pause();_,token=inspect_task(actor=self.manager,slot_id=self.slot1.pk)
        p=prepare_task(actor=self.manager,slot_id=self.slot1.pk,task_id=None,state_token=token,action='open',
            reason=ACTION_REASONS['open'][0],purpose='REPLACE')
        result=confirm_task(actor=self.manager,slot_id=self.slot1.pk,task_id=None,proposal_token=p['proposal_token'],confirmed=True)
        d=maintenance_schedule(self.manager,self.a1.pk,slot=str(self.slot1.pk))
        self.assertEqual(d['existing_task'].pk,result.task_id);self.assertEqual(CoordinationTask.objects.count(),1)
    def test_past_inactive_slot_is_history_not_task_eligibility(self):
        now=timezone.now();slot=AvailabilitySlot.objects.create(clinic=self.a,dentist=self.d1,
            starts_at=now-timedelta(days=2),ends_at=now-timedelta(days=1),is_active=False)
        d=maintenance_schedule(self.manager,self.a1.pk,slot=str(slot.pk));self.assertFalse(d['task_eligible'])
        self.assertTrue(d['blocked']);self.assertNotIn(slot.pk,[s.pk for s in d['rows']])
    def test_maintenance_form_offers_service_or_retirement(self):
        self.change(self.a1);c=WorkspaceClient();c.force_login(self.manager)
        r=c.get(reverse('equipment_change',args=[self.a1.pk]))
        self.assertEqual([code for code,label in r.context['form'].fields['kind'].choices],['SERVICE','RETIRE'])
        self.assertEqual(r.context['form'].initial['kind'],'SERVICE')
        form=EquipmentActionForm(dict(kind='MAINTENANCE',performed_on=self.today,note='重复送修'),state='MAINTENANCE')
        self.assertFalse(form.is_valid())
    def test_native_equipment_dates_render_a_valid_business_day(self):
        c=WorkspaceClient();c.force_login(self.manager)
        for name,args in [('equipment_register',[]),('equipment_change',[self.a1.pk])]:
            r=c.get(reverse(name,args=args));self.assertContains(r,'value="'+self.today.isoformat()+'"')
    def test_native_reschedule_search_date_is_valid(self):
        v=self.book();c=WorkspaceClient();c.force_login(self.front)
        r=c.get(reverse('visit_reschedule',args=[v.pk]));self.assertTrue(r.context['search'].is_valid())
        day=r.context['search'].cleaned_data['day']
        self.assertContains(r,'value="'+day.isoformat()+'"')
    def test_retired_equipment_get_is_readable_but_edit_form_closed(self):
        self.change(self.a1,kind='RETIRE');c=WorkspaceClient();c.force_login(self.manager)
        self.assertEqual(c.get(reverse('equipment_detail',args=[self.a1.pk])).status_code,200)
        self.assertEqual(c.get(reverse('equipment_change',args=[self.a1.pk])).status_code,409)
    @override_settings(ADC_READ_ONLY=True)
    def test_readonly_planning_omits_write_handoff(self):
        c=WorkspaceClient();c.force_login(self.manager);r=c.get(reverse('equipment_schedule',args=[self.a1.pk]),{'slot':self.slot1.pk})
        self.assertEqual(r.status_code,200);self.assertNotContains(r,'交给前台协调任务')
    def test_handoff_http_has_no_patient_identifiers(self):
        self.book();c=WorkspaceClient();c.force_login(self.manager)
        r=c.get(reverse('equipment_schedule',args=[self.a1.pk]),{'slot':self.slot1.pk})
        self.assertEqual(r.status_code,200);self.assertNotContains(r,self.p1.name);self.assertNotContains(r,self.p1.patient_no)
        self.assertContains(r,'核对出诊与接收状态')
