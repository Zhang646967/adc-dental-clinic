"""Executed PostgreSQL maintenance ownership, independent acceptance and history checks."""
from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import patch
from uuid import uuid4
from django.core.exceptions import PermissionDenied
from django.db import transaction,IntegrityError,connection
from django.test import TransactionTestCase,override_settings
from django.urls import reverse
from django.utils import timezone
from django.test.utils import CaptureQueriesContext
from accounts.models import UserAccount,RoleAssignment
from adc_core.rules import RuleError
from care.models import AuditEvent
from equipment.models import EquipmentEvent
from equipment.maintenance_models import MaintenanceOrder,MaintenanceAction
from equipment.maintenance_services import prepare_maintenance,confirm_maintenance,order_scope,snapshot
from finance.cash_models import CashEntry
from finance.cash_services import prepare_cash,confirm_cash_request
from scheduling.models import AvailabilitySlot,Visit
from tests.test_care_finance_equipment import CFEFixture,activate
from tests.workspace_client import WorkspaceClient

class MaintenanceTests(CFEFixture,TransactionTestCase):
    def setUp(self):
        self.setup_cfe();self.equip=self.change(self.asset(),kind='MAINTENANCE')
        self.reviewer=UserAccount.objects.create_user(username='maint_reviewer')
        RoleAssignment.objects.create(user=self.reviewer,role='MANAGER',scope_kind='CLINIC',clinic=self.a);activate(self.reviewer,'MANAGER',self.a)
    def preview(self,**kw):
        values=dict(actor=self.manager,asset_id=self.equip.pk,action='OPEN',fields=dict(owner=self.manager.pk,due=self.today,issue='合成设备异常，需要维修核查'),note='合成责任分配')
        values.update(kw);return prepare_maintenance(**values)
    def open(self,**kw):
        p=self.preview(**kw);return confirm_maintenance(actor=kw.get('actor',self.manager),proposal_token=p['proposal_token'],confirmed=True)[0]
    def action_preview(self,row,action,actor=None,fields=None):
        return prepare_maintenance(actor=actor or self.manager,asset_id=row.asset_id,order_id=row.pk,action=action,fields=fields or {},note='合成办理依据 '+action)
    def act(self,row,action,actor=None,fields=None):
        p=self.action_preview(row,action,actor,fields)
        return confirm_maintenance(actor=actor or self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]
    def report_fields(self,**kw):
        data=dict(performed=self.today,cost=D('20.01'),next_due=self.today+timedelta(days=30),evidence='合成维修凭据 TEST-001，已核对工作情况',schedule_checked=True);data.update(kw);return data
    def ready(self,**kw):
        row=self.act(self.open(),'START');return self.act(row,'SUBMIT',fields=self.report_fields(**kw))
    def client_for(self,user):
        c=WorkspaceClient(enforce_csrf_checks=True);c.force_login(user);return c
    def test_preview_creates_no_history(self):
        before=AuditEvent.objects.count();self.preview();self.assertEqual(before,AuditEvent.objects.count());self.assertFalse(MaintenanceOrder.objects.exists())
    def test_requires_current_stopped_asset(self):
        other=self.asset(asset_code='RUNNING')
        with self.assertRaises(RuleError):self.preview(asset_id=other.pk)
        self.change(self.equip,kind='RETIRE')
        with self.assertRaises(RuleError):self.preview()
    def test_open_assigns_responsibility_without_cash_or_schedule_change(self):
        before=list(AvailabilitySlot.objects.order_by('pk').values());row=self.open()
        self.assertEqual(row.state,'ASSIGNED');self.assertEqual(row.assigned_to_id,self.manager.pk)
        self.assertEqual(list(AvailabilitySlot.objects.order_by('pk').values()),before);self.assertFalse(CashEntry.objects.exists())
        self.equip.refresh_from_db();self.assertEqual(self.equip.state,'MAINTENANCE');self.assertEqual(row.actions.count(),1)
    def test_only_one_live_order_and_stale_open_after_cancel(self):
        p=self.preview();row=self.open()
        with self.assertRaises(RuleError):self.preview()
        self.act(row,'CANCEL')
        with self.assertRaises(RuleError):confirm_maintenance(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        new=self.open();self.assertNotEqual(new.pk,row.pk)
    def test_only_assigned_owner_can_start_or_submit(self):
        row=self.open()
        with self.assertRaises(RuleError):self.act(row,'START',actor=self.reviewer)
        row=self.act(row,'START')
        with self.assertRaises(RuleError):self.act(row,'SUBMIT',actor=self.reviewer,fields=self.report_fields())
    def test_complete_independent_acceptance_exact_service_event(self):
        row=self.ready();self.equip.refresh_from_db();self.assertEqual(self.equip.state,'MAINTENANCE');self.assertFalse(row.service_event_id)
        row=self.act(row,'APPROVE',actor=self.reviewer);event=row.service_event
        self.assertEqual((row.state,event.kind,event.previous_state,event.next_state),('CLOSED','SERVICE','MAINTENANCE','IN_SERVICE'))
        self.assertEqual((event.cost,event.note,event.recorded_by_id),(D('20.01'),row.completion_note,self.reviewer.pk));self.assertEqual(event.sequence,row.maintenance_event.sequence+1)
        self.equip.refresh_from_db();self.assertEqual(self.equip.next_service_due,self.today+timedelta(days=30));self.assertFalse(CashEntry.objects.exists())
    def test_cannot_self_approve_or_return(self):
        row=self.ready()
        for action in ('APPROVE','RETURN'):
            with self.assertRaises(RuleError):self.act(row,action)
    def test_switching_role_cannot_enable_self_acceptance(self):
        row=self.ready();RoleAssignment.objects.create(user=self.manager,role='FINANCE',scope_kind='CHAIN');activate(self.manager,'FINANCE')
        with self.assertRaises(PermissionDenied):self.act(row,'APPROVE')
        activate(self.manager,'MANAGER',self.a)
        with self.assertRaises(RuleError):self.act(row,'APPROVE')
    def test_return_retains_original_submission_and_requires_resubmit(self):
        row=self.ready();first=row.completion_note;row=self.act(row,'RETURN',actor=self.reviewer)
        self.assertEqual((row.state,row.completion_note,row.submitted_by_id),('IN_PROGRESS','',None))
        self.assertEqual(row.actions.get(action='SUBMIT').snapshot['evidence'],first)
        with self.assertRaises(RuleError):self.act(row,'APPROVE',actor=self.reviewer)
        row=self.act(row,'SUBMIT',fields=self.report_fields(cost='30.02',evidence='合成补充检查 TEST-002'));row=self.act(row,'APPROVE',actor=self.reviewer)
        self.assertEqual(row.service_event.cost,D('30.02'));self.assertEqual(row.actions.filter(action='SUBMIT').count(),2)
    def test_owner_withdraws_before_correcting_report(self):
        row=self.ready()
        with self.assertRaises(RuleError):self.act(row,'WITHDRAW',actor=self.reviewer)
        row=self.act(row,'WITHDRAW');self.assertEqual(row.state,'IN_PROGRESS')
        self.assertEqual(row.actions.get(action='SUBMIT').snapshot['cost'],'20.01')
    def test_assignment_changes_owner_and_requires_new_start(self):
        row=self.act(self.open(),'START');row=self.act(row,'ASSIGN',fields=dict(owner=self.reviewer.pk,due=self.today+timedelta(days=2)))
        self.assertEqual((row.assigned_to_id,row.state),(self.reviewer.pk,'ASSIGNED'))
        with self.assertRaises(RuleError):self.act(row,'START')
        row=self.act(row,'START',actor=self.reviewer);self.assertEqual(row.state,'IN_PROGRESS')
    def test_noop_or_stale_assignment_refused(self):
        row=self.open()
        with self.assertRaises(RuleError):self.act(row,'ASSIGN',fields=dict(owner=self.manager.pk,due=self.today))
        p=self.action_preview(row,'START');self.act(row,'ASSIGN',fields=dict(owner=self.reviewer.pk,due=self.today))
        with self.assertRaises(RuleError):confirm_maintenance(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
    def test_owner_must_be_current_clinic_manager(self):
        for owner in (self.front.pk,self.fin.pk,True,0):
            with self.assertRaises(RuleError):self.preview(fields=dict(owner=owner,due=self.today,issue='合成'))
        RoleAssignment.objects.filter(user=self.reviewer).update(clinic=self.b)
        with self.assertRaises(RuleError):self.preview(fields=dict(owner=self.reviewer.pk,due=self.today,issue='合成'))
    def test_expired_new_deadline_and_future_repair_refused(self):
        with self.assertRaises(RuleError):self.preview(fields=dict(owner=self.manager.pk,due=self.today-timedelta(days=1),issue='合成'))
        row=self.act(self.open(),'START')
        for fields in (self.report_fields(performed=self.today+timedelta(days=1)),self.report_fields(performed=self.today-timedelta(days=1)),self.report_fields(next_due=self.today)):
            with self.assertRaises(RuleError):self.act(row,'SUBMIT',fields=fields)
    def test_missing_schedule_acknowledgement_and_invalid_money_refused(self):
        row=self.act(self.open(),'START')
        with self.assertRaises(RuleError):self.act(row,'SUBMIT',fields=self.report_fields(schedule_checked=False))
        for value in ('-1','NaN','Infinity','0.001',True):
            with self.assertRaises(RuleError):self.act(row,'SUBMIT',fields=self.report_fields(cost=value))
    def test_unknown_cost_retains_unknown_in_service_event(self):
        row=self.act(self.ready(cost=None,next_due=None),'APPROVE',actor=self.reviewer)
        self.assertIsNone(row.service_event.cost);self.assertIsNone(row.service_event.next_service_due)
    def test_zero_cost_is_explicit_and_cannot_post_positive_fee(self):
        row=self.act(self.ready(cost='0.00'),'APPROVE',actor=self.reviewer);self.assertEqual(row.service_event.cost,D('0'))
        with self.assertRaises(RuleError):prepare_cash(actor=self.manager,source_type='equipment',source_id=row.service_event_id,kind='EQUIPMENT_EXPENSE',occurred_on=self.today,reason='合成',**self.evidence())
    def test_cost_requires_separate_cash_request_and_finance_approval(self):
        row=self.act(self.ready(),'APPROVE',actor=self.reviewer);self.assertFalse(CashEntry.objects.exists())
        p=prepare_cash(actor=self.manager,source_type='equipment',source_id=row.service_event_id,kind='EQUIPMENT_EXPENSE',occurred_on=self.today,reason='合成维修费凭据',**self.evidence())
        entry=confirm_cash_request(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]
        self.assertEqual(entry.state,'PENDING');self.approve(entry);entry.refresh_from_db();self.assertEqual(entry.amount,D('20.01'));self.assertEqual(entry.state,'POSTED')
    def test_cancel_leaves_asset_stopped_and_cannot_bypass_acceptance(self):
        row=self.act(self.open(),'CANCEL');self.equip.refresh_from_db();self.assertEqual(self.equip.state,'MAINTENANCE')
        with self.assertRaises(RuleError):self.change(self.equip,kind='SERVICE',cost='20')
        self.assertEqual(self.change(self.equip,kind='RETIRE').state,'RETIRED')
    def test_pending_report_must_be_returned_or_withdrawn_before_cancel(self):
        row=self.ready()
        for action in ('CANCEL','ASSIGN'):
            with self.assertRaises(RuleError):self.act(row,action,fields=dict(owner=self.reviewer.pk,due=self.today) if action=='ASSIGN' else None)
        row=self.act(row,'WITHDRAW');self.assertEqual(self.act(row,'CANCEL').state,'CANCELLED')
    def test_active_order_blocks_legacy_service_and_retire(self):
        self.open()
        for kind in ('SERVICE','RETIRE'):
            with self.assertRaises(RuleError):self.change(self.equip,kind=kind)
    def test_stale_legacy_preview_cannot_bypass_new_order(self):
        p=self.change_preview(self.equip,kind='SERVICE',cost='5');self.open()
        from equipment.services import confirm_equipment
        with self.assertRaises(RuleError):confirm_equipment(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
    def test_revoked_owner_cannot_be_accepted_but_can_be_reassigned(self):
        row=self.ready();p=self.action_preview(row,'APPROVE',actor=self.reviewer);RoleAssignment.objects.filter(user=self.manager,role='MANAGER').update(is_active=False)
        with self.assertRaises(RuleError):confirm_maintenance(actor=self.reviewer,proposal_token=p['proposal_token'],confirmed=True)
        row=self.act(row,'RETURN',actor=self.reviewer);row=self.act(row,'ASSIGN',actor=self.reviewer,fields=dict(owner=self.reviewer.pk,due=self.today))
        self.assertEqual(row.assigned_to_id,self.reviewer.pk)
    def test_inactive_owner_blocks_acceptance(self):
        row=self.ready();UserAccount.objects.filter(pk=self.manager.pk).update(is_active=False)
        with self.assertRaises(RuleError):self.act(row,'APPROVE',actor=self.reviewer)
    def test_revoked_reviewer_and_inactive_clinic_block_confirmation(self):
        row=self.ready();p=self.action_preview(row,'APPROVE',actor=self.reviewer);RoleAssignment.objects.filter(user=self.reviewer).update(is_active=False)
        with self.assertRaises(PermissionDenied):confirm_maintenance(actor=self.reviewer,proposal_token=p['proposal_token'],confirmed=True)
        RoleAssignment.objects.filter(user=self.reviewer).update(is_active=True);type(self.a).objects.filter(pk=self.a.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):confirm_maintenance(actor=self.reviewer,proposal_token=p['proposal_token'],confirmed=True)
    def test_cross_clinic_access_and_stale_context_refused(self):
        row=self.open();p=self.action_preview(row,'START');RoleAssignment.objects.create(user=self.manager,role='MANAGER',scope_kind='CLINIC',clinic=self.b);activate(self.manager,'MANAGER',self.b)
        self.assertFalse(order_scope(self.manager).filter(pk=row.pk).exists())
        with self.assertRaises(RuleError):confirm_maintenance(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
    def test_other_roles_cannot_write(self):
        for actor in (self.front,self.fin,self.hq,self.doctor,self.pa,self.tech):
            with self.assertRaises(PermissionDenied):self.preview(actor=actor)
    @override_settings(ADC_READ_ONLY=True)
    def test_readonly_rejects_direct_command(self):
        p=self.preview()
        with self.assertRaises(PermissionDenied):confirm_maintenance(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
    def test_signature_confirmation_and_route_binding(self):
        p=self.preview()
        for kw in (dict(confirmed=False),dict(confirmed=True,proposal_token=p['proposal_token']+'x'),dict(confirmed=True,expected_asset_id=self.equip.pk+1,expected_order_id=None,expected_action='OPEN')):
            data=dict(actor=self.manager,proposal_token=p['proposal_token']);data.update(kw)
            with self.assertRaises(RuleError):confirm_maintenance(**data)
    def test_repeat_open_and_acceptance_return_current_facts(self):
        p=self.preview();row=confirm_maintenance(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0];self.act(row,'START');row=self.act(row,'SUBMIT',fields=self.report_fields());a=self.action_preview(row,'APPROVE',actor=self.reviewer)
        row=confirm_maintenance(actor=self.reviewer,proposal_token=a['proposal_token'],confirmed=True)[0]
        for actor,token in [(self.manager,p['proposal_token']),(self.reviewer,a['proposal_token'])]:
            got,repeated=confirm_maintenance(actor=actor,proposal_token=token,confirmed=True);self.assertTrue(repeated);self.assertEqual(got.state,'CLOSED')
        self.assertEqual(EquipmentEvent.objects.filter(asset=self.equip,kind='SERVICE').count(),1)
    def test_replay_does_not_undo_later_equipment_state(self):
        row=self.ready();p=self.action_preview(row,'APPROVE',actor=self.reviewer);confirm_maintenance(actor=self.reviewer,proposal_token=p['proposal_token'],confirmed=True)
        self.equip.refresh_from_db();self.change(self.equip,kind='MAINTENANCE')
        confirm_maintenance(actor=self.reviewer,proposal_token=p['proposal_token'],confirmed=True);self.equip.refresh_from_db();self.assertEqual(self.equip.state,'MAINTENANCE')
    def test_audit_failure_rolls_back_order_and_device_restore(self):
        p=self.preview()
        with patch('equipment.maintenance_services.emit',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):confirm_maintenance(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(MaintenanceOrder.objects.exists());row=self.ready();p=self.action_preview(row,'APPROVE',actor=self.reviewer)
        with patch('equipment.maintenance_services.emit',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):confirm_maintenance(actor=self.reviewer,proposal_token=p['proposal_token'],confirmed=True)
        self.equip.refresh_from_db();row.refresh_from_db();self.assertEqual((row.state,self.equip.state),('READY','MAINTENANCE'));self.assertFalse(row.service_event_id)
    def test_no_raw_evidence_in_audit(self):
        self.ready(evidence='PRIVATE_REPAIR_EVIDENCE')
        self.assertNotIn('PRIVATE_REPAIR_EVIDENCE',str(list(AuditEvent.objects.values('reason','change_summary'))))
    def test_schedule_and_visits_unchanged_by_acceptance(self):
        slots=list(AvailabilitySlot.objects.order_by('pk').values());visits=list(Visit.objects.order_by('pk').values())
        self.act(self.ready(),'APPROVE',actor=self.reviewer)
        self.assertEqual(list(AvailabilitySlot.objects.order_by('pk').values()),slots);self.assertEqual(list(Visit.objects.order_by('pk').values()),visits)
    def test_sql_original_and_action_history_immutable(self):
        row=self.open()
        with self.assertRaises(IntegrityError),transaction.atomic():MaintenanceOrder.objects.filter(pk=row.pk).update(issue='rewrite')
        step=row.actions.get()
        with self.assertRaises(IntegrityError),transaction.atomic():MaintenanceAction.objects.filter(pk=step.pk).update(note='rewrite')
        with self.assertRaises(IntegrityError),transaction.atomic():MaintenanceAction.objects.filter(pk=step.pk).delete()
    def test_sql_state_requires_matching_append_action(self):
        row=self.open()
        with self.assertRaises(IntegrityError),transaction.atomic():
            MaintenanceOrder.objects.filter(pk=row.pk).update(state='IN_PROGRESS',lock_version=1)
            with connection.cursor() as c:c.execute('SET CONSTRAINTS ALL IMMEDIATE')
    def test_sql_terminal_state_cannot_be_rewritten(self):
        row=self.act(self.ready(),'APPROVE',actor=self.reviewer)
        with self.assertRaises(IntegrityError),transaction.atomic():MaintenanceOrder.objects.filter(pk=row.pk).update(review_reason='rewrite',lock_version=row.lock_version+1)
    def raw_restore(self):
        from equipment.models import EquipmentAsset
        a=EquipmentAsset.objects.get(pk=self.equip.pk);old=a.state;a.state='IN_SERVICE';a.next_service_due=None;a.lock_version+=1;a.save(update_fields=['state','next_service_due','lock_version'])
        EquipmentEvent.objects.create(asset=a,operation_id=uuid4(),sequence=a.lock_version,kind='SERVICE',previous_state=old,next_state='IN_SERVICE',performed_on=self.today,cost=D('1'),next_service_due=None,note='raw bypass',recorded_by=self.manager)
        with connection.cursor() as c:c.execute('SET CONSTRAINTS ALL IMMEDIATE')
    def test_sql_blocks_bypass_while_active_and_after_cancel(self):
        row=self.open()
        with self.assertRaises(IntegrityError),transaction.atomic():self.raw_restore()
        self.act(row,'CANCEL')
        with self.assertRaises(IntegrityError),transaction.atomic():self.raw_restore()
    def test_sql_snapshot_matches_saved_action(self):
        row=self.ready()
        with connection.cursor() as c:c.execute('SELECT adc_maintenance_snapshot(w) FROM adc_maintenance_order w WHERE id=%s',[row.pk]);actual=c.fetchone()[0]
        import json
        self.assertEqual(json.loads(actual) if isinstance(actual,str) else actual,snapshot(row));self.assertEqual(row.actions.latest('sequence').snapshot,snapshot(row))
    def test_concurrent_duplicate_open_and_review_single_effect(self):
        p=self.preview();results=self.race(lambda i:confirm_maintenance(actor=self.actor_copy(self.manager),proposal_token=p['proposal_token'],confirmed=True))
        self.assertEqual(sorted(r[1] for r in results),[False,True]);row=self.act(results[0][0],'START');row=self.act(row,'SUBMIT',fields=self.report_fields());p=self.action_preview(row,'APPROVE',actor=self.reviewer)
        results=self.race(lambda i:confirm_maintenance(actor=self.actor_copy(self.reviewer),proposal_token=p['proposal_token'],confirmed=True))
        self.assertEqual(sorted(r[1] for r in results),[False,True]);self.assertEqual(EquipmentEvent.objects.filter(asset=self.equip,kind='SERVICE').count(),1)
    def test_competing_opens_one_active_order(self):
        actors=[self.manager,self.reviewer];previews=[self.preview(actor=a) for a in actors]
        def run(i):
            try:return confirm_maintenance(actor=self.actor_copy(actors[i]),proposal_token=previews[i]['proposal_token'],confirmed=True)[0].pk
            except RuleError:return None
        results=self.race(run);self.assertEqual(sum(v is not None for v in results),1)
    def test_competing_withdraw_and_acceptance_one_transition(self):
        row=self.ready();actors=[self.manager,self.reviewer];previews=[self.action_preview(row,'WITHDRAW'),self.action_preview(row,'APPROVE',actor=self.reviewer)]
        def run(i):
            try:return confirm_maintenance(actor=self.actor_copy(actors[i]),proposal_token=previews[i]['proposal_token'],confirmed=True)[0].state
            except RuleError:return None
        results=self.race(run);self.assertEqual(sum(v is not None for v in results),1);row.refresh_from_db();self.equip.refresh_from_db()
        self.assertEqual(self.equip.state,'IN_SERVICE' if row.state=='CLOSED' else 'MAINTENANCE')
    def test_http_seven_roles_and_current_clinic(self):
        row=self.open()
        for actor,read in [(self.manager,True),(self.fin,True),(self.hq,True),(self.front,False),(self.doctor,False),(self.pa,False),(self.tech,False)]:
            c=self.client_for(actor);self.assertEqual(c.get(reverse('maintenance_list')).status_code,200 if read else 403)
            self.assertEqual(c.get(reverse('maintenance_detail',args=[row.pk])).status_code,200 if read else 403)
            self.assertEqual(c.get(reverse('maintenance_create',args=[self.equip.pk])).status_code,200 if actor==self.manager else 403)
        RoleAssignment.objects.filter(user=self.reviewer).update(clinic=self.b);c=self.client_for(self.reviewer)
        self.assertEqual(c.get(reverse('maintenance_detail',args=[row.pk])).status_code,404)
    def test_http_csrf_dates_and_stale_workspace(self):
        c=self.client_for(self.manager);url=reverse('maintenance_create',args=[self.equip.pk]);response=c.get(url);self.assertContains(response,'type="date"');self.assertFalse(MaintenanceOrder.objects.exists())
        self.assertEqual(c.post(url,{'action':'preview'}).status_code,403)
        self.assertIn(c.post(url,{'action':'preview','csrfmiddlewaretoken':c.cookies['csrftoken'].value,'workspace_token':'bad'}).status_code,(403,409))
    def test_http_links_and_old_status_bypass_guidance(self):
        row=self.open();c=self.client_for(self.manager);self.assertContains(c.get(reverse('equipment_detail',args=[self.equip.pk])),'办理当前维护工单')
        response=c.get(reverse('equipment_change',args=[self.equip.pk]));self.assertEqual(response.status_code,409);self.assertContains(response,'进入当前维护工单',status_code=409)
        self.assertContains(c.get(reverse('maintenance_detail',args=[row.pk])),'核对维护对出诊的影响')
    def test_http_invalid_filters_and_unknown_action(self):
        row=self.open();c=self.client_for(self.manager)
        for query in ('?state=bad','?due=bad','?asset=-1','?owner=bad'):self.assertEqual(c.get(reverse('maintenance_list')+query).status_code,400)
        self.assertEqual(c.get(reverse('maintenance_action',args=[row.pk,'INVALID'])).status_code,404)
    def test_http_paginated_worklist_and_bounded_queries(self):
        self.open()
        for i in range(20):
            a=self.change(self.asset(asset_code=f'MORE-{i}'),kind='MAINTENANCE');self.open(asset_id=a.pk)
        c=self.client_for(self.manager)
        with CaptureQueriesContext(connection) as captured:response=c.get(reverse('maintenance_list'))
        self.assertEqual(len(response.context['rows']),20)
        with CaptureQueriesContext(connection) as single:
            last=c.get(reverse('maintenance_list')+'?page=2')
        self.assertEqual(len(last.context['rows']),1)
        # Authentication and workspace checks have fixed query overhead. A full
        # page must cost exactly the same number of queries as the one-row page;
        # per-row owner authorization would add nineteen queries here.
        self.assertEqual(len(captured),len(single))

    def test_sql_submission_cannot_omit_named_submitter(self):
        # SQL CHECK treats NULL as unknown, so equality to the owner alone is
        # insufficient even when the application always supplies a submitter.
        row=self.act(self.open(),'START')
        with self.assertRaises(IntegrityError),transaction.atomic():
            MaintenanceOrder.objects.filter(pk=row.pk).update(state='READY',
                performed_on=self.today,cost=D('20.01'),completion_note='合成提交事实',
                schedule_checked=True,submitted_by_id=None,submitted_at=timezone.now(),
                lock_version=row.lock_version+1)
            row.refresh_from_db()
            MaintenanceAction.objects.create(order=row,operation_id=uuid4(),
                sequence=row.lock_version,action='SUBMIT',actor=self.manager,
                note='合成缺少提交人的 SQL 拒绝验证',snapshot=snapshot(row))
