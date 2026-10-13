"""Real worker processes, POSIX signals and PostgreSQL transaction recovery.

The insert barrier exists only in Django's disposable test database. These
checks do not substitute for the manual browser routes or a Windows restore.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from unittest import skipUnless

from django.db import connection
from django.test import TransactionTestCase

from coordination.models import CoordinationTask
from coordination.task_rules import ACTION_REASONS
from coordination.task_services import inspect_task, prepare_task, confirm_task
from notifications.dispatcher import dispatch_batch
from notifications.models import NotificationOutbox, InboxMessage
from tests.fixtures import FixtureMixin
from workspaces.models import WorkspaceContext

ROOT = Path(__file__).resolve().parents[1]


@skipUnless(os.name == 'posix', 'Worker process acceptance requires POSIX signals.')
class WorkerProcessTests(FixtureMixin, TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor, 'postgresql')
        self.assertTrue(connection.settings_dict['NAME'].startswith('test_'))
        self.make_fixture()
        for actor, role in ((self.manager, 'MANAGER'), (self.front, 'FRONT_DESK')):
            actor._adc_workspace = WorkspaceContext.objects.create(
                user=actor, role=role, clinic=self.a, revision=1)
        self.slot1.booking_paused = True
        self.slot1.intake_revision = 1
        self.slot1.save(update_fields=['booking_paused', 'intake_revision'])
        self.temp = TemporaryDirectory(prefix='adc-worker-process-')
        self.addCleanup(self.temp.cleanup)

    def transition(self, actor, action, task=None):
        _, state = inspect_task(actor=actor, slot_id=self.slot1.pk,
                                task_id=task.pk if task else None)
        proposal = prepare_task(
            actor=actor, slot_id=self.slot1.pk, task_id=task.pk if task else None,
            state_token=state, action=action, reason=ACTION_REASONS[action][0],
            purpose='REPLACE' if action == 'open' else '')
        result = confirm_task(actor=actor, slot_id=self.slot1.pk,
                              task_id=task.pk if task else None,
                              proposal_token=proposal['proposal_token'], confirmed=True)
        return CoordinationTask.objects.get(pk=result.task_id)

    def new_task(self):
        return self.transition(self.manager, 'open')

    def start_worker(self, **overrides):
        name = 'adc_worker_test_' + secrets.token_hex(6)
        database = connection.settings_dict
        env = {**os.environ, 'POSTGRES_DB': database['NAME'],
               'POSTGRES_USER': database['USER'], 'POSTGRES_PASSWORD': database['PASSWORD'],
               'DB_HOST': database['HOST'], 'DB_PORT': str(database['PORT']),
               'DJANGO_SETTINGS_MODULE': 'config.settings.course_demo',
               'ADC_RC_SYNTHETIC': '1', 'ADC_READ_ONLY': '0', 'PGAPPNAME': name,
               'AI_MODE': 'disabled', 'AI_API_KEY': '', 'OPENAI_API_KEY': '',
               'PYTHONUNBUFFERED': '1', **overrides}
        stdout = (Path(self.temp.name) / (name + '.stdout')).open('w+', encoding='utf-8')
        stderr = (Path(self.temp.name) / (name + '.stderr')).open('w+', encoding='utf-8')
        process = subprocess.Popen([sys.executable, 'scripts/rc_worker.py'],
                                   cwd=ROOT, env=env, stdout=stdout, stderr=stderr)
        worker = {'process': process, 'name': name, 'stdout': stdout, 'stderr': stderr}
        self.addCleanup(self.cleanup_worker, worker)
        return worker

    def cleanup_worker(self, worker):
        process = worker['process']
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        worker['stdout'].close()
        worker['stderr'].close()

    def output(self, worker):
        return ''.join(Path(f.name).read_text(encoding='utf-8')
                       for f in (worker['stdout'], worker['stderr']))

    def until(self, predicate, message, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        self.fail(message)

    def delivered(self, event):
        self.until(lambda: NotificationOutbox.objects.get(pk=event.pk).state == 'DELIVERED',
                   'The actual worker did not commit the expected delivery.')

    def stop_worker(self, worker):
        worker['process'].terminate()
        self.assertEqual(worker['process'].wait(timeout=8), 0)
        self.assertIn('通知处理已停止', self.output(worker))

    def assert_private_logs(self, worker):
        text = self.output(worker)
        for private in ('test_front', 'test_manager', '演示患者', 'recipients', 'event_id',
                        connection.settings_dict['PASSWORD']):
            self.assertNotIn(private, text)

    @contextmanager
    def held_insert(self):
        # A real BEFORE INSERT lock holds the worker before COMMIT is sent.
        # This avoids treating a lost COMMIT receipt as proof of rollback.
        name = 'adc_worker_hold_' + secrets.token_hex(6)
        quoted = connection.ops.quote_name(name)
        table = connection.ops.quote_name(InboxMessage._meta.db_table)
        key = 2140000000 + secrets.randbelow(1000000)
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE FUNCTION {quoted}() RETURNS trigger LANGUAGE plpgsql AS '
                           f'$$ BEGIN PERFORM pg_advisory_xact_lock({key}); RETURN NEW; END; $$')
            cursor.execute(f'CREATE TRIGGER {quoted} BEFORE INSERT ON {table} '
                           f'FOR EACH ROW EXECUTE FUNCTION {quoted}()')
            cursor.execute('SELECT pg_advisory_lock(%s)', [key])
            cursor.execute('SELECT pg_backend_pid()')
            owner = cursor.fetchone()[0]
        try:
            yield owner
        finally:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s)', [key])
                cursor.execute(f'DROP TRIGGER {quoted} ON {table}')
                cursor.execute(f'DROP FUNCTION {quoted}()')

    def wait_blocked(self, worker, owner):
        def blocked():
            with connection.cursor() as cursor:
                cursor.execute('SELECT EXISTS (SELECT 1 FROM pg_stat_activity '
                               'WHERE application_name=%s AND %s=ANY(pg_blocking_pids(pid)))',
                               [worker['name'], owner])
                return cursor.fetchone()[0]
        self.until(blocked, 'The actual worker did not reach the controlled PostgreSQL insert.')

    def test_idle_worker_handles_sigterm_cleanly(self):
        worker = self.start_worker()
        self.until(lambda: '"processed": 0' in self.output(worker), 'Worker did not start.')
        self.stop_worker(worker)
        self.assert_private_logs(worker)

    def test_restart_consumes_new_pending_event_without_replaying_old_delivery(self):
        task = self.new_task()
        first = NotificationOutbox.objects.get(action='open')
        worker = self.start_worker()
        self.delivered(first)
        self.stop_worker(worker)
        self.assertEqual(InboxMessage.objects.count(), 2)
        self.transition(self.front, 'claim', task)
        second = NotificationOutbox.objects.get(action='claim')
        expected_task = CoordinationTask.objects.values().get(pk=task.pk)
        self.assertEqual(second.state, 'PENDING')
        restarted = self.start_worker()
        self.delivered(second)
        self.stop_worker(restarted)
        self.assertEqual(InboxMessage.objects.count(), 3)
        self.assertEqual(CoordinationTask.objects.values().get(pk=task.pk), expected_task)
        self.assert_private_logs(worker)
        self.assert_private_logs(restarted)

    def shutdown_during_delivery(self, signum):
        task = self.new_task()
        self.transition(self.front, 'claim', task)
        first = NotificationOutbox.objects.get(action='open')
        second = NotificationOutbox.objects.get(action='claim')
        expected_task = CoordinationTask.objects.values().get(pk=task.pk)
        with self.held_insert() as owner:
            worker = self.start_worker()
            self.wait_blocked(worker, owner)
            self.assertFalse(InboxMessage.objects.exists())
            worker['process'].send_signal(signum)
        self.assertEqual(worker['process'].wait(timeout=8), 0)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.state, second.state, second.attempts), ('DELIVERED', 'PENDING', 0))
        self.assertEqual(InboxMessage.objects.count(), 2)
        restarted = self.start_worker()
        self.delivered(second)
        self.stop_worker(restarted)
        self.assertEqual(InboxMessage.objects.count(), 3)
        self.assertEqual(CoordinationTask.objects.values().get(pk=task.pk), expected_task)
        self.assert_private_logs(worker)

    def test_sigterm_finishes_current_transaction_but_admits_no_next_event(self):
        self.shutdown_during_delivery(signal.SIGTERM)

    def test_sigint_finishes_current_transaction_but_admits_no_next_event(self):
        self.shutdown_during_delivery(signal.SIGINT)

    def test_sigkill_before_commit_rolls_back_and_restart_delivers_once(self):
        self.new_task()
        event = NotificationOutbox.objects.get()
        with self.held_insert() as owner:
            worker = self.start_worker()
            self.wait_blocked(worker, owner)
            worker['process'].kill()
            self.assertEqual(worker['process'].wait(timeout=8), -signal.SIGKILL)
        def disconnected():
            with connection.cursor() as cursor:
                cursor.execute('SELECT NOT EXISTS (SELECT 1 FROM pg_stat_activity '
                               'WHERE application_name=%s)', [worker['name']])
                return cursor.fetchone()[0]
        self.until(disconnected, 'Killed worker connection did not roll back and close.')
        event.refresh_from_db()
        self.assertEqual((event.state, event.attempts), ('PENDING', 0))
        self.assertFalse(InboxMessage.objects.exists())
        restarted = self.start_worker()
        self.delivered(event)
        self.stop_worker(restarted)
        self.assertEqual(InboxMessage.objects.count(), 2)

    def test_stop_requested_before_batch_leaves_the_event_unattempted(self):
        self.new_task()
        self.assertEqual(dispatch_batch(25, should_stop=lambda: True), [])
        event = NotificationOutbox.objects.get()
        self.assertEqual((event.state, event.attempts), ('PENDING', 0))
        self.assertFalse(InboxMessage.objects.exists())

    def test_readonly_wrapper_exits_before_loading_django_or_connecting(self):
        self.new_task()
        worker = self.start_worker(ADC_READ_ONLY='1', DJANGO_SETTINGS_MODULE='must_not_load',
                                   DB_HOST='must-not-connect.invalid')
        self.assertEqual(worker['process'].wait(timeout=5), 0)
        self.assertIn('Read-only instance', self.output(worker))
        self.assertEqual(NotificationOutbox.objects.get().attempts, 0)
        self.assertFalse(InboxMessage.objects.exists())

    def test_non_course_wrapper_refuses_before_loading_django(self):
        worker = self.start_worker(ADC_RC_SYNTHETIC='0', DJANGO_SETTINGS_MODULE='must_not_load')
        self.assertNotEqual(worker['process'].wait(timeout=5), 0)
        self.assertIn('Not an RC course instance', self.output(worker))
