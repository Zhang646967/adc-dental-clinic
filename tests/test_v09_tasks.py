"""Genuine PostgreSQL/HTTP task tests; authored separately from pure checks.
No mocked ORM or SQLite substitutes. Not executed in the generation environment.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from importlib import import_module
from threading import Event
from time import monotonic,sleep
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from django.apps import apps
from django.core.exceptions import PermissionDenied
from django.db import connection,transaction,IntegrityError,close_old_connections,DatabaseError
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase,override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from adc_core.rules import RuleError
from care.models import AuditEvent
from coordination.models import CoordinationTask,WaitRequest,WaitOffer,SchedulePlan
from coordination.task_rules import ACTION_REASONS
from coordination.task_services import inspect_task,prepare_task,confirm_task,list_tasks
from coordination.services import publish_plan,answer_offer
from scheduling.models import AvailabilitySlot,Visit
from scheduling.services import change_appointment
from scheduling.intake_services import inspect_intake,prepare_intake,confirm_intake
from workspaces.models import WorkspaceContext
from tests.fixtures import FixtureMixin
from tests.workspace_client import WorkspaceClient

class TaskWorkflowTests(FixtureMixin,TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor,'postgresql');self.make_fixture()
        for user,role in ((self.manager,'MANAGER'),(self.front,'FRONT_DESK'),(self.front2,'FRONT_DESK'),(self.tech,'SYSADMIN')):
            user._adc_workspace=WorkspaceContext.objects.create(user=user,role=role,clinic=None if role=='SYSADMIN' else self.a,revision=1)
        self.manager2=UserAccount.objects.create_user(username='task_manager_2',password='test-only-pass-123')
        RoleAssignment.objects.create(user=self.manager2,role='MANAGER',scope_kind='CLINIC',clinic=self.a)
        self.manager2._adc_workspace=WorkspaceContext.objects.create(user=self.manager2,role='MANAGER',clinic=self.a,revision=1)
    def intake(self,action,actor=None):
        actor=actor or self.manager
        _,s=inspect_intake(actor=actor,slot_id=self.slot1.pk)
        p=prepare_intake(actor=actor,slot_id=self.slot1.pk,state_token=s,action=action,reason='COORDINATION' if action=='pause' else 'READY_TO_REOPEN')
        return confirm_intake(actor=actor,slot_id=self.slot1.pk,proposal_token=p['proposal_token'],confirmed=True)
    def pause_fixture(self):
        # Baseline data setup, not evidence that the intake UI works.
        self.slot1.booking_paused=True;self.slot1.intake_revision+=1
        self.slot1.save(update_fields=['booking_paused','intake_revision'])
    def preview(self,actor,action,t=None,**kw):
        data,s=inspect_task(actor=actor,slot_id=self.slot1.pk,task_id=t.pk if t else None)
        args=dict(reason=ACTION_REASONS[action][0],purpose='REPLACE' if action=='open' else '')
        args.update(kw)
        return prepare_task(actor=actor,slot_id=self.slot1.pk,task_id=t.pk if t else None,state_token=s,action=action,**args)
    def commit(self,actor,p):
        return confirm_task(actor=actor,slot_id=p['slot_id'],task_id=p['task_id'],proposal_token=p['proposal_token'],confirmed=True)
    def command(self,actor,action,t=None,**kw):
        r=self.commit(actor,self.preview(actor,action,t,**kw));return CoordinationTask.objects.get(pk=r.task_id)
    def opened(self):
        self.pause_fixture();return self.command(self.manager,'open')
    def working(self):return self.command(self.front,'claim',self.opened())
    def ready(self):return self.command(self.front,'submit',self.working())
    def add_offer(self):
        req=WaitRequest.objects.create(patient=self.p1,clinic=self.a,earliest=self.t,latest=self.t+timedelta(hours=4),created_by=self.front)
        plan=SchedulePlan.objects.create(clinic=self.a,created_by=self.manager,
            suggestions=[dict(request_id=req.pk,request_revision=0,slot_id=self.slot1.pk,
                start=self.t.isoformat(),end=(self.t+timedelta(minutes=30)).isoformat(),intake_revision=0)])
        publish_plan(actor=self.manager,plan_id=plan.pk)
        return WaitOffer.objects.get(plan=plan)
    def test_open_preview_has_no_writes(self):
        self.pause_fixture();before=AuditEvent.objects.count();p=self.preview(self.manager,'open')
        self.assertEqual(CoordinationTask.objects.count(),0);self.assertEqual(AuditEvent.objects.count(),before);self.assertEqual(p['after'],'待前台受理')
    def test_open_requires_explicit_pause(self):
        with self.assertRaises(RuleError):self.preview(self.manager,'open')
    def test_open_does_not_modify_slot(self):
        self.pause_fixture();before=AvailabilitySlot.objects.values().get(pk=self.slot1.pk)
        self.command(self.manager,'open');self.assertEqual(before,AvailabilitySlot.objects.values().get(pk=self.slot1.pk))
    def test_open_with_booking_does_not_cancel_it(self):
        v=self.book();t=self.opened();v.refresh_from_db();self.assertEqual(v.status,'SCHEDULED');self.assertEqual(t.state,'OPEN')
    def test_task_does_not_invalidate_existing_offer(self):
        o=self.add_offer();t=self.opened();answer_offer(actor=self.front,offer_id=o.pk,accept=True)
        o.refresh_from_db();self.assertEqual(o.state,'ACCEPTED');t.refresh_from_db();self.assertEqual(t.state,'OPEN')
    def test_only_one_active_task(self):
        self.opened()
        with self.assertRaises(RuleError):self.preview(self.manager2,'open')
        self.assertEqual(CoordinationTask.objects.count(),1)
    def test_duplicate_open_same_operation_returns_original(self):
        self.pause_fixture();p=self.preview(self.manager,'open');a=self.commit(self.manager,p);b=self.commit(self.manager,p)
        self.assertEqual(a.task_id,b.task_id);self.assertTrue(b.repeated);self.assertEqual(AuditEvent.objects.filter(event_type='TASK_CREATED').count(),1)
    def test_new_task_after_cancelled(self):
        old=self.command(self.manager,'cancel',self.opened());new=self.command(self.manager2,'open')
        self.assertNotEqual(old.pk,new.pk)
    def test_replay_old_creation_does_not_reopen(self):
        self.pause_fixture();p=self.preview(self.manager,'open');r=self.commit(self.manager,p);t=CoordinationTask.objects.get(pk=r.task_id)
        self.command(self.manager,'cancel',t);self.command(self.manager2,'open')
        replay=self.commit(self.manager,p);self.assertEqual(replay.state,'CANCELLED');self.assertEqual(CoordinationTask.objects.count(),2)
    def test_front_claim_assigns_self_only(self):
        t=self.working();self.assertEqual(t.assignee_id,self.front.pk);self.assertEqual(t.state,'IN_PROGRESS')
    def test_other_front_claim_after_first_rejected(self):
        t=self.working()
        with self.assertRaises(RuleError):self.preview(self.front2,'claim',t)
    def test_manager_cannot_claim(self):
        t=self.opened()
        with self.assertRaises(RuleError):self.preview(self.manager,'claim',t)
    def test_front_cannot_create(self):
        self.pause_fixture()
        with self.assertRaises(RuleError):self.preview(self.front,'open')
    def test_other_front_cannot_report(self):
        t=self.working()
        with self.assertRaises(RuleError):self.preview(self.front2,'progress',t,reason='NEED_HELP')
    def test_recording_statement_does_not_change_visit(self):
        v=self.book();t=self.working();before=Visit.objects.values().get(pk=v.pk)
        t=self.command(self.front,'progress',t,reason='USED_ORIGINAL',target_kind='visit',target_id=v.pk)
        self.assertEqual(before,Visit.objects.values().get(pk=v.pk));self.assertEqual(t.state,'IN_PROGRESS')
        with self.assertRaises(RuleError):self.preview(self.front,'submit',t)
    def test_statement_rejects_foreign_target(self):
        other=Visit.objects.create(patient=self.p2,dentist=self.d2,clinic=self.b,availability_slot=self.slot2,scheduled_start=self.t,scheduled_end=self.t+timedelta(minutes=30))
        t=self.working()
        with self.assertRaises(RuleError):self.preview(self.front,'progress',t,reason='NO_RESPONSE',target_kind='visit',target_id=other.pk)
    def test_help_does_not_require_patient_identity(self):
        t=self.command(self.front,'progress',self.working(),reason='NEED_HELP')
        event=AuditEvent.objects.filter(subject_key=str(t.pk),event_type='TASK_REPORTED').get()
        self.assertTrue(event.change_summary['statement_only']);self.assertIsNone(event.change_summary['target_id'])
    def test_declaration_no_raw_contact_in_audit(self):
        v=self.book();self.p1.phone='13800001111';self.p1.save(update_fields=['phone'])
        self.command(self.front,'progress',self.working(),reason='NO_RESPONSE',target_kind='visit',target_id=v.pk)
        rows=str(list(AuditEvent.objects.filter(subject_type='coordinationtask').values('reason','change_summary')))
        self.assertNotIn(self.p1.phone,rows);self.assertNotIn(self.p1.name,rows)
    def test_owner_can_release_and_other_can_claim(self):
        t=self.command(self.front,'release',self.working());self.assertIsNone(t.assignee_id)
        t=self.command(self.front2,'claim',t);self.assertEqual(t.assignee_id,self.front2.pk)
    def test_manager_can_requeue_disabled_assignee(self):
        t=self.working();UserAccount.objects.filter(pk=self.front.pk).update(is_active=False)
        t=self.command(self.manager,'return',t,reason='OWNER_UNAVAILABLE')
        self.assertEqual(t.state,'OPEN');self.assertIsNone(t.assignee_id)
        t=self.command(self.front2,'claim',t);self.assertEqual(t.assignee_id,self.front2.pk)
    def test_disabled_assignee_cannot_continue(self):
        t=self.working();UserAccount.objects.filter(pk=self.front.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.preview(self.front,'progress',t,reason='NEED_HELP')
    def test_submit_requires_no_booking(self):
        self.book();t=self.working()
        with self.assertRaises(RuleError):self.preview(self.front,'submit',t)
    def test_submit_requires_no_effective_offer(self):
        self.add_offer();t=self.working()
        with self.assertRaises(RuleError):self.preview(self.front,'submit',t)
    def test_expired_offer_no_longer_blocks_submission(self):
        o=self.add_offer();t=self.working();WaitOffer.objects.filter(pk=o.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        t=self.command(self.front,'submit',t);self.assertEqual(t.state,'READY')
        o.refresh_from_db();self.assertEqual(o.state,'PENDING') # No implicit recycling.
    def test_submit_after_original_cancellation(self):
        v=self.book();t=self.working()
        change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='cancel',reason='合成协调取消',party='PATIENT')
        t=self.command(self.front,'submit',t);self.assertEqual(t.state,'READY')
    def test_checked_in_cannot_be_cleared_by_task(self):
        v=self.book();change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='check_in')
        t=self.working()
        with self.assertRaises(RuleError):self.preview(self.front,'submit',t)
        v.refresh_from_db();self.assertEqual(v.status,'CHECKED_IN')
    def test_submit_requires_still_paused(self):
        t=self.working();AvailabilitySlot.objects.filter(pk=self.slot1.pk).update(booking_paused=False,intake_revision=2)
        with self.assertRaises(RuleError):self.preview(self.front,'submit',t)
    def test_submit_started_denied(self):
        t=self.working()
        with patch('coordination.task_services.timezone.now',return_value=self.t):
            with self.assertRaises(RuleError):self.preview(self.front,'submit',t)
    def test_approve_does_not_maintain_or_resume(self):
        t=self.ready();before=AvailabilitySlot.objects.values().get(pk=self.slot1.pk)
        t=self.command(self.manager,'approve',t)
        self.assertEqual(t.state,'CLOSED');self.assertEqual(before,AvailabilitySlot.objects.values().get(pk=self.slot1.pk));self.assertEqual(Visit.objects.count(),0)
    def test_same_account_crossrole_cannot_selfreview(self):
        self.pause_fixture();mctx=self.manager._adc_workspace;t=self.command(self.manager,'open')
        RoleAssignment.objects.create(user=self.manager,role='FRONT_DESK',scope_kind='CLINIC',clinic=self.a)
        self.manager._adc_workspace=WorkspaceContext.objects.create(user=self.manager,role='FRONT_DESK',clinic=self.a,revision=1)
        t=self.command(self.manager,'claim',t);t=self.command(self.manager,'submit',t)
        self.manager._adc_workspace=mctx
        with self.assertRaisesRegex(RuleError,'不能切换身份'):self.preview(self.manager,'approve',t)
    def test_resume_pause_cycle_invalidates_ready(self):
        t=self.ready();AvailabilitySlot.objects.filter(pk=self.slot1.pk).update(intake_revision=5)
        with self.assertRaisesRegex(RuleError,'变化'):self.preview(self.manager,'approve',t)
    def test_return_requires_another_submission(self):
        t=self.command(self.manager,'return',self.ready());self.assertEqual(t.submitted_digest,'')
        with self.assertRaises(RuleError):self.preview(self.manager,'approve',t)
        t=self.command(self.front2,'claim',t);t=self.command(self.front2,'submit',t)
        t=self.command(self.manager,'approve',t);self.assertEqual(t.state,'CLOSED')
    def test_cancel_preserves_pending_promises_and_pause(self):
        v=self.book();t=self.command(self.manager,'cancel',self.working())
        self.slot1.refresh_from_db();v.refresh_from_db()
        self.assertEqual(t.state,'CANCELLED');self.assertTrue(self.slot1.booking_paused);self.assertEqual(v.status,'SCHEDULED')
    def test_cancel_ready_clears_current_submission_keeps_audit(self):
        t=self.command(self.manager,'cancel',self.ready())
        self.assertIsNone(t.submitted_by_id);self.assertTrue(AuditEvent.objects.filter(event_type='TASK_SUBMITTED',subject_key=str(t.pk)).exists())
    def test_stale_task_revision_rejected(self):
        t=self.working();p=self.preview(self.front,'progress',t,reason='NEED_HELP')
        self.command(self.manager,'return',t)
        with self.assertRaises(RuleError):self.commit(self.front,p)
    def test_stale_confirm_does_not_revive_after_state_cycle(self):
        t=self.opened();p=self.preview(self.front,'claim',t)
        t=self.command(self.front2,'claim',t);t=self.command(self.front2,'release',t)
        with self.assertRaises(RuleError):self.commit(self.front,p)
    def test_expired_signature_rejected(self):
        t=self.opened();p=self.preview(self.front,'claim',t)
        with patch('django.core.signing.time.time',return_value=timezone.now().timestamp()+1000):
            with self.assertRaises(RuleError):self.commit(self.front,p)
    def test_tampered_signature_rejected(self):
        t=self.opened();p=self.preview(self.front,'claim',t);p['proposal_token']+='x'
        with self.assertRaises(RuleError):self.commit(self.front,p)
    def test_context_change_rejected(self):
        t=self.opened();p=self.preview(self.front,'claim',t)
        WorkspaceContext.objects.filter(pk=self.front._adc_workspace.pk).update(revision=2)
        with self.assertRaises(PermissionDenied):self.commit(self.front,p)
    def test_current_role_not_assigned_role(self):
        t=self.opened();self.tech._adc_workspace=WorkspaceContext.objects.create(user=self.tech,role='SYSADMIN',revision=1)
        RoleAssignment.objects.create(user=self.tech,role='MANAGER',scope_kind='CLINIC',clinic=self.a)
        with self.assertRaises(PermissionDenied):inspect_task(actor=self.tech,slot_id=self.slot1.pk,task_id=t.pk)
    def test_foreign_slot_rejected_before_projection(self):
        with self.assertRaises(PermissionDenied):inspect_task(actor=self.manager,slot_id=self.slot2.pk)
    def test_wrong_task_slot_pair_rejected(self):
        t=self.opened()
        with self.assertRaises(PermissionDenied):inspect_task(actor=self.front,slot_id=self.slot2.pk,task_id=t.pk)
    def test_other_actor_cannot_use_confirmation(self):
        t=self.opened();p=self.preview(self.front,'claim',t)
        with self.assertRaises(PermissionDenied):self.commit(self.front2,p)
    def test_readonly_service_rejects(self):
        t=self.opened();p=self.preview(self.front,'claim',t)
        with override_settings(ADC_READ_ONLY=True):
            with self.assertRaises(PermissionDenied):self.commit(self.front,p)
    def test_confirmation_required(self):
        t=self.opened();p=self.preview(self.front,'claim',t)
        with self.assertRaises(RuleError):confirm_task(actor=self.front,slot_id=self.slot1.pk,task_id=t.pk,proposal_token=p['proposal_token'],confirmed=False)
    def test_open_audit_failure_rolls_back(self):
        self.pause_fixture();p=self.preview(self.manager,'open')
        with patch('coordination.task_services.emit',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):self.commit(self.manager,p)
        self.assertEqual(CoordinationTask.objects.count(),0)
    def test_transition_audit_failure_rolls_back(self):
        t=self.opened();p=self.preview(self.front,'claim',t)
        with patch('coordination.task_services.emit',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):self.commit(self.front,p)
        t.refresh_from_db();self.assertEqual(t.state,'OPEN');self.assertEqual(t.revision,0)
    def test_terminal_row_immutable_in_db(self):
        t=self.command(self.manager,'cancel',self.opened())
        with self.assertRaises(IntegrityError),transaction.atomic():CoordinationTask.objects.filter(pk=t.pk).update(revision=t.revision+1)
    def test_history_not_deleted_by_db_dml(self):
        t=self.opened()
        with self.assertRaises(IntegrityError),transaction.atomic():CoordinationTask.objects.filter(pk=t.pk).delete()
    def test_task_identity_immutable_in_db(self):
        t=self.opened()
        with self.assertRaises(IntegrityError),transaction.atomic():CoordinationTask.objects.filter(pk=t.pk).update(purpose='DEACTIVATE',revision=1)
    def test_unique_active_constraint_in_db(self):
        self.opened()
        with self.assertRaises(IntegrityError),transaction.atomic():
            CoordinationTask.objects.create(slot=self.slot1,purpose='REPLACE',opening_reason='PLAN_CHANGE',creation_operation=uuid4(),created_by=self.manager)
    def test_selfreview_constraint_in_db(self):
        t=self.ready()
        with self.assertRaises(IntegrityError),transaction.atomic():
            CoordinationTask.objects.filter(pk=t.pk).update(state='CLOSED',closed_by_id=self.front.pk,closed_at=timezone.now(),revision=t.revision+1)
    def test_schema_reverse_refuses_used_tasks(self):
        self.opened();m=import_module('coordination.migrations.0002_coordination_tasks')
        with self.assertRaises(RuntimeError):m.guard_reverse(apps,SimpleNamespace(connection=connection))
    def test_additive_empty_migration_preserves_slot_and_pause(self):
        self.pause_fixture();before=AvailabilitySlot.objects.values().get(pk=self.slot1.pk)
        executor=MigrationExecutor(connection);final_targets=executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([('coordination','0001_initial')])
        finally:MigrationExecutor(connection).migrate(final_targets)
        self.assertEqual(before,AvailabilitySlot.objects.values().get(pk=self.slot1.pk));self.assertEqual(CoordinationTask.objects.count(),0)
    def test_projection_manager_hides_target_ids_and_patient(self):
        v=self.book();t=self.command(self.front,'progress',self.working(),reason='NO_RESPONSE',target_kind='visit',target_id=v.pk)
        data,_=inspect_task(actor=self.manager,slot_id=self.slot1.pk,task_id=t.pk)
        self.assertTrue(data['history']);self.assertFalse(any('target' in e for e in data['history']))
        self.assertNotIn(self.p1.patient_no,str(data));self.assertNotIn(self.p1.name,str(data))
    def test_list_scope_and_mine(self):
        t=self.working();a=list_tasks(actor=self.front,mode='mine');b=list_tasks(actor=self.front2,mode='mine')
        self.assertEqual(a['total'],1);self.assertEqual(b['total'],0)
    def test_http_detail_does_not_write(self):
        t=self.opened();c=WorkspaceClient();c.force_login(self.front)
        before=AuditEvent.objects.count();r=c.get(reverse('coordination_task_detail',args=[self.slot1.pk,t.pk]))
        self.assertEqual(r.status_code,200);self.assertContains(r,'任务状态不是当前预约状态');self.assertEqual(before,AuditEvent.objects.count())
    def test_http_preview_confirm_flow(self):
        self.pause_fixture();c=WorkspaceClient();c.force_login(self.manager)
        url=reverse('coordination_task_open',args=[self.slot1.pk]);r=c.get(url);self.assertEqual(r.status_code,200)
        token=r.context['form'].initial['state_token']
        p=c.post(url,dict(state_token=token,purpose='REPLACE',reason='PLAN_CHANGE'))
        self.assertEqual(p.status_code,200);self.assertContains(p,'尚未保存');self.assertEqual(CoordinationTask.objects.count(),0)
        r=c.post(reverse('coordination_task_confirm_new',args=[self.slot1.pk]),dict(proposal_token=p.context['preview']['proposal_token'],confirmed='on'))
        self.assertEqual(r.status_code,302);self.assertEqual(CoordinationTask.objects.count(),1)
    def test_http_confirmation_get_rejected(self):
        c=WorkspaceClient();c.force_login(self.manager)
        self.assertEqual(c.get(reverse('coordination_task_confirm_new',args=[self.slot1.pk])).status_code,405)
    def test_http_csrf_still_required(self):
        c=WorkspaceClient(enforce_csrf_checks=True);c.force_login(self.manager)
        r=c.post(reverse('coordination_task_confirm_new',args=[self.slot1.pk]),dict(proposal_token='bad',confirmed='on'))
        self.assertEqual(r.status_code,403)
    def test_http_readonly_post_rejected(self):
        c=WorkspaceClient();c.force_login(self.manager)
        with override_settings(ADC_READ_ONLY=True):
            self.assertIn(c.post(reverse('coordination_task_open',args=[self.slot1.pk]),{}).status_code,(403,409))
    def test_http_foreign_role_rejected(self):
        c=WorkspaceClient();c.force_login(self.tech)
        self.assertEqual(c.get(reverse('coordination_task_list')).status_code,403)
    def test_http_query_error_unknown_not_empty(self):
        t=self.opened();c=WorkspaceClient();c.force_login(self.front)
        with patch('coordination.task_views.inspect_task',side_effect=DatabaseError('not exposed')):
            r=c.get(reverse('coordination_task_detail',args=[self.slot1.pk,t.pk]))
        self.assertEqual(r.status_code,503);self.assertContains(r,'结果未知',status_code=503);self.assertNotContains(r,'not exposed',status_code=503)
    def test_confirm_repeat_after_owner_release_no_undo(self):
        t=self.opened();p=self.preview(self.front,'claim',t);r=self.commit(self.front,p);t.refresh_from_db()
        self.command(self.front,'release',t);repeat=self.commit(self.front,p)
        self.assertTrue(repeat.repeated);self.assertEqual(repeat.state,'OPEN')

class TaskConcurrencyTests(FixtureMixin,TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor,'postgresql');self.make_fixture()
        self.other=UserAccount.objects.create_user(username='task_other_mgr',password='test-only-pass-abc')
        RoleAssignment.objects.create(user=self.other,role='MANAGER',scope_kind='CLINIC',clinic=self.a)
        for a,r in ((self.manager,'MANAGER'),(self.other,'MANAGER'),(self.front,'FRONT_DESK'),(self.front2,'FRONT_DESK')):
            a._adc_workspace=WorkspaceContext.objects.create(user=a,role=r,clinic=self.a,revision=1)
        self.slot1.booking_paused=True;self.slot1.save(update_fields=['booking_paused'])
    def prep(self,a,action,t=None):
        _,s=inspect_task(actor=a,slot_id=self.slot1.pk,task_id=t.pk if t else None)
        return prepare_task(actor=a,slot_id=self.slot1.pk,task_id=t.pk if t else None,state_token=s,
            action=action,reason=ACTION_REASONS[action][0],purpose='REPLACE' if action=='open' else '')
    def wait_for_lock(self,name):
        end=monotonic()+8
        while monotonic()<end:
            with connection.cursor() as cur:
                cur.execute('SELECT wait_event_type FROM pg_stat_activity WHERE application_name=%s',[name])
                if any(r[0]=='Lock' for r in cur.fetchall()):return
            sleep(.03)
        self.fail('Second real connection did not reach the shared slot lock')
    def race(self,kind):
        from coordination import task_services
        task=None;a,b=self.manager,self.other
        if kind=='claim':
            p=self.prep(self.manager,'open');r=confirm_task(actor=self.manager,slot_id=self.slot1.pk,task_id=None,proposal_token=p['proposal_token'],confirmed=True)
            task=CoordinationTask.objects.get(pk=r.task_id);a,b=self.front,self.front2
        action='claim' if kind=='claim' else 'open'
        pa,pb=self.prep(a,action,task),self.prep(b,action,task)
        locked,release=Event(),Event();original=task_services._transition
        def hold(t,obs,**kwargs):
            if kwargs['actor'].pk==a.pk:
                locked.set()
                if not release.wait(12):raise RuntimeError('test timeout')
            return original(t,obs,**kwargs)
        app='adc_task_race_'+kind
        def worker(account,p,second):
            close_old_connections()
            try:
                if second:
                    with connection.cursor() as cur:cur.execute("SELECT set_config('application_name',%s,false)",[app])
                actor=UserAccount.objects.get(pk=account.pk);actor._adc_workspace=WorkspaceContext.objects.get(pk=account._adc_workspace.pk)
                try:return confirm_task(actor=actor,slot_id=self.slot1.pk,task_id=p['task_id'],proposal_token=p['proposal_token'],confirmed=True)
                except RuleError:return 'rejected'
            finally:connection.close()
        with patch('coordination.task_services._transition',side_effect=hold),ThreadPoolExecutor(max_workers=2) as pool:
            f=pool.submit(worker,a,pa,False)
            try:
                self.assertTrue(locked.wait(8));g=pool.submit(worker,b,pb,True);self.wait_for_lock(app)
            finally:release.set()
            first=f.result(timeout=12);second=g.result(timeout=12)
        self.assertNotEqual(first,'rejected');self.assertEqual(second,'rejected')
        self.assertEqual(CoordinationTask.objects.count(),1)
        if kind=='claim':self.assertEqual(CoordinationTask.objects.get().assignee_id,a.pk)
    def test_two_managers_only_one_active_task(self):self.race('open')
    def test_two_front_desks_only_one_assignee(self):self.race('claim')
