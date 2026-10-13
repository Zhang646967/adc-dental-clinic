"""Pure notice policies and source contracts; these are not ORM/queue tests."""
import ast
from datetime import datetime, timezone, timedelta
from pathlib import Path
import unittest
from notifications.rules import (ACTIONS, NOTICE_BOUNDARY, MAX_RECIPIENTS, MAX_ATTEMPTS,
    recipient_snapshot, validate_event, retry_time, bounded_batch, validate_retry, title, positive_int)

ROOT=Path(__file__).resolve().parents[1]

class NotificationRulesTests(unittest.TestCase):
    def target(self,**kw): return dict(user_id=1,grant_id=2,role='FRONT_DESK')|kw
    def data(self,**kw): return dict(action='open',event_state='OPEN',task_id=1,clinic_id=2,task_revision=0,recipients=[self.target()])|kw
    def test_valid_event(self): self.assertEqual(validate_event(**self.data()),[self.target()])
    def test_empty_targets_are_recordable(self): self.assertEqual(validate_event(**self.data(recipients=[])),[])
    def test_open_frontdesk(self): self.assertEqual(ACTIONS['open'][1],('FRONT_DESK',))
    def test_submit_manager(self): self.assertEqual(ACTIONS['submit'][1],('MANAGER',))
    def test_claim_manager(self): self.assertEqual(ACTIONS['claim'][1],('MANAGER',))
    def test_end_informs_both_roles(self): self.assertEqual(set(ACTIONS['approve'][1]),{'MANAGER','FRONT_DESK'})
    def test_progress_is_statement(self): self.assertIn('声明',title('progress'))
    def test_notice_is_not_business_completion(self): self.assertIn('不等于',NOTICE_BOUNDARY)
    def test_no_raw_personal_keys(self):
        with self.assertRaises(ValueError): recipient_snapshot([self.target(phone='000')])
    def test_no_arbitrary_url(self):
        with self.assertRaises(ValueError): recipient_snapshot([self.target(url='https://example.invalid')])
    def test_no_unknown_roles(self):
        with self.assertRaises(ValueError): recipient_snapshot([self.target(role='SYSADMIN')])
    def test_no_role_fanout_for_dentist(self): self.assertNotIn('DENTIST',sum((v[1] for v in ACTIONS.values()),()))
    def test_duplicate_grant_rejected(self):
        with self.assertRaises(ValueError): recipient_snapshot([self.target(),self.target()])
    def test_bool_id_rejected(self):
        with self.assertRaises(ValueError): recipient_snapshot([self.target(grant_id=True)])
    def test_string_id_rejected(self):
        with self.assertRaises(ValueError): recipient_snapshot([self.target(user_id='1')])
    def test_zero_id_rejected(self):
        with self.assertRaises(ValueError): positive_int(0)
    def test_large_id_rejected(self):
        with self.assertRaises(ValueError): positive_int(2**63)
    def test_no_targets_truncation(self):
        with self.assertRaises(ValueError): recipient_snapshot([self.target(grant_id=i+1) for i in range(MAX_RECIPIENTS+1)])
    def test_target_limit_valid(self): self.assertEqual(len(recipient_snapshot([self.target(grant_id=i+1) for i in range(MAX_RECIPIENTS)])),MAX_RECIPIENTS)
    def test_sort_is_deterministic(self): self.assertEqual([r['grant_id'] for r in recipient_snapshot([self.target(grant_id=5),self.target(grant_id=3)])],[3,5])
    def test_unknown_action(self):
        with self.assertRaises(ValueError): validate_event(**self.data(action='accept_booking'))
    def test_unknown_state(self):
        with self.assertRaises(ValueError): validate_event(**self.data(event_state='PAID'))
    def test_action_state_mismatch(self):
        with self.assertRaises(ValueError): validate_event(**self.data(event_state='CLOSED'))
    def test_negative_revision(self):
        with self.assertRaises(ValueError): validate_event(**self.data(task_revision=-1))
    def test_restricted_audience(self):
        with self.assertRaises(ValueError): validate_event(**self.data(recipients=[self.target(role='MANAGER')]))
    def test_backoff_schedule(self):
        now=datetime(2031,1,1,tzinfo=timezone.utc)
        self.assertEqual([(retry_time(i,now)-now).total_seconds() for i in range(1,5)],[15,60,300,900])
    def test_final_attempt_stops(self): self.assertIsNone(retry_time(MAX_ATTEMPTS,datetime.now(timezone.utc)))
    def test_invalid_attempt(self):
        with self.assertRaises(ValueError): retry_time(0,datetime.now(timezone.utc))
    def test_no_naive_time(self):
        with self.assertRaises(ValueError): retry_time(1,datetime(2031,1,1))
    def test_batch_bound(self): self.assertEqual(bounded_batch(100),100)
    def test_batch_reject_bool(self):
        with self.assertRaises(ValueError): bounded_batch(True)
    def test_batch_reject_overflow(self):
        with self.assertRaises(ValueError): bounded_batch(101)
    def test_retry_failed_only(self): self.assertIsNone(validate_retry('FAILED',2,2))
    def test_retry_pending_rejected(self):
        with self.assertRaises(ValueError): validate_retry('PENDING',2,2)
    def test_retry_stale_round(self):
        with self.assertRaises(ValueError): validate_retry('FAILED',2,1)
    def test_retry_no_recipient_not_backfill(self):
        with self.assertRaises(ValueError): validate_retry('NO_RECIPIENTS',2,2)
    def test_invalid_title(self):
        with self.assertRaises(ValueError): title('<script>')

class NotificationSourceContracts(unittest.TestCase):
    def text(self,p): return (ROOT/p).read_text()
    def test_task_hook_follows_audit(self):
        s=self.text('coordination/task_services.py');a=s.index('    event=emit(actor,EVENT_TYPES[action]')
        self.assertLess(a,s.index('    enqueue_task_notice(task=task,event=event,action=action)'))
    def test_replay_precedes_hook(self):
        s=self.text('coordination/task_services.py');self.assertLess(s.index('previous.state,event.pk,True'),s.index('    enqueue_task_notice'))
    def test_hook_requires_atomic(self): self.assertIn('connection.in_atomic_block',self.text('notifications/enqueue.py'))
    def test_no_oncommit_for_durable_intent(self): self.assertNotIn('on_commit(',self.text('notifications/enqueue.py'))
    def test_snapshot_and_current_grants(self):
        self.assertIn('user__is_active=True',self.text('notifications/enqueue.py'));self.assertIn('user__is_active=True',self.text('notifications/dispatcher.py'))
    def test_worker_skip_locked(self): self.assertIn('select_for_update(skip_locked=True)',self.text('notifications/dispatcher.py'))
    def test_atomic_delivery_savepoint(self): self.assertGreaterEqual(self.text('notifications/dispatcher.py').count('with transaction.atomic()'),2)
    def test_no_processing_lease_state(self): self.assertNotIn("state='PROCESSING'",self.text('notifications/dispatcher.py'))
    def test_worker_readonly_guard(self): self.assertIn('settings.ADC_READ_ONLY',self.text('notifications/dispatcher.py'))
    def test_all_new_files_without_network_imports(self):
        for p in (ROOT/'notifications').rglob('*.py'):
            tree=ast.parse(p.read_text())
            for n in ast.walk(tree):
                if isinstance(n,ast.Import): self.assertFalse(any(x.name.split('.')[0] in {'requests','httpx','socket','smtplib','urllib'} for x in n.names))
    def test_no_business_commands_in_notifications(self):
        for name in ('dispatcher.py','services.py','enqueue.py'):
            s=self.text('notifications/'+name)
            for method in ('create_appointment(','change_appointment(','confirm_task(','answer_offer(','confirm_availability_change('): self.assertNotIn(method,s)
    def test_inbox_owner_and_scope(self):
        s=self.text('notifications/services.py');self.assertIn('recipient_id=actor.pk',s);self.assertIn('grant__is_active=True',s);self.assertIn('role=identity[1]',s)
    def test_get_has_no_ack(self):
        s=self.text('notifications/views.py');n=next(x for x in ast.parse(s).body if isinstance(x,ast.FunctionDef) and x.name=='inbox')
        self.assertNotIn('mark_read(',ast.get_source_segment(s,n))
    def test_ack_is_post_only(self):
        s=self.text('notifications/views.py');self.assertIn('@require_POST\ndef acknowledge',s)
    def test_first_read_timestamp_preserved(self): self.assertIn('if message.read_at is None:',self.text('notifications/services.py'))
    def test_retry_only_after_scope_check(self):
        s=self.text('notifications/services.py');self.assertIn("if identity[1]!='MANAGER'",s);self.assertIn('expected_round',s)
    def test_worker_whitelisted_errors(self):
        s=self.text('notifications/dispatcher.py');self.assertNotIn('str(exc)',s);self.assertNotIn('repr(exc)',s)
    def test_inbox_db_idempotency(self): self.assertIn("fields=['event','grant']",self.text('notifications/models.py'))
    def test_migration_identity_guards(self):
        s=self.text('notifications/migrations/0001_initial.py');self.assertIn('adc_inbox_ownership',s);self.assertIn('NEW.recipients',s);self.assertIn('prevent_destructive_reverse',s)
    def test_old_readonly_whitelist_unchanged(self):
        s=self.text('adc_core/read_only_policy.py');self.assertNotIn('notification_read',s);self.assertNotIn('notification_retry',s)
    def test_no_auto_worker_in_local_compose(self): self.assertNotIn('notification-worker',self.text('compose.yaml'))
    def test_worker_no_old_volume_or_external_port(self):
        s=self.text('compose.notifications.yaml');self.assertNotIn('ports:',s);self.assertNotIn('volumes:',s);self.assertIn('AI_MODE: disabled',s)
