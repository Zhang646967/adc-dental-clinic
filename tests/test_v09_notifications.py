"""PostgreSQL/HTTP notice tests. Authored here; execution status is in TEST_REPORT.
Actual models, transactions, middleware and row locks; no SQLite or fake ORM.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.db import transaction,connection,IntegrityError,DatabaseError,close_old_connections
from django.test import TransactionTestCase,override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from adc_core.rules import RuleError
from care.models import AuditEvent
from coordination.models import CoordinationTask
from coordination.task_services import inspect_task,prepare_task,confirm_task
from coordination.task_rules import ACTION_REASONS
from notifications.models import NotificationOutbox,InboxMessage
from notifications.dispatcher import dispatch_one,dispatch_batch,_deliver
from notifications.services import list_inbox,mark_read,delivery_status,retry_delivery
from notifications.enqueue import enqueue_task_notice
from tests.fixtures import FixtureMixin
from workspaces.models import WorkspaceContext
from workspaces.context import SESSION_KEY


class NotificationTests(FixtureMixin,TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor,'postgresql')
        self.make_fixture()
        for actor,role in ((self.front,'FRONT_DESK'),(self.front2,'FRONT_DESK'),(self.manager,'MANAGER'),(self.tech,'SYSADMIN')):
            actor._adc_workspace=WorkspaceContext.objects.create(user=actor,role=role,
                clinic=None if role=='SYSADMIN' else self.a,revision=1)
        self.slot1.booking_paused=True;self.slot1.intake_revision=1
        self.slot1.save(update_fields=['booking_paused','intake_revision'])
    def preview(self,actor,action,task=None):
        _,token=inspect_task(actor=actor,slot_id=self.slot1.pk,task_id=task.pk if task else None)
        return prepare_task(actor=actor,slot_id=self.slot1.pk,task_id=task.pk if task else None,state_token=token,
            action=action,reason=ACTION_REASONS[action][0],purpose='REPLACE' if action=='open' else '')
    def commit(self,actor,p):
        return confirm_task(actor=actor,slot_id=p['slot_id'],task_id=p['task_id'],proposal_token=p['proposal_token'],confirmed=True)
    def new_task(self):
        r=self.commit(self.manager,self.preview(self.manager,'open'))
        return CoordinationTask.objects.get(pk=r.task_id)
    def delivered(self):
        task=self.new_task();dispatch_one()
        return task,InboxMessage.objects.filter(recipient=self.front).get()
    def fail_delivery(self):
        task=self.new_task()
        with patch('notifications.dispatcher._deliver',side_effect=RuntimeError('never-store-secret-or-SQL')):
            for _ in range(5):
                NotificationOutbox.objects.filter(state='PENDING').update(next_attempt_at=timezone.now()-timedelta(seconds=1))
                dispatch_one()
        return NotificationOutbox.objects.get()
    def token(self): return self.client.cookies['csrftoken'].value

    def test_task_preview_no_event_or_message(self):
        self.preview(self.manager,'open')
        self.assertFalse(NotificationOutbox.objects.exists());self.assertFalse(InboxMessage.objects.exists())
    def test_task_commit_enqueues_but_no_message_yet(self):
        t=self.new_task();e=NotificationOutbox.objects.get()
        self.assertEqual((e.task_id,e.state,e.action),(t.pk,'PENDING','open'))
        self.assertFalse(InboxMessage.objects.exists())
    def test_source_audit_same_transition(self):
        t=self.new_task();e=NotificationOutbox.objects.get()
        self.assertEqual(e.source_event.subject_key,str(t.pk));self.assertEqual(e.source_event.event_type,'TASK_CREATED')
    def test_task_replay_does_not_enqueue_twice(self):
        p=self.preview(self.manager,'open');self.commit(self.manager,p);r=self.commit(self.manager,p)
        self.assertTrue(r.repeated);self.assertEqual(NotificationOutbox.objects.count(),1)
    def test_enqueue_failure_rolls_back_task_and_audit(self):
        p=self.preview(self.manager,'open');before=AuditEvent.objects.count()
        with patch('notifications.enqueue.NotificationOutbox.objects.create',side_effect=DatabaseError('synthetic')):
            with self.assertRaises(DatabaseError): self.commit(self.manager,p)
        self.assertFalse(CoordinationTask.objects.exists());self.assertEqual(AuditEvent.objects.count(),before)
    def test_outer_rollback_has_no_dispatchable_event(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic(): self.new_task();raise RuntimeError('abort')
        self.assertIsNone(dispatch_one());self.assertFalse(InboxMessage.objects.exists())
    def test_recipient_snapshot_is_minimal(self):
        self.new_task();e=NotificationOutbox.objects.get()
        self.assertEqual(len(e.recipients),2)
        for r in e.recipients: self.assertEqual(set(r),{'user_id','grant_id','role'})
    def test_claim_targets_managers(self):
        t=self.new_task();self.commit(self.front,self.preview(self.front,'claim',t))
        e=NotificationOutbox.objects.get(action='claim');self.assertEqual([r['user_id'] for r in e.recipients],[self.manager.pk])
    def test_dispatch_two_fronts(self):
        self.new_task();r=dispatch_one();self.assertEqual(r['delivered'],2)
        self.assertEqual(InboxMessage.objects.count(),2)
    def test_dispatch_does_not_mutate_task_or_patient(self):
        task=self.new_task();before=list(CoordinationTask.objects.values());patient=self.p1.phone
        dispatch_one();self.assertEqual(list(CoordinationTask.objects.values()),before);self.p1.refresh_from_db();self.assertEqual(self.p1.phone,patient)
    def test_worker_repeat_does_not_duplicate(self):
        self.delivered();self.assertIsNone(dispatch_one());self.assertEqual(InboxMessage.objects.count(),2)
    def test_insert_then_failure_rolls_all_messages_back(self):
        self.new_task()
        def crash(e,now): _deliver(e,now);raise RuntimeError('after inserts')
        with patch('notifications.dispatcher._deliver',side_effect=crash): r=dispatch_one()
        self.assertEqual(r['state'],'PENDING');self.assertFalse(InboxMessage.objects.exists())
    def test_failure_is_backed_off(self):
        self.new_task();before=timezone.now()
        with patch('notifications.dispatcher._deliver',side_effect=RuntimeError('synthetic')): dispatch_one()
        e=NotificationOutbox.objects.get();self.assertEqual(e.attempts,1);self.assertGreater(e.next_attempt_at,before+timedelta(seconds=14))
    def test_not_due_is_not_attempted(self):
        self.new_task();NotificationOutbox.objects.update(next_attempt_at=timezone.now()+timedelta(days=1))
        self.assertIsNone(dispatch_one());self.assertEqual(NotificationOutbox.objects.get().attempts,0)
    def test_failed_event_stops_after_five(self):
        e=self.fail_delivery();self.assertEqual((e.state,e.attempts),('FAILED',5));self.assertIsNone(dispatch_one())
    def test_exception_text_is_not_persisted(self):
        e=self.fail_delivery();self.assertEqual(e.error_code,'DELIVERY_ERROR');self.assertNotIn('secret',str(e.__dict__))
    def test_retry_only_notice_no_task_replay(self):
        e=self.fail_delivery();before=list(CoordinationTask.objects.values())
        retry_delivery(actor=self.manager,event_id=e.pk,expected_round=0,confirmed=True)
        self.assertEqual(list(CoordinationTask.objects.values()),before)
        e.refresh_from_db();self.assertEqual((e.state,e.attempts,e.retry_round),('PENDING',0,1))
        dispatch_one();self.assertEqual(InboxMessage.objects.count(),2)
    def test_retry_repeat_is_rejected_not_reset_again(self):
        e=self.fail_delivery();retry_delivery(actor=self.manager,event_id=e.pk,expected_round=0,confirmed=True)
        with self.assertRaises(RuleError): retry_delivery(actor=self.manager,event_id=e.pk,expected_round=0,confirmed=True)
    def test_retry_wrong_role(self):
        e=self.fail_delivery()
        with self.assertRaises(PermissionDenied): retry_delivery(actor=self.front,event_id=e.pk,expected_round=0,confirmed=True)
    def test_retry_without_confirmation(self):
        e=self.fail_delivery()
        with self.assertRaises(RuleError): retry_delivery(actor=self.manager,event_id=e.pk,expected_round=0,confirmed=False)
    def test_retry_audit_failure_rolls_back(self):
        e=self.fail_delivery()
        with patch('notifications.services.emit',side_effect=DatabaseError('synthetic')):
            with self.assertRaises(DatabaseError): retry_delivery(actor=self.manager,event_id=e.pk,expected_round=0,confirmed=True)
        e.refresh_from_db();self.assertEqual((e.state,e.retry_round),('FAILED',0))
    def test_no_initial_recipient_is_explicit(self):
        RoleAssignment.objects.filter(role='FRONT_DESK',clinic=self.a).update(is_active=False)
        self.new_task();r=dispatch_one();self.assertEqual(r['state'],'NO_RECIPIENTS')
    def test_new_grant_after_event_not_backfilled(self):
        self.new_task();late=UserAccount.objects.create_user('late_notice',password='synthetic-only')
        RoleAssignment.objects.create(user=late,role='FRONT_DESK',scope_kind='CLINIC',clinic=self.a)
        dispatch_one();self.assertFalse(InboxMessage.objects.filter(recipient=late).exists())
    def test_revoked_before_delivery_is_skipped(self):
        self.new_task();RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(is_active=False)
        r=dispatch_one();self.assertEqual((r['delivered'],r['suppressed']),(1,1))
    def test_disabled_before_delivery_is_skipped(self):
        self.new_task();UserAccount.objects.filter(pk=self.front.pk).update(is_active=False)
        self.assertEqual(dispatch_one()['delivered'],1)
    def test_inbox_does_not_mark_read(self):
        self.delivered();r=list_inbox(actor=self.front);self.assertEqual(r['unread'],1)
        self.assertFalse(InboxMessage.objects.filter(read_at__isnull=False).exists())
    def test_read_is_own_current_grant_only(self):
        _,m=self.delivered()
        with self.assertRaises(PermissionDenied): mark_read(actor=self.front2,message_id=m.pk)
    def test_read_is_idempotent(self):
        _,m=self.delivered();mark_read(actor=self.front,message_id=m.pk);m.refresh_from_db();first=m.read_at
        mark_read(actor=self.front,message_id=m.pk);m.refresh_from_db();self.assertEqual(m.read_at,first)
    def test_current_role_cannot_borrow_front_permission(self):
        self.delivered();RoleAssignment.objects.create(user=self.front,role='MANAGER',scope_kind='CLINIC',clinic=self.a)
        WorkspaceContext.objects.filter(pk=self.front._adc_workspace.pk).update(role='MANAGER',revision=2)
        self.front._adc_workspace.refresh_from_db();self.assertEqual(list_inbox(actor=self.front)['total'],0)
    def test_switch_clinic_hides_other_messages(self):
        self.delivered();WorkspaceContext.objects.filter(pk=self.front._adc_workspace.pk).update(clinic=self.b,revision=2)
        self.front._adc_workspace.refresh_from_db();self.assertEqual(list_inbox(actor=self.front)['total'],0)
    def test_revoked_after_delivery_hides_messages(self):
        _,m=self.delivered();RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(is_active=False)
        with self.assertRaises(PermissionDenied): list_inbox(actor=self.front)
        with self.assertRaises(PermissionDenied): mark_read(actor=self.front,message_id=m.pk)
    def test_historical_notice_does_not_claim_current_state(self):
        task,m=self.delivered();self.commit(self.front,self.preview(self.front,'claim',task))
        row=list_inbox(actor=self.front)['rows'][0]
        self.assertNotEqual(row['event_revision'],row['current_revision']);self.assertNotEqual(row['event_state'],row['current_state'])
    def test_status_has_no_recipient_names_or_patient(self):
        self.delivered();result=delivery_status(actor=self.manager)
        for k in ('test_front','患者姓名','recipients'): self.assertNotIn(k,str(result))
    def test_status_front_denied(self):
        with self.assertRaises(PermissionDenied): delivery_status(actor=self.front)
    @override_settings(ADC_READ_ONLY=True)
    def test_worker_readonly_denied(self):
        with self.assertRaises(PermissionDenied): dispatch_one()
    def test_readonly_keeps_reads_not_ack(self):
        _,m=self.delivered()
        with override_settings(ADC_READ_ONLY=True):
            self.assertEqual(list_inbox(actor=self.front)['total'],1)
            with self.assertRaises(PermissionDenied): mark_read(actor=self.front,message_id=m.pk)
    def test_unique_recipient_event_constraint(self):
        _,m=self.delivered()
        with self.assertRaises(IntegrityError):
            with transaction.atomic(): InboxMessage.objects.create(event=m.event,recipient=m.recipient,grant=m.grant,clinic=m.clinic,role=m.role)
    def test_recipient_rewrite_database_rejected(self):
        _,m=self.delivered()
        with self.assertRaises(IntegrityError):
            with transaction.atomic(): InboxMessage.objects.filter(pk=m.pk).update(recipient=self.front2)
    def test_read_timestamp_cannot_be_cleared(self):
        _,m=self.delivered();mark_read(actor=self.front,message_id=m.pk)
        with self.assertRaises(IntegrityError):
            with transaction.atomic(): InboxMessage.objects.filter(pk=m.pk).update(read_at=None)
    def test_event_snapshot_database_immutable(self):
        self.new_task()
        with self.assertRaises(IntegrityError):
            with transaction.atomic(): NotificationOutbox.objects.update(recipients=[])
    def test_terminal_delivery_cannot_requeue(self):
        self.delivered()
        with self.assertRaises(IntegrityError):
            with transaction.atomic(): NotificationOutbox.objects.update(state='PENDING',next_attempt_at=timezone.now(),completed_at=None)
    def test_inbox_get_real_template(self):
        self.delivered();self.client.force_login(self.front)
        r=self.client.get(reverse('notification_inbox'));self.assertContains(r,'站内消息');self.assertContains(r,'标记已读')
        self.assertFalse(InboxMessage.objects.filter(read_at__isnull=False).exists())
    def test_ack_get_not_allowed(self):
        _,m=self.delivered();self.client.force_login(self.front)
        self.assertEqual(self.client.get(reverse('notification_read',args=[m.pk])).status_code,405)
    def test_ack_http(self):
        _,m=self.delivered();self.client.force_login(self.front)
        r=self.client.post(reverse('notification_read',args=[m.pk]),{'csrfmiddlewaretoken':self.token()})
        self.assertEqual(r.status_code,302);m.refresh_from_db();self.assertIsNotNone(m.read_at)
    def test_wrong_actor_http(self):
        _,m=self.delivered();self.client.force_login(self.front2)
        r=self.client.post(reverse('notification_read',args=[m.pk]),{'csrfmiddlewaretoken':self.token()})
        self.assertEqual(r.status_code,403)
    def test_old_workspace_http(self):
        _,m=self.delivered();self.client.force_login(self.front);old=self.client.current_token()
        ctx=WorkspaceContext.objects.get(pk=self.client.session[SESSION_KEY]);ctx.revision+=1;ctx.save(update_fields=['revision'])
        r=self.client.post(reverse('notification_read',args=[m.pk]),{'workspace_token':old,'csrfmiddlewaretoken':self.token()})
        self.assertEqual(r.status_code,409)
    def test_csrf_missing_rejected(self):
        from tests.workspace_client import WorkspaceClient
        _,m=self.delivered();client=WorkspaceClient(enforce_csrf_checks=True);client.force_login(self.front)
        r=client.post(reverse('notification_read',args=[m.pk]),{})
        self.assertEqual(r.status_code,403);m.refresh_from_db();self.assertIsNone(m.read_at)
    def test_worker_future_event_ignored_in_current_batch(self):
        self.new_task();NotificationOutbox.objects.update(next_attempt_at=timezone.now()+timedelta(minutes=1))
        self.assertEqual(dispatch_batch(25),[])
    def test_retry_get_not_allowed(self):
        e=self.fail_delivery();self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse('notification_retry',args=[e.pk])).status_code,405)
    def test_readonly_http_no_write_forms(self):
        self.delivered();self.client.force_login(self.front)
        with override_settings(ADC_READ_ONLY=True):
            r=self.client.get(reverse('notification_inbox'));self.assertContains(r,'当前实例只读');self.assertNotContains(r,'>标记已读</button>')
    def test_new_migration_reverse_blocks_used_data(self):
        from importlib import import_module
        from django.apps import apps
        self.new_task()
        migration=import_module('notifications.migrations.0001_initial')
        with connection.schema_editor() as editor:
            with self.assertRaises(RuntimeError): migration.prevent_destructive_reverse(apps,editor)
    def test_skip_locked_allows_second_event(self):
        task=self.new_task();self.commit(self.front,self.preview(self.front,'claim',task))
        first=NotificationOutbox.objects.order_by('pk').first();held=Event();release=Event()
        def hold_first():
            close_old_connections()
            try:
                with transaction.atomic():
                    NotificationOutbox.objects.select_for_update().get(pk=first.pk);held.set()
                    if not release.wait(8): raise RuntimeError('lock timeout')
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as executor:
            f=executor.submit(hold_first)
            try:
                self.assertTrue(held.wait(5));r=dispatch_one();self.assertNotEqual(r['event_id'],first.pk)
            finally: release.set();f.result(timeout=10)
        first.refresh_from_db();self.assertEqual(first.state,'PENDING')
    def test_two_workers_do_not_duplicate(self):
        self.new_task()
        def run():
            close_old_connections()
            try: return dispatch_one()
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor: results=list(executor.map(lambda _:run(),range(2)))
        self.assertEqual(sum(r is not None for r in results),1);self.assertEqual(InboxMessage.objects.count(),2)
