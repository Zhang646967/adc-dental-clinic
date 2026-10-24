"""Host incident rules; actual Docker/OOM exercise is recorded separately."""
from copy import deepcopy
from pathlib import Path
import subprocess
import tempfile
import sys
import unittest
from unittest.mock import patch

from adc_core.operations_store import PrivateStore
from scripts.host_events import Journal, SERVICES, EVENTS, backup_event, docker_sample, CollectionFailure, run
from scripts.g4_course import Course

TARGET = dict(v=1, project='adc_host_test', source='a'*40, context='test-local', docker='docker')


def now(n):
    return dict(utc=1800000000+n, mono=10000+n)


def rows():
    return [dict(id=str(i)*64, service=s, image='sha256:'+'a'*64, phase='running',
        exit_code=0, oom=False, restarts=0, started='initial', health='none')
        for i, s in enumerate(SERVICES, 1)]


class HostEventsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        PrivateStore(self.folder).write('target.json', TARGET)
        self.journal = Journal(self.folder)

    def collect(self, n, containers=None, events=None, saturated=False):
        return self.journal.collect(now=now(n), sample=lambda *_: (
            rows() if containers is None else containers, events or [], saturated))

    def problem(self):
        self.collect(0)
        changed = rows(); changed[3]['phase'] = 'exited'
        self.collect(30, changed)
        return self.journal.load()['incidents'][0]['id']

    def test_first_sample_and_two_good_samples(self):
        self.assertEqual(self.collect(0)['state'], 'HEALTHY')
        self.assertEqual(self.collect(30)['conditions']['notification-worker']['good'], 2)

    def test_worker_stop_is_critical(self):
        self.problem()
        self.assertEqual(self.journal.status(now=now(30))['conditions']['notification-worker']['state'], 'CRITICAL')

    def test_missing_container_is_unknown(self):
        self.assertEqual(self.collect(0, rows()[:-1])['conditions']['operations']['state'], 'UNKNOWN')

    def test_duplicate_service_is_not_healthy(self):
        self.assertEqual(self.collect(0, rows()+[rows()[0]])['conditions']['db']['state'], 'UNKNOWN')

    def test_restart_counter_and_recreation_are_retained(self):
        self.collect(0)
        changed=rows(); changed[1]['restarts']=1
        self.collect(30, changed)
        changed[1]['id']='f'*64
        self.collect(60, changed)
        codes=[e['code'] for e in self.journal.load()['events']]
        self.assertIn('CONTAINER_RESTARTED', codes)
        self.assertIn('CONTAINER_RECREATED', codes)

    def test_oom_survives_restart_and_requires_human_closure(self):
        self.collect(0)
        event=dict(ns=99, code='CONTAINER_OOM', id='4'*64, service='notification-worker')
        self.collect(30, events=[event]); self.collect(60); result=self.collect(90)
        self.assertEqual(result['state'], 'CRITICAL')
        self.assertEqual(result['active_incidents'][0]['code'], 'CONTAINER_OOM')

    def test_oom_reason_supersedes_generic_exit_in_same_sample(self):
        self.collect(0)
        changed=rows(); changed[3].update(phase='exited', oom=True, exit_code=137)
        result=self.collect(30, changed)
        self.assertEqual(result['active_incidents'][0]['code'], 'CONTAINER_OOM')

    def test_overlapping_events_do_not_duplicate(self):
        event=dict(ns=99, code='CONTAINER_RESTARTED', id='4'*64, service='notification-worker')
        self.collect(0, events=[event]); self.collect(30, events=[event])
        self.assertEqual(len(self.journal.load()['events']), 1)

    def test_collector_failure_preserves_last_success(self):
        self.collect(0)
        def broken(*_): raise subprocess.TimeoutExpired('docker', 15)
        result=self.journal.collect(sample=broken, now=now(30))
        self.assertEqual(result['state'], 'UNKNOWN')
        self.assertEqual(result['sampled'], now(0))

    def test_timeout_identifies_stage_without_subprocess_text(self):
        with patch('scripts.host_events.subprocess.run', side_effect=subprocess.TimeoutExpired(
                'PRIVATE-COMMAND', 15, output='PRIVATE-OUTPUT', stderr='PRIVATE-ERROR')):
            with self.assertRaises(CollectionFailure) as error: run(TARGET, 'events', '--format', 'PRIVATE-FORMAT')
        self.assertEqual((error.exception.stage,error.exception.category),('events','TIMEOUT'))
        self.assertNotIn('PRIVATE',str(error.exception))

    def test_failed_command_identifies_stage_without_stderr(self):
        with patch('scripts.host_events.subprocess.run', side_effect=subprocess.CalledProcessError(
                1,'PRIVATE-COMMAND',stderr='PRIVATE-ERROR')):
            with self.assertRaises(CollectionFailure) as error: run(TARGET,'inspect','PRIVATE-ID')
        self.assertEqual((error.exception.stage,error.exception.category),('inspect','EXIT_FAILURE'))
        self.assertNotIn('PRIVATE',str(error.exception))

    def test_missing_executable_has_fixed_diagnostic(self):
        with patch('scripts.host_events.subprocess.run', side_effect=FileNotFoundError('PRIVATE-PATH')):
            with self.assertRaises(CollectionFailure) as error: run(TARGET,'context','inspect')
        self.assertEqual((error.exception.stage,error.exception.category),('context','COMMAND_UNAVAILABLE'))

    def test_output_bound_is_recorded_without_retaining_output(self):
        with patch('scripts.host_events.subprocess.run', return_value=subprocess.CompletedProcess([],0,'x'*(256*1024+1))):
            with self.assertRaises(CollectionFailure) as error: run(TARGET,'ps')
        self.assertEqual((error.exception.stage,error.exception.category),('ps','OUTPUT_BOUND'))

    def test_lifecycle_filter_excludes_multiline_exec_before_projection(self):
        calls=[]
        def daemon(target,*args):
            calls.append(args)
            if args[0]=='context':return 'unix:///synthetic/docker.sock'
            if args[0]=='ps':return ''
            filters={args[i+1] for i,key in enumerate(args[:-1]) if key=='--filter'}
            # The real daemon returns exec command text unless action filters
            # are supplied; this is not a lifecycle event or a health sample.
            return '' if {'event='+a for a in EVENTS}<=filters else '1|exec_create: PRIVATE|COMMAND\nPRIVATE-LINE|'+('a'*64)+'|web'
        with patch('scripts.host_events.run',side_effect=daemon):
            containers,events,saturated=docker_sample(TARGET,1,2)
        self.assertEqual((containers,events,saturated),([],[],False))
        args=calls[-1]
        filters=[args[i+1] for i,key in enumerate(args[:-1]) if key=='--filter']
        self.assertEqual({v for v in filters if v.startswith('event=')},{'event='+a for a in EVENTS})
        self.assertIn('label=com.docker.compose.project='+TARGET['project'],filters)

    def test_filtered_oom_and_stop_events_are_still_projected(self):
        output='1|oom|'+('a'*64)+'|web\n2|stop|'+('b'*64)+'|notification-worker'
        def daemon(target,*args):
            if args[0]=='context':return 'unix:///synthetic/docker.sock'
            if args[0]=='ps':return ''
            return output
        with patch('scripts.host_events.run',side_effect=daemon):
            _,events,saturated=docker_sample(TARGET,1,2)
        self.assertFalse(saturated)
        self.assertEqual([e['code'] for e in events],['CONTAINER_OOM','CONTAINER_STOPPED'])

    def test_diagnostic_changes_retained_and_unchanged_failure_deduplicated(self):
        self.collect(0)
        def timeout(*_): raise CollectionFailure('events','TIMEOUT')
        self.journal.collect(sample=timeout,now=now(30))
        self.journal.collect(sample=timeout,now=now(60))
        self.assertEqual(len(self.journal.load()['events']),1)
        def failed(*_): raise CollectionFailure('inspect','EXIT_FAILURE')
        result=self.journal.collect(sample=failed,now=now(70))
        self.assertEqual(len(self.journal.load()['events']),2)
        self.assertEqual(result['last_collection_failure'],dict(stage='inspect',category='EXIT_FAILURE',at=now(70)))
        self.assertEqual(result['sampled'],now(0))
        self.assertEqual(result['state'],'UNKNOWN')

    def test_recovery_keeps_prior_diagnostic_and_unknown_history(self):
        self.collect(0)
        def failed(*_): raise CollectionFailure('ps','TIMEOUT')
        self.journal.collect(sample=failed,now=now(30))
        self.collect(60);result=self.collect(90)
        self.assertEqual(result['conditions']['collector']['state'],'HEALTHY')
        self.assertEqual(result['state'],'UNKNOWN')
        self.assertEqual(result['last_collection_failure']['at'],now(30))
        self.assertEqual(result['active_incidents'][0]['code'],'COLLECTOR_UNAVAILABLE')

    def test_watch_staleness_is_identified_without_docker(self):
        self.collect(0)
        self.assertEqual(self.journal.status(now=now(91))['conditions']['collector']['reason'], 'COLLECTOR_STALE_OR_CLOCK')

    def test_collection_gap_remains_incident_after_recovery(self):
        self.collect(0); self.collect(100); self.collect(130); result=self.collect(160)
        self.assertEqual(result['conditions']['collector']['state'], 'HEALTHY')
        self.assertEqual(result['state'], 'UNKNOWN')
        self.assertEqual(result['active_incidents'][0]['code'], 'COLLECTION_GAP')

    def test_event_ring_saturation_is_unknown(self):
        self.assertEqual(self.collect(0, saturated=True)['state'], 'UNKNOWN')

    def test_clock_regression_is_unknown_and_history_retained(self):
        self.collect(30)
        self.assertEqual(self.journal.status(now=now(0))['state'], 'UNKNOWN')
        self.assertEqual(self.collect(0)['active_incidents'][0]['code'], 'COLLECTION_GAP')

    def test_acknowledgement_changes_no_sample_or_condition(self):
        incident=self.problem(); before=self.journal.load()
        self.journal.handle(incident, 'operator_a', now=now(31))
        after=self.journal.load()
        self.assertEqual(before['sampled'], after['sampled'])
        self.assertEqual(before['conditions'], after['conditions'])

    def test_different_operator_cannot_take_over(self):
        incident=self.problem(); self.journal.handle(incident, 'operator_a', now=now(31))
        with self.assertRaises(ValueError): self.journal.handle(incident, 'operator_b', now=now(32))

    def test_close_requires_action_and_two_new_good_samples(self):
        incident=self.problem(); self.journal.handle(incident, 'operator_a', now=now(31))
        with self.assertRaises(ValueError): self.journal.handle(incident, 'operator_a', close=True, now=now(32))
        self.journal.handle(incident, 'operator_a', 'restart_service', now=now(32))
        self.collect(60)
        with self.assertRaises(ValueError): self.journal.handle(incident, 'operator_a', close=True, now=now(61))
        self.collect(90)
        self.journal.handle(incident, 'operator_a', close=True, now=now(91))
        self.assertEqual(self.journal.status(now=now(91))['state'], 'HEALTHY')
        self.assertIsNotNone(self.journal.load()['incidents'][0]['closed'])

    def test_stale_observation_cannot_close_incident(self):
        incident=self.problem(); self.collect(60); self.collect(90)
        self.journal.handle(incident, 'op', 'verify_health', now=now(91))
        with self.assertRaises(ValueError): self.journal.handle(incident, 'op', close=True, now=now(200))

    def test_repeated_sample_cannot_count_for_recovery(self):
        self.collect(0)
        with self.assertRaises(RuntimeError): self.collect(0)

    def test_backup_failure_and_success_retain_incident(self):
        self.collect(0); self.collect(30)
        self.journal.backup(False, now(31)); self.journal.backup(True, now(32))
        result=self.journal.status(now=now(32))
        self.assertEqual(result['conditions']['backup']['state'], 'HEALTHY')
        self.assertEqual(result['active_incidents'][0]['code'], 'BACKUP_FAILED')

    def test_optional_backup_observer_does_not_initialize_or_change_receipts(self):
        self.assertEqual(backup_event(self.folder, TARGET['project'], TARGET['source'], False), 'NOT_CONFIGURED')
        self.assertFalse((self.folder/'private/host-events').exists())

    def test_backup_wrapper_records_real_failure(self):
        course=object.__new__(Course); course.bundle=self.folder; course.plan=dict(
            project=TARGET['project'], requested_source_commit=TARGET['source'])
        with patch.object(course, '_backup', side_effect=ValueError('private diagnostic')), patch(
                'scripts.host_events.backup_event') as observer:
            with self.assertRaises(ValueError): course.backup('private-path')
        observer.assert_called_once_with(self.folder, TARGET['project'], TARGET['source'], False)

    def test_backup_wrapper_keeps_success_when_observer_unavailable(self):
        course=object.__new__(Course); course.bundle=self.folder; course.plan=dict(
            project=TARGET['project'], requested_source_commit=TARGET['source'])
        with patch.object(course, '_backup', return_value=dict(status='SERVER_BACKUP_CREATED')), patch(
                'scripts.host_events.backup_event', return_value='UNAVAILABLE'):
            self.assertEqual(course.backup('private-path')['status'], 'SERVER_BACKUP_CREATED')

    def test_docker_projection_does_not_request_logs_or_credentials(self):
        with patch('scripts.host_events.run', side_effect=['unix:///local.sock', '', '']) as command:
            self.assertEqual(docker_sample(TARGET, 1, 2), ([], [], False))
        arguments=repr(command.call_args_list)
        self.assertNotIn('logs', arguments)
        self.assertNotIn('exec', arguments)
        self.assertNotIn('Config.Env', arguments)

    def test_remote_endpoint_is_rejected_before_listing_containers(self):
        with patch('scripts.host_events.run', return_value='ssh://foreign') as command:
            with self.assertRaises(ValueError): docker_sample(TARGET, 1, 2)
        self.assertEqual(command.call_count, 1)

    def test_host_history_is_bounded_and_active_incident_retained(self):
        state=self.journal.load()
        for i in range(200): self.journal.event(state, 'CONTAINER_STARTED', 'web', now(i))
        self.assertEqual(len(state['events']), 192)
        self.assertEqual(state['pruned_events'], 8)

    def test_corrupt_host_status_is_unknown_exit_three(self):
        self.collect(0)
        (self.folder/'host.json').write_text('broken checksum')
        result=subprocess.run([sys.executable, 'scripts/host_events.py', '--directory',
            str(self.folder), 'status'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 3)
        self.assertIn('HOST_JOURNAL_UNAVAILABLE', result.stdout)
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__': unittest.main()
