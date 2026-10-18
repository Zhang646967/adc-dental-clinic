"""R2.2 real PostgreSQL/read-only observation and existing business boundaries."""
from datetime import timedelta
import io
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, DatabaseError
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from accounts.models import RoleAssignment
from adc_core.operations import clock, identity, advance, fresh_state, status
from adc_core.operations_sampling import database_sample, collect_sample
from adc_core.operations_store import PrivateStore
from coordination.models import CoordinationTask
from coordination.task_services import inspect_task, prepare_task, confirm_task
from coordination.task_rules import ACTION_REASONS
from notifications.dispatcher import dispatch_one, _deliver
from notifications.models import NotificationOutbox, InboxMessage
from notifications.services import delivery_status
from tests.fixtures import FixtureMixin
from workspaces.models import WorkspaceContext


class OperationsDatabaseTests(FixtureMixin, TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor,'postgresql')
        self.make_fixture()
        for actor,role in ((self.front,'FRONT_DESK'),(self.manager,'MANAGER')):
            actor._adc_workspace=WorkspaceContext.objects.create(user=actor,role=role,clinic=self.a,revision=1)
        self.slot1.booking_paused=True;self.slot1.intake_revision=1
        self.slot1.save(update_fields=['booking_paused','intake_revision'])
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.worker=Path(self.tmp.name)/'worker';self.monitor=Path(self.tmp.name)/'monitor'
        self.env=patch.dict(os.environ,{'ADC_OPERATIONS_INSTANCE':'adc_test_observation','ADC_SOURCE_COMMIT':'a'*40,
            'ADC_READ_ONLY':'0','ADC_WORKER_DIRECTORY':str(self.worker),'ADC_MONITOR_DIRECTORY':str(self.monitor)})
        self.env.start();self.addCleanup(self.env.stop)

    def event(self):
        _,token=inspect_task(actor=self.manager,slot_id=self.slot1.pk)
        p=prepare_task(actor=self.manager,slot_id=self.slot1.pk,task_id=None,state_token=token,action='open',
                       reason=ACTION_REASONS['open'][0],purpose='REPLACE')
        r=confirm_task(actor=self.manager,slot_id=p['slot_id'],task_id=p['task_id'],proposal_token=p['proposal_token'],confirmed=True)
        return NotificationOutbox.objects.get(task_id=r.task_id)

    def dispatch(self):
        call_command('dispatch_notifications',stdout=io.StringIO(),stderr=io.StringIO())

    def heartbeat(self):
        return PrivateStore(self.worker).read('heartbeat.json')

    def test_idle_has_current_db_success_without_any_delivery(self):
        self.dispatch();h=self.heartbeat()
        self.assertIsNotNone(h['last_success']);self.assertIsNone(h['last_delivery'])
        self.assertFalse(NotificationOutbox.objects.exists())

    def test_delivery_heartbeat_written_after_inbox_commit(self):
        self.event();self.dispatch();h=self.heartbeat()
        self.assertIsNotNone(h['last_delivery']);self.assertEqual(InboxMessage.objects.count(),2)
        self.assertEqual(NotificationOutbox.objects.get().state,'DELIVERED')

    def test_failed_heartbeat_sink_does_not_replay_or_undo_delivery(self):
        self.event()
        with patch('adc_core.operations.Heartbeat.write',side_effect=OSError('R22_PRIVATE_SINK')):
            self.dispatch()
        self.assertEqual(NotificationOutbox.objects.get().state,'DELIVERED')
        self.assertEqual(InboxMessage.objects.count(),2)

    def test_optional_heartbeat_lock_io_failure_does_not_block_delivery(self):
        self.event()
        with patch('adc_core.operations_store.PrivateStore.lock',side_effect=PermissionError('R22_PRIVATE_LOCK')):
            self.dispatch()
        self.assertEqual(NotificationOutbox.objects.get().state,'DELIVERED')
        self.assertEqual(InboxMessage.objects.count(),2)

    def test_database_loop_failure_never_claims_success(self):
        with patch('notifications.management.commands.dispatch_notifications.dispatch_batch',side_effect=DatabaseError('R22_PRIVATE_DB')):
            with self.assertRaises(CommandError):self.dispatch()
        h=self.heartbeat();self.assertEqual(h['phase'],'failed');self.assertIsNone(h['last_success'])

    def test_worker_readonly_guard_does_not_write_heartbeat(self):
        with override_settings(ADC_READ_ONLY=True):
            with self.assertRaises(CommandError):self.dispatch()
        self.assertFalse(self.worker.exists())

    def test_future_retry_is_pending_but_not_due(self):
        e=self.event();NotificationOutbox.objects.filter(pk=e.pk).update(next_attempt_at=timezone.now()+timedelta(hours=1))
        s=database_sample();self.assertEqual((s['pending'],s['due'],s['oldest_due_seconds']),(1,0,0))

    def test_due_age_uses_later_retry_not_original_event(self):
        now=timezone.now()
        with patch('django.utils.timezone.now',return_value=now-timedelta(hours=2)):e=self.event()
        NotificationOutbox.objects.filter(pk=e.pk).update(next_attempt_at=now-timedelta(seconds=125))
        s=database_sample();self.assertEqual(s['due'],1);self.assertGreaterEqual(s['oldest_due_seconds'],125)
        self.assertLess(s['oldest_due_seconds'],130)

    def test_future_occurred_date_clamps_age(self):
        now=timezone.now()
        with patch('django.utils.timezone.now',return_value=now+timedelta(hours=1)):self.event()
        self.assertEqual(database_sample()['oldest_due_seconds'],0)

    def test_terminal_delivery_not_counted_as_backlog(self):
        self.event();dispatch_one();s=database_sample()
        self.assertEqual((s['delivered'],s['due'],s['pending']),(1,0,0))

    def test_no_recipients_separate_from_failed_and_delivered(self):
        self.event();RoleAssignment.objects.filter(role='FRONT_DESK',clinic=self.a).update(is_active=False)
        dispatch_one();s=database_sample()
        self.assertEqual((s['no_recipients'],s['failed'],s['delivered'],s['due']),(1,0,0,0))

    def test_failed_terminal_remains_visible_without_automatic_retry(self):
        e=self.event();NotificationOutbox.objects.filter(pk=e.pk).update(state='FAILED',next_attempt_at=None,completed_at=timezone.now(),error_code='INVALID_EVENT')
        s=database_sample();self.assertEqual((s['failed'],s['due']),(1,0))
        self.assertEqual(NotificationOutbox.objects.get().state,'FAILED')

    def test_sampling_selects_only_aggregate_columns(self):
        self.event()
        with CaptureQueriesContext(connection) as captured:s=database_sample()
        sql=' '.join(row['sql'] for row in captured.captured_queries).lower()
        for field in ('recipients','task_id','clinic_id','source_event_id','change_summary'):
            self.assertNotIn(field,sql)
        self.assertIn('read only',sql);self.assertIn('statement_timeout',sql)

    def test_database_write_attempt_rejected_inside_observation(self):
        self.event();original=NotificationOutbox.objects.get().state
        with patch('adc_core.operations_sampling.NotificationOutbox.objects.values',side_effect=lambda *a:NotificationOutbox.objects.update(state='FAILED')):
            with self.assertRaises(DatabaseError):database_sample()
        self.assertEqual(NotificationOutbox.objects.get().state,original)

    def test_observation_settings_do_not_escape_transaction(self):
        with connection.cursor() as c:
            c.execute('SHOW statement_timeout');before=c.fetchone()
        database_sample()
        with connection.cursor() as c:
            c.execute('SHOW transaction_read_only');self.assertEqual(c.fetchone()[0],'off')
            c.execute('SHOW statement_timeout');self.assertEqual(c.fetchone(),before)

    def test_sampling_leaves_all_business_and_notice_rows_unchanged(self):
        self.event();before=list(NotificationOutbox.objects.values());tasks=list(CoordinationTask.objects.values())
        database_sample();database_sample()
        self.assertEqual(list(NotificationOutbox.objects.values()),before)
        self.assertEqual(list(CoordinationTask.objects.values()),tasks);self.assertFalse(InboxMessage.objects.exists())

    def test_observer_database_failure_reports_unknown_queue(self):
        PrivateStore(self.monitor)
        with patch('adc_core.operations_sampling.database_sample',side_effect=DatabaseError('R22_PRIVATE_DB')),patch('adc_core.operations_sampling.web_sample',return_value=False):
            s=collect_sample(identity(),self.worker,self.monitor)
        self.assertIsNone(s['database']);self.assertNotIn('R22_PRIVATE',json.dumps(s))

    def test_status_reader_does_not_need_database(self):
        PrivateStore(self.monitor)
        with patch('django.db.backends.base.base.BaseDatabaseWrapper.ensure_connection',side_effect=DatabaseError('offline')):
            out=io.StringIO()
            with self.assertRaises(SystemExit) as stopped:call_command('operations_status',stdout=out)
        self.assertEqual(stopped.exception.code,3);self.assertEqual(json.loads(out.getvalue())['state'],'UNKNOWN')

    def test_bad_checksum_is_unknown_and_not_echoed(self):
        PrivateStore(self.monitor);p=self.monitor/'monitor.json';p.write_text('R22_PRIVATE_CORRUPT');p.chmod(0o600)
        out=io.StringIO()
        with self.assertRaises(SystemExit):call_command('operations_status',stdout=out)
        self.assertNotIn('R22_PRIVATE',out.getvalue());self.assertEqual(json.loads(out.getvalue())['code'],3)

    def test_scoped_manager_view_separates_due_and_future(self):
        e=self.event();NotificationOutbox.objects.filter(pk=e.pk).update(next_attempt_at=timezone.now()+timedelta(hours=1))
        view=delivery_status(actor=self.manager)
        self.assertEqual((view['pending'],view['due'],view['scheduled_retry'],view['oldest']),(1,0,1,''))

    def test_manager_due_age_uses_effective_due_time(self):
        now=timezone.now()
        with patch('django.utils.timezone.now',return_value=now-timedelta(days=1)):e=self.event()
        NotificationOutbox.objects.filter(pk=e.pk).update(next_attempt_at=now-timedelta(seconds=125))
        view=delivery_status(actor=self.manager)
        self.assertGreaterEqual(view['oldest_due_seconds'],125);self.assertLess(view['oldest_due_seconds'],130)

    def test_manager_cannot_see_foreign_clinic_backlog(self):
        self.event();self.manager._adc_workspace.clinic=self.b;self.manager._adc_workspace.save(update_fields=['clinic'])
        # No grant at that clinic: the existing actor contract must still refuse.
        from django.core.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):delivery_status(actor=self.manager)

    def test_no_public_operational_endpoint(self):
        r=self.client.get('/health/');self.assertEqual(r.status_code,200)
        self.assertEqual(set(r.json()),{'status','version'})
        from django.urls import resolve
        self.assertEqual(resolve('/operations/').url_name,'operations_dashboard')
        self.assertEqual(self.client.get('/operations/').status_code,302)
        for url in ('/metrics/','/operations/status/','/private/operations/'):
            self.assertEqual(self.client.get(url).status_code,404)

    def test_crash_before_commit_rolls_back_inbox_then_recovers_once(self):
        self.event()
        def crash(event,now):
            _deliver(event,now)
            raise KeyboardInterrupt()
        with patch('notifications.dispatcher._deliver',side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):dispatch_one()
        self.assertFalse(InboxMessage.objects.exists());self.assertEqual(NotificationOutbox.objects.get().state,'PENDING')
        dispatch_one();self.assertIsNone(dispatch_one());self.assertEqual(InboxMessage.objects.count(),2)

    def test_commit_without_process_receipt_does_not_duplicate(self):
        self.event();dispatch_one()
        # Process receipt is deliberately ignored: persisted state is authoritative.
        self.dispatch();self.assertEqual(InboxMessage.objects.count(),2)
        self.assertEqual(database_sample()['due'],0)
