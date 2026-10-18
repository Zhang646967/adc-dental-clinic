"""Private file/condition adversarial checks, separate from PostgreSQL evidence."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from adc_core.operations_store import PrivateStore, canonical, MAX_BYTES
from adc_core.operations import (advance, acknowledge, conditions, fresh_state, status,
    worker_condition, Heartbeat, age, identity, MAX_INCIDENTS)

TARGET = {'instance':'adc_test_operations','source':'a'*40,'read_only':False}


def moment(t=0, boot='a'*36):
    return {'utc': 2000000000+t, 'mono': 10000+t, 'boot':boot}


def worker(t=0, **changes):
    return dict(v=1,kind='worker',identity=TARGET,at=moment(t),run='b'*32,sequence=t+1,
                phase='success',last_success=moment(t),last_delivery=None) | changes


def sample(t=0, **changes):
    return dict(v=1,kind='sample',identity=TARGET,at=moment(t),worker=worker(t),web=True,
        database={'due':0,'oldest_due_seconds':0,'pending':0,'failed':0,'delivered':0,'no_recipients':0},
        storage={'total':100*1024**3,'free':50*1024**3}) | changes


class OperationPolicies(unittest.TestCase):
    def healthy(self):
        state=fresh_state(TARGET,moment())
        advance(state,sample(),TARGET,moment())
        return advance(state,sample(30),TARGET,moment(30))

    def test_idle_database_loop_is_healthy_without_delivery(self):
        self.assertEqual(worker_condition(worker(),TARGET,moment(80))[0],'HEALTHY')
    def test_empty_start_is_not_success(self):
        self.assertEqual(worker_condition(worker(phase='starting',last_success=None),TARGET,moment())[0],'UNKNOWN')
    def test_live_loop_cannot_hide_old_db_success(self):
        self.assertEqual(worker_condition(worker(100,last_success=moment()),TARGET,moment(100))[1],'WORKER_NO_DB_PROGRESS')
    def test_stopped_worker_is_detected(self):
        self.assertEqual(worker_condition(worker(phase='stopped'),TARGET,moment())[1],'WORKER_STOPPED')
    def test_failed_worker_is_detected(self):
        self.assertEqual(worker_condition(worker(phase='failed'),TARGET,moment())[1],'WORKER_FAILED')
    def test_force_stop_leaves_stale_heartbeat(self):
        self.assertEqual(worker_condition(worker(),TARGET,moment(91))[1],'WORKER_STALE')
    def test_readonly_worker_absence_expected(self):
        self.assertEqual(worker_condition(None,TARGET|{'read_only':True},moment()),('HEALTHY','NOT_REQUIRED'))
    def test_foreign_instance_never_proves_progress(self):
        self.assertEqual(worker_condition(worker(identity=TARGET|{'instance':'adc_other'}),TARGET,moment())[0],'UNKNOWN')
    def test_foreign_source_never_proves_progress(self):
        self.assertEqual(worker_condition(worker(identity=TARGET|{'source':'c'*40}),TARGET,moment())[0],'UNKNOWN')
    def test_future_heartbeat_unknown(self):
        self.assertEqual(worker_condition(worker(1),TARGET,moment())[0],'UNKNOWN')
    def test_future_success_unknown(self):
        self.assertEqual(worker_condition(worker(last_success=moment(1)),TARGET,moment())[0],'UNKNOWN')
    def test_different_boot_unknown(self):
        self.assertEqual(worker_condition(worker(),TARGET,moment(1,boot='c'*36))[0],'UNKNOWN')
    def test_wall_clock_jump_unknown(self):
        with self.assertRaises(ValueError):age(moment(),moment(301)|{'mono':10000})
    def test_reversed_monotonic_unknown(self):
        with self.assertRaises(ValueError):age(moment(),moment(1)|{'mono':9999})
    def test_extra_private_worker_fields_rejected(self):
        self.assertEqual(worker_condition(worker(patient='private'),TARGET,moment())[0],'UNKNOWN')
    def test_invalid_boolean_sequence_rejected(self):
        self.assertEqual(worker_condition(worker(sequence=True),TARGET,moment())[0],'UNKNOWN')
    def test_first_sample_unknown_without_startup_incident(self):
        state=advance(fresh_state(TARGET,moment()),sample(),TARGET,moment())
        self.assertEqual(status(state,TARGET,moment())['state'],'UNKNOWN')
        self.assertFalse(state['incidents'])
    def test_two_samples_establish_health(self):
        self.assertEqual(status(self.healthy(),TARGET,moment(30))['state'],'HEALTHY')
    def test_repeated_sample_cannot_clear_fault(self):
        state=self.healthy()
        with self.assertRaises(ValueError):advance(state,sample(30),TARGET,moment(60))
    def test_stopped_observer_independent_reader_unknown(self):
        self.assertEqual(status(self.healthy(),TARGET,moment(121))['state'],'UNKNOWN')
    def test_foreign_collector_unknown(self):
        self.assertEqual(status(self.healthy(),TARGET|{'instance':'adc_other'},moment(30))['state'],'UNKNOWN')
    def test_reader_rechecks_worker_age(self):
        state=self.healthy();state['sample']['worker']=worker()
        self.assertEqual(status(state,TARGET,moment(91))['conditions']['worker']['state'],'CRITICAL')
    def test_due_age_grows_when_collector_stops(self):
        state=self.healthy();state['sample']['database'].update(due=1,pending=1,oldest_due_seconds=110)
        self.assertEqual(status(state,TARGET,moment(45))['conditions']['backlog']['state'],'WARNING')
    def test_future_retry_not_due(self):
        s=sample();s['database']['pending']=4
        self.assertEqual(conditions(s,TARGET,moment())['backlog'][0],'HEALTHY')
    def test_overdue_threshold(self):
        s=sample();s['database'].update(due=1,pending=1,oldest_due_seconds=121)
        self.assertEqual(conditions(s,TARGET,moment())['backlog'][0],'WARNING')
    def test_failed_not_mixed_with_delivered(self):
        s=sample();s['database'].update(failed=1,delivered=3,no_recipients=2)
        self.assertEqual(conditions(s,TARGET,moment())['failed_delivery'][0],'WARNING')
    def test_database_failure_not_zero_backlog(self):
        c=conditions(sample(database=None),TARGET,moment())
        self.assertEqual(c['backlog'][0],'UNKNOWN');self.assertEqual(c['database'][0],'CRITICAL')
    def test_first_readiness_failure_is_unknown_then_critical(self):
        state=self.healthy();advance(state,sample(60,web=False),TARGET,moment(60))
        self.assertEqual(state['conditions']['web']['state'],'UNKNOWN')
        advance(state,sample(90,web=False),TARGET,moment(90))
        self.assertEqual(state['conditions']['web']['state'],'CRITICAL')
    def test_repeating_fault_has_one_opening(self):
        state=self.healthy()
        for t in (60,90,120):advance(state,sample(t,worker=None),TARGET,moment(t))
        rows=[i for i in state['incidents'] if i['condition']=='worker']
        self.assertEqual(len(rows),1);self.assertEqual(len(rows[0]['history']),1)
    def test_acknowledgement_not_recovery_or_freshness(self):
        state=self.healthy();advance(state,sample(60,worker=None),TARGET,moment(60));before=copy.deepcopy(state['at'])
        row=next(i for i in state['incidents'] if i['condition']=='worker')
        acknowledge(state,TARGET,row['id'],'course_operator',moment(61))
        self.assertEqual(state['conditions']['worker']['state'],'UNKNOWN')
        self.assertEqual(state['at'],before);self.assertIsNone(row['recovered'])
    def test_ack_idempotent_and_different_owner_rejected(self):
        state=self.healthy();advance(state,sample(60,worker=None),TARGET,moment(60));row=state['incidents'][0]
        acknowledge(state,TARGET,row['id'],'operator_a',moment(61));acknowledge(state,TARGET,row['id'],'operator_a',moment(62))
        self.assertEqual(len(row['history']),2)
        with self.assertRaises(ValueError):acknowledge(state,TARGET,row['id'],'operator_b',moment(63))
    def test_recovery_requires_two_new_successes(self):
        state=self.healthy();advance(state,sample(60,worker=None),TARGET,moment(60));row=state['incidents'][0]
        advance(state,sample(90),TARGET,moment(90));self.assertIsNone(row['recovered'])
        advance(state,sample(120),TARGET,moment(120));self.assertIsNotNone(row['recovered'])
        self.assertEqual([h['event'] for h in row['history']],['opened','recovered'])
    def test_low_storage_with_hysteresis(self):
        state=self.healthy();total=100*1024**3
        for t,free,expected in [(60,9,'CRITICAL'),(90,14,'CRITICAL'),(120,21,'WARNING'),(150,26,'UNKNOWN'),(180,26,'HEALTHY')]:
            advance(state,sample(t,storage={'total':total,'free':free*1024**3}),TARGET,moment(t))
            self.assertEqual(state['conditions']['storage']['state'],expected)
    def test_small_absolute_space_is_critical(self):
        self.assertEqual(conditions(sample(storage={'total':2*1024**3,'free':900*1024**2}),TARGET,moment())['storage'][0],'CRITICAL')
    def test_invalid_storage_unknown_not_healthy(self):
        state=self.healthy();state['sample']['storage']={'total':0,'free':0}
        self.assertEqual(status(state,TARGET,moment(30))['state'],'UNKNOWN')
    def test_unidentified_build_cannot_be_healthy(self):
        t=TARGET|{'source':'unknown'};s=sample();s['identity']=t
        self.assertEqual(conditions(s,t,moment())['worker'][1],'SOURCE_UNIDENTIFIED')
    def test_invalid_aggregate_boolean_rejected(self):
        s=sample();s['database']['due']=True
        with self.assertRaises(ValueError):conditions(s,TARGET,moment())
    def test_private_aggregate_fields_rejected(self):
        s=sample();s['database']['recipients']=['private']
        with self.assertRaises(ValueError):conditions(s,TARGET,moment())
    def test_nonfinite_age_rejected(self):
        s=sample();s['database']['oldest_due_seconds']=float('nan')
        with self.assertRaises(ValueError):conditions(s,TARGET,moment())
    def test_unknown_condition_reason_rejected(self):
        state=self.healthy();state['conditions']['web']['reason']='private secret'
        self.assertEqual(status(state,TARGET,moment(30))['state'],'UNKNOWN')
    def test_incident_retention_bounded_without_removing_active(self):
        state=self.healthy()
        for k in range(MAX_INCIDENTS+4):
            t=60+90*k
            advance(state,sample(t,worker=None),TARGET,moment(t))
            advance(state,sample(t+30),TARGET,moment(t+30));advance(state,sample(t+60),TARGET,moment(t+60))
        advance(state,sample(t+90,worker=None),TARGET,moment(t+90))
        self.assertEqual(len(state['incidents']),MAX_INCIDENTS);self.assertGreater(state['pruned_incidents'],0)
        self.assertEqual(sum(i['recovered'] is None for i in state['incidents']),1)
    def test_instance_identity_does_not_accept_url(self):
        with patch.dict(os.environ,{'ADC_OPERATIONS_INSTANCE':'https://private'}):
            with self.assertRaises(ValueError):identity()
    def test_regressed_worker_sequence_is_unknown(self):
        state=self.healthy()
        advance(state,sample(60,worker=worker(60,sequence=1)),TARGET,moment(60))
        self.assertEqual(state['conditions']['worker']['state'],'UNKNOWN')
    def test_modified_time_cannot_reuse_sequence(self):
        state=self.healthy()
        advance(state,sample(60,worker=worker(60,sequence=31)),TARGET,moment(60))
        self.assertEqual(state['conditions']['worker']['state'],'UNKNOWN')
    def test_boolean_schema_version_not_trusted(self):
        self.assertEqual(worker_condition(worker(v=True),TARGET,moment())[0],'UNKNOWN')
    def test_integer_readonly_flag_not_trusted(self):
        self.assertEqual(worker_condition(worker(identity=TARGET|{'read_only':0}),TARGET,moment())[0],'UNKNOWN')


class PrivateFiles(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=PrivateStore(self.root)
    def test_roundtrip_owner_only_and_digest(self):
        self.store.write('monitor.json',{'state':'UNKNOWN'})
        self.assertEqual(self.store.read('monitor.json'),{'state':'UNKNOWN'})
        self.assertEqual((self.root/'monitor.json').stat().st_mode&0o777,0o600)
    def test_checksum_mismatch_not_trusted(self):
        self.store.write('monitor.json',{})
        p=self.root/'monitor.json';p.write_text('{"payload":{},"sha256":"0"}')
        with self.assertRaises(ValueError):self.store.read('monitor.json')
    def test_symlink_cannot_be_read_or_replaced(self):
        other=self.root/'private';other.write_text('do not alter');(self.root/'monitor.json').symlink_to(other)
        with self.assertRaises((ValueError,OSError)):self.store.read('monitor.json')
        with self.assertRaises((ValueError,OSError)):self.store.write('monitor.json',{})
        self.assertEqual(other.read_text(),'do not alter')
    def test_public_file_rejected(self):
        self.store.write('monitor.json',{});(self.root/'monitor.json').chmod(0o644)
        with self.assertRaises(ValueError):self.store.read('monitor.json')
    def test_public_directory_rejected(self):
        self.root.chmod(0o755)
        with self.assertRaises(ValueError):PrivateStore(self.root)
    def test_duplicate_json_field_rejected(self):
        p=self.root/'monitor.json';p.write_text('{"payload":{},"payload":{},"sha256":"x"}');p.chmod(0o600)
        with self.assertRaises(ValueError):self.store.read('monitor.json')
    def test_overlarge_file_rejected(self):
        p=self.root/'monitor.json';p.write_bytes(b' '* (MAX_BYTES+1));p.chmod(0o600)
        with self.assertRaises(ValueError):self.store.read('monitor.json')
    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):self.store.write('../outside',{})
    def test_single_writer_lock(self):
        with self.store.lock('writer.lock'):
            with self.assertRaises(BlockingIOError):
                with self.store.lock('writer.lock'):pass
    def test_failed_replace_preserves_old_complete_record(self):
        self.store.write('monitor.json',{'value':1})
        with patch('adc_core.operations_store.os.replace',side_effect=OSError('private failure')):
            with self.assertRaises(OSError):self.store.write('monitor.json',{'value':2})
        self.assertEqual(self.store.read('monitor.json'),{'value':1})
        self.assertEqual([p.name for p in self.root.iterdir()],['monitor.json'])
    def test_idle_heartbeat_separates_three_facts(self):
        h=Heartbeat(self.root,TARGET)
        with patch('adc_core.operations.clock',return_value=moment()):h.write('success')
        with patch('adc_core.operations.clock',return_value=moment(5)):h.write('polling')
        record=self.store.read('heartbeat.json')
        self.assertEqual(record['at'],moment(5));self.assertEqual(record['last_success'],moment());self.assertIsNone(record['last_delivery'])
    def test_delivery_time_advances_only_with_committed_delivery(self):
        h=Heartbeat(self.root,TARGET)
        with patch('adc_core.operations.clock',return_value=moment()):h.write('success',delivered=True)
        with patch('adc_core.operations.clock',return_value=moment(5)):h.write('success')
        self.assertEqual(self.store.read('heartbeat.json')['last_delivery'],moment())
    def test_explicit_archive_preserves_prior_record_and_is_bounded(self):
        for i in range(5):
            self.store.write('monitor.json',{'version':i});self.store.archive_monitor()
        self.assertEqual(self.store.read('previous-1.json'),{'version':4})
        self.assertEqual(len(list(self.root.glob('previous-*.json'))),3)
    def test_deeply_nested_corruption_is_invalid(self):
        p=self.root/'monitor.json';p.write_text('['*10000+']'*10000);p.chmod(0o600)
        with self.assertRaises(ValueError):self.store.read('monitor.json')
