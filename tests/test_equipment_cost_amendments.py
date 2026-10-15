"""PostgreSQL source history, independent decisions, cash linkage and HTTP boundaries."""
from decimal import Decimal as D
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.db import transaction,IntegrityError,connection
from django.test import TransactionTestCase,override_settings
from django.urls import reverse
from django.test.utils import CaptureQueriesContext
from accounts.models import UserAccount,RoleAssignment
from adc_core.rules import RuleError
from care.models import AuditEvent
from equipment.models import EquipmentCostAmendment
from equipment.costs import prepare_cost,confirm_cost,prepare_cost_review,confirm_cost_review,effective_cost,cost_history
from equipment.fees import fee_worklist
from finance.cash_services import prepare_cash,confirm_cash_request
from finance.cash_models import CashEntry
from finance.cash_selectors import event_net
from tests.test_care_finance_equipment import CFEFixture,activate
from tests.workspace_client import WorkspaceClient

class CostAmendmentTests(CFEFixture,TransactionTestCase):
    def setUp(self):
        self.setup_cfe();self.a1=self.asset(acquisition_cost=None);self.event=self.a1.events.get(sequence=0)
    def preview(self,**kw):
        data=dict(actor=self.manager,event_id=self.event.pk,proposed_cost=D('120.01'),reason='合成原始凭据核对补录')
        data.update(kw);return prepare_cost(**data)
    def request(self,**kw):
        p=self.preview(**kw);return confirm_cost(actor=kw.get('actor',self.manager),proposal_token=p['proposal_token'],confirmed=True)[0]
    def review_preview(self,row,**kw):
        data=dict(actor=self.fin,amendment_id=row.pk,decision='approve',reason='合成独立核对原始凭据')
        data.update(kw);return prepare_cost_review(**data)
    def decide(self,row,**kw):
        p=self.review_preview(row,**kw)
        return confirm_cost_review(actor=kw.get('actor',self.fin),proposal_token=p['proposal_token'],confirmed=True)[0]
    def client_for(self,actor):
        c=WorkspaceClient(enforce_csrf_checks=True);c.force_login(actor);return c
    def test_preview_and_get_never_change_business(self):
        before=AuditEvent.objects.count();self.preview();cost_history(self.manager,self.event.pk)
        self.assertFalse(EquipmentCostAmendment.objects.exists());self.assertFalse(CashEntry.objects.exists());self.assertEqual(before,AuditEvent.objects.count())
    def test_pending_is_not_effective_or_cash(self):
        row=self.request();self.assertEqual(row.state,'PENDING');self.assertEqual(effective_cost(self.event),(None,None))
        self.assertEqual(fee_worklist(self.fin)['totals']['unknown_cost'],1);self.assertFalse(CashEntry.objects.exists())
    def test_unknown_supplement_retains_original_and_lifecycle(self):
        row=self.decide(self.request());self.event.refresh_from_db();self.a1.refresh_from_db()
        self.assertIsNone(self.event.cost);self.assertIsNone(self.a1.acquisition_cost);self.assertEqual(self.a1.state,'IN_SERVICE');self.assertEqual(self.a1.lock_version,0)
        self.assertEqual(effective_cost(self.event),(D('120.01'),row.pk));self.assertFalse(CashEntry.objects.exists())
    def test_expense_binds_approved_source_revision(self):
        row=self.decide(self.request());e=self.expense(self.a1)
        self.assertEqual((e.amount,e.equipment_cost_amendment_id),(D('120.01'),row.pk));self.approve(e)
        self.assertEqual(event_net(self.event.pk),D('120.01'));self.assertEqual(fee_worklist(self.fin)['totals']['recorded_cost'],D('120.01'))
    def test_zero_is_explicit_and_cannot_post_positive_expense(self):
        row=self.decide(self.request(proposed_cost=D('0')))
        self.assertEqual(effective_cost(self.event),(D('0'),row.pk));self.assertEqual(fee_worklist(self.fin)['totals']['zero_cost'],1)
        with self.assertRaises(RuleError):self.expense(self.a1)
    def test_rejection_preserves_unknown_and_future_request(self):
        self.decide(self.request(),decision='reject');self.assertEqual(effective_cost(self.event),(None,None));self.request(proposed_cost=D('60'))
        self.assertEqual(EquipmentCostAmendment.objects.count(),2)
    def test_repeated_request_returns_current_terminal_state(self):
        p=self.preview();r=confirm_cost(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0];self.decide(r)
        r,repeated=confirm_cost(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(repeated);self.assertEqual(r.state,'APPROVED');self.assertEqual(EquipmentCostAmendment.objects.count(),1)
    def test_repeated_review_is_idempotent(self):
        r=self.request();p=self.review_preview(r)
        confirm_cost_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        row,repeated=confirm_cost_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(repeated);self.assertEqual(row.state,'APPROVED')
    def test_concurrent_duplicate_review_one_effective_basis(self):
        r=self.request();p=self.review_preview(r)
        results=self.race(lambda i:confirm_cost_review(actor=self.actor_copy(self.fin),proposal_token=p['proposal_token'],confirmed=True))
        self.assertEqual(sorted(x[1] for x in results),[False,True]);self.assertEqual(EquipmentCostAmendment.objects.filter(state='APPROVED').count(),1)
    def test_competing_manager_requests_cannot_overwrite(self):
        other=UserAccount.objects.create_user(username='cost_other_manager');RoleAssignment.objects.create(user=other,role='MANAGER',scope_kind='CLINIC',clinic=self.a);activate(other,'MANAGER',self.a)
        actors=[self.manager,other];previews=[self.preview(actor=a) for a in actors]
        def run(i):
            try:return confirm_cost(actor=self.actor_copy(actors[i]),proposal_token=previews[i]['proposal_token'],confirmed=True)[0].pk
            except RuleError:return None
        results=self.race(run);self.assertEqual(sum(x is not None for x in results),1);self.assertEqual(EquipmentCostAmendment.objects.count(),1)
    def test_same_person_cannot_self_review_by_switching_role(self):
        row=self.request();RoleAssignment.objects.create(user=self.manager,role='FINANCE',scope_kind='CHAIN');activate(self.manager,'FINANCE')
        with self.assertRaises(RuleError):self.review_preview(row,actor=self.manager)
    def test_revoked_preparer_blocks_approval_but_allows_rejection(self):
        row=self.request();p=self.review_preview(row);RoleAssignment.objects.filter(user=self.manager,role='MANAGER').update(is_active=False)
        with self.assertRaises(RuleError):confirm_cost_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(self.decide(row,decision='reject').state,'REJECTED')
    def test_revoked_reviewer_and_inactive_preparer(self):
        r=self.request();p=self.review_preview(r);RoleAssignment.objects.filter(user=self.fin,role='FINANCE').update(is_active=False)
        with self.assertRaises(PermissionDenied):confirm_cost_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        r.refresh_from_db();self.assertEqual(r.state,'PENDING')
    def test_context_switch_invalidates_old_request(self):
        p=self.preview();RoleAssignment.objects.create(user=self.manager,role='MANAGER',scope_kind='CLINIC',clinic=self.b);activate(self.manager,'MANAGER',self.b)
        with self.assertRaises(RuleError):confirm_cost(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
    def test_cross_clinic_read_and_write_rejected(self):
        RoleAssignment.objects.create(user=self.manager,role='MANAGER',scope_kind='CLINIC',clinic=self.b);activate(self.manager,'MANAGER',self.b)
        with self.assertRaises(self.event.DoesNotExist):self.preview()
        with self.assertRaises(self.event.DoesNotExist):cost_history(self.manager,self.event.pk)
    def test_other_roles_have_no_cost_write_permission(self):
        for actor in (self.front,self.hq,self.fin,self.doctor,self.pa,self.tech):
            with self.assertRaises(PermissionDenied):self.preview(actor=actor)
    @override_settings(ADC_READ_ONLY=True)
    def test_read_only_command_rejects_mutation(self):
        p=self.preview()
        with self.assertRaises(PermissionDenied):confirm_cost(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
    def test_retired_equipment_cost_can_be_supplemented_without_reactivation(self):
        self.change(self.a1,kind='RETIRE');self.decide(self.request());self.a1.refresh_from_db()
        self.assertEqual(self.a1.state,'RETIRED');self.assertEqual(self.a1.events.count(),2)
    def test_service_event_can_be_supplemented_independently(self):
        a=self.change(self.a1,kind='SERVICE',cost=None);self.event=a.events.get(kind='SERVICE');self.decide(self.request())
        self.assertEqual(a.events.get(sequence=0).cost,None);self.assertEqual(effective_cost(self.event)[0],D('120.01'))
    def test_non_fee_event_cannot_be_amended(self):
        a=self.change(self.a1,kind='MAINTENANCE');self.event=a.events.get(kind='MAINTENANCE')
        with self.assertRaises(self.event.DoesNotExist):self.preview()
    def test_noop_negative_fractional_nonfinite_inputs_rejected(self):
        self.decide(self.request())
        for value in (D('120.01'),D('-1'),D('0.001'),D('NaN'),D('Infinity'),D('100000000000000')):
            with self.assertRaises(RuleError):self.preview(proposed_cost=value)
    def test_empty_or_oversized_reason_rejected(self):
        for reason in ('',' ','x'*501):
            with self.assertRaises(RuleError):self.preview(reason=reason)
    def test_pending_cost_blocks_new_expense_and_stale_cash_preview(self):
        a=self.asset(asset_code='KNOWN');self.event=a.events.get(sequence=0)
        p=prepare_cash(actor=self.manager,source_type='equipment',source_id=self.event.pk,kind='EQUIPMENT_EXPENSE',occurred_on=self.today,reason='合成',**self.evidence())
        self.request(proposed_cost=D('450'))
        with self.assertRaises(RuleError):confirm_cash_request(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        with self.assertRaises(RuleError):self.expense(a)
    def test_pending_cash_blocks_cost_request(self):
        a=self.asset(asset_code='KNOWN');self.event=a.events.get(sequence=0);self.expense(a)
        with self.assertRaises(RuleError):self.preview()
    def test_posted_fee_requires_reviewed_reversal_before_amendment(self):
        first=self.decide(self.request());expense=self.approve(self.expense(self.a1))
        with self.assertRaises(RuleError):self.preview(proposed_cost=D('80'))
        p=prepare_cash(actor=self.manager,source_type='equipment',source_id=self.event.pk,kind='EXPENSE_REVERSAL',reversal_id=expense.pk,occurred_on=self.today,reason='合成费用错误冲回',**self.evidence())
        reverse_entry=confirm_cash_request(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]
        self.assertEqual(reverse_entry.equipment_cost_amendment_id,first.pk)
        with self.assertRaises(RuleError):self.preview(proposed_cost=D('80'))
        self.approve(reverse_entry);second=self.decide(self.request(proposed_cost=D('80')));repost=self.approve(self.expense(self.a1))
        self.assertEqual((repost.amount,repost.equipment_cost_amendment_id,event_net(self.event.pk)),(D('80'),second.pk,D('80')))
        expense.refresh_from_db();self.assertEqual(expense.amount,D('120.01'));self.assertEqual(second.based_amendment_id,first.pk)
        totals=fee_worklist(self.fin)['totals'];self.assertEqual((totals['events'],totals['recorded_cost'],totals['net_expense']),(1,D('80'),D('80')))
    def test_amendment_changes_invalidate_old_expense_preview(self):
        a=self.asset(asset_code='KNOWN');self.event=a.events.get(sequence=0)
        p=prepare_cash(actor=self.manager,source_type='equipment',source_id=self.event.pk,kind='EQUIPMENT_EXPENSE',occurred_on=self.today,reason='合成',**self.evidence())
        self.decide(self.request(proposed_cost=D('350')))
        with self.assertRaises(RuleError):confirm_cash_request(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
    def test_audit_failure_rolls_back_request_and_review(self):
        with patch('equipment.costs.emit',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):self.request()
        self.assertFalse(EquipmentCostAmendment.objects.exists());row=self.request()
        with patch('equipment.costs.emit',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):self.decide(row)
        row.refresh_from_db();self.assertEqual(row.state,'PENDING');self.assertEqual(effective_cost(self.event),(None,None))
    def test_database_history_and_self_review_guards(self):
        row=self.request()
        for action in (lambda:EquipmentCostAmendment.objects.filter(pk=row.pk).update(proposed_cost=D('1')),
            lambda:EquipmentCostAmendment.objects.filter(pk=row.pk).delete(),
            lambda:EquipmentCostAmendment.objects.filter(pk=row.pk).update(state='APPROVED',lock_version=1,reviewed_by=self.manager,reviewed_at=row.prepared_at,review_reason='合成')):
            with self.assertRaises(IntegrityError),transaction.atomic():action()
        self.assertEqual(EquipmentCostAmendment.objects.get(pk=row.pk).state,'PENDING')
    def test_database_rejects_invalid_cost_basis_and_direct_posted_insert(self):
        row=self.request()
        for data in (dict(state='APPROVED',reviewed_by=self.fin,reviewed_at=row.prepared_at,lock_version=1,review_reason='合成'),dict(previous_cost=D('9')),dict(event=self.change(self.a1,kind='MAINTENANCE').events.get(kind='MAINTENANCE'))):
            base=dict(event=self.event,previous_cost=None,proposed_cost=D('10'),prepared_by=self.manager,reason='合成');base.update(data)
            with self.assertRaises(IntegrityError),transaction.atomic():EquipmentCostAmendment.objects.create(**base)
    def test_cash_database_rejects_mismatched_approved_revision(self):
        row=self.decide(self.request());a=self.asset(asset_code='OTHER');e=a.events.get(sequence=0)
        base=dict(equipment_event=e,equipment_cost_amendment=row,clinic=self.a,kind='EQUIPMENT_EXPENSE',amount=D('120.01'),occurred_on=self.today,reason='合成',prepared_by=self.manager)
        with self.assertRaises(IntegrityError),transaction.atomic():CashEntry.objects.create(**base)
        base.update(equipment_event=self.event,equipment_cost_amendment=None)
        with self.assertRaises(IntegrityError),transaction.atomic():CashEntry.objects.create(**base)
    def test_terminal_cost_decision_cannot_be_rewritten(self):
        row=self.decide(self.request())
        with self.assertRaises(IntegrityError),transaction.atomic():EquipmentCostAmendment.objects.filter(pk=row.pk).update(review_reason='changed')
    def test_confirm_requires_explicit_true_and_correct_destination(self):
        p=self.preview()
        for kwargs in (dict(confirmed=False),dict(confirmed=True,expected_event_id=self.event.pk+1)):
            with self.assertRaises(RuleError):confirm_cost(actor=self.manager,proposal_token=p['proposal_token'],**kwargs)
    def test_approved_totals_are_bounded_queries_and_do_not_multiply_cash(self):
        self.decide(self.request());self.approve(self.expense(self.a1))
        with CaptureQueriesContext(connection) as first:fee_worklist(self.fin)
        for n in range(10):self.asset(asset_code='MORE-'+str(n),acquisition_cost=None)
        with CaptureQueriesContext(connection) as many:fee_worklist(self.fin)
        self.assertEqual(len(first),len(many));self.assertEqual(fee_worklist(self.fin)['totals']['recorded_cost'],D('120.01'))
    def test_http_preview_confirmation_csrf_and_no_write_get(self):
        c=self.client_for(self.manager);url=reverse('equipment_cost_request',args=[self.event.pk]);r=c.get(url)
        self.assertEqual(r.status_code,200);self.assertFalse(EquipmentCostAmendment.objects.exists())
        self.assertEqual(c.post(url,dict(action='preview',proposed_cost='120.01',reason='合成')).status_code,403)
        data=dict(action='preview',proposed_cost='120.01',reason='合成',csrfmiddlewaretoken=c.cookies['csrftoken'].value)
        r=c.post(url,data);self.assertEqual(r.status_code,200);self.assertContains(r,'拟核实整笔费用')
        token=r.context['form'].initial['proposal_token'];r=c.post(url,dict(action='confirm',confirmed='on',proposal_token=token,csrfmiddlewaretoken=c.cookies['csrftoken'].value))
        self.assertEqual(r.status_code,302);self.assertEqual(EquipmentCostAmendment.objects.count(),1)
    def test_seven_role_http_boundaries(self):
        history=reverse('equipment_cost_history',args=[self.event.pk]);edit=reverse('equipment_cost_request',args=[self.event.pk])
        for actor in (self.manager,self.fin,self.hq,self.front,self.doctor,self.pa,self.tech):
            c=self.client_for(actor);allowed=actor in (self.manager,self.fin,self.hq)
            self.assertEqual(c.get(history).status_code,200 if allowed else 403)
            self.assertEqual(c.get(edit).status_code,200 if actor==self.manager else 403)
    def test_review_preview_shows_original_reason_and_no_cash_effect(self):
        row=self.request();c=self.client_for(self.fin);url=reverse('equipment_cost_review',args=[row.pk])
        r=c.get(url);self.assertContains(r,row.reason);self.assertContains(r,'120.01')
        r=c.post(url,dict(action='preview',decision='approve',reason='独立合成核对',csrfmiddlewaretoken=c.cookies['csrftoken'].value))
        self.assertEqual(r.status_code,200);self.assertContains(r,'不会自动记账');self.assertFalse(CashEntry.objects.exists())
    def test_history_pagination_and_pending_queue_scope(self):
        for n in range(21):self.decide(self.request(proposed_cost=D(n+1)),decision='reject')
        data=cost_history(self.manager,self.event.pk,'2');self.assertEqual(len(data['amendments']),1)
        self.request();c=self.client_for(self.fin);r=c.get(reverse('equipment_cost_queue'));self.assertEqual(r.context['page_obj'].paginator.count,1)
        c=self.client_for(self.front);self.assertEqual(c.get(reverse('equipment_cost_queue')).status_code,403)
    def test_cost_pending_is_visible_and_suppresses_expense_link(self):
        a=self.asset(asset_code='KNOWN');self.event=a.events.get(sequence=0);self.request(proposed_cost=D('400'))
        data=fee_worklist(self.manager);row=next(e for e in data['rows'] if e.pk==self.event.pk)
        self.assertEqual(row.fee_state,'COST_PENDING');self.assertTrue(row.pending_cost_amendment)
    def test_oversized_http_identifiers_are_404(self):
        c=self.client_for(self.manager)
        for route in ('equipment_cost_history','equipment_cost_request'):
            self.assertEqual(c.get(reverse(route,args=[2**70])).status_code,404)
        self.assertEqual(self.client_for(self.fin).get(reverse('equipment_cost_review',args=[2**70])).status_code,404)
    def test_invalid_command_identifiers_fail_closed(self):
        for value in (False,0,-1,2**70):
            with self.assertRaises(RuleError):self.preview(event_id=value)
    def test_cash_and_cost_competition_has_only_one_pending_workflow(self):
        a=self.asset(asset_code='KNOWN');self.event=a.events.get(sequence=0)
        other=UserAccount.objects.create_user(username='cost_race_manager');RoleAssignment.objects.create(user=other,role='MANAGER',scope_kind='CLINIC',clinic=self.a);activate(other,'MANAGER',self.a)
        cash=prepare_cash(actor=self.manager,source_type='equipment',source_id=self.event.pk,kind='EQUIPMENT_EXPENSE',occurred_on=self.today,reason='合成竞争记账',**self.evidence())
        cost=self.preview(actor=other)
        def run(i):
            try:
                if i==0:return confirm_cash_request(actor=self.actor_copy(self.manager),proposal_token=cash['proposal_token'],confirmed=True)[0].pk
                return confirm_cost(actor=self.actor_copy(other),proposal_token=cost['proposal_token'],confirmed=True)[0].pk
            except RuleError:return None
        results=self.race(run);self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(CashEntry.objects.filter(state='PENDING').count()+EquipmentCostAmendment.objects.filter(state='PENDING').count(),1)
    def test_inactive_preparer_cannot_be_approved(self):
        row=self.request();UserAccount.objects.filter(pk=self.manager.pk).update(is_active=False)
        with self.assertRaises(RuleError):self.review_preview(row)
        self.assertEqual(self.decide(row,decision='reject').state,'REJECTED')
    def test_inactive_source_clinic_prevents_approval(self):
        row=self.request();type(self.a).objects.filter(pk=self.a.pk).update(is_active=False)
        with self.assertRaises(RuleError):self.review_preview(row)
        self.assertEqual(self.decide(row,decision='reject').state,'REJECTED')
    def test_http_independent_review_confirmation_is_effective_without_cash(self):
        row=self.request();c=self.client_for(self.fin);url=reverse('equipment_cost_review',args=[row.pk]);c.get(url)
        r=c.post(url,dict(action='preview',decision='approve',reason='合成独立核对',csrfmiddlewaretoken=c.cookies['csrftoken'].value))
        token=r.context['form'].initial['proposal_token']
        r=c.post(url,dict(action='confirm',confirmed='on',proposal_token=token,csrfmiddlewaretoken=c.cookies['csrftoken'].value))
        self.assertEqual(r.status_code,302);self.assertEqual(effective_cost(self.event),(D('120.01'),row.pk));self.assertFalse(CashEntry.objects.exists())
    def test_new_revision_cash_source_cannot_be_rewritten(self):
        row=self.decide(self.request());e=self.expense(self.a1)
        with self.assertRaises(IntegrityError),transaction.atomic():CashEntry.objects.filter(pk=e.pk).update(equipment_cost_amendment=None)
    def test_approved_revision_cannot_point_to_another_event(self):
        approved=self.decide(self.request());a=self.asset(asset_code='OTHER');other=a.events.get(sequence=0)
        with self.assertRaises(IntegrityError),transaction.atomic():EquipmentCostAmendment.objects.create(event=other,based_amendment=approved,
            previous_cost=D('120.01'),proposed_cost=D('10'),reason='合成错误依据',prepared_by=self.manager)
    def test_stale_request_after_rejection_does_not_reopen_history(self):
        p=self.preview();row=confirm_cost(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0];self.decide(row,decision='reject')
        self.decide(self.request(proposed_cost=D('10')))
        replay,repeated=confirm_cost(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(repeated);self.assertEqual(replay.state,'REJECTED');self.assertEqual(effective_cost(self.event)[0],D('10'))
