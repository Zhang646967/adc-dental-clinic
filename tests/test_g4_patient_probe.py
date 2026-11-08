import contextlib
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs

from scripts.g4_patient_probe import Journey, availability, load_fixture, observe, summarize
from scripts.g4_probe_watch import check


FIXTURE = {'scope': 'synthetic-patient', 'host': 'adc.probe.test',
           'username': 'probe_fixture', 'password': 'do-not-record-fixture-password',
           'clinic': 1, 'service': 17, 'own_visit': 20, 'foreign_visit': 21}
START = datetime(2026, 11, 7, tzinfo=timezone.utc)


class ProbeTests(TestCase):
    def test_fixture_requires_private_file_and_distinct_results(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.json'
            path.write_text(json.dumps(FIXTURE))
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                load_fixture(path)
            path.chmod(0o600)
            self.assertEqual(load_fixture(path), FIXTURE)
            path.write_text(json.dumps(FIXTURE | {'foreign_visit': FIXTURE['own_visit']}))
            with self.assertRaises(ValueError):
                load_fixture(path)

    def run_fixture(self, availability_response):
        actor = {'authenticated': True, 'subject_key': 'self', 'delegated': False,
                 'csrf_token': 'private-csrf-value', 'workspace_token': 'private-workspace',
                 'today': '2026-11-07'}
        responses = [
            (200, {'clinics': [{'id': 1, 'synthetic': True, 'services': [{'id': 17}]}]}),
            (401, 'LOGIN_REQUIRED'),
            (200, {'authenticated': False, 'csrf_token': 'guest-csrf'}),
            (200, actor),
            availability_response,
            (200, {'id': 20, 'clinic_id': 1, 'status': 'SCHEDULED', 'clinic': 'private-result'}),
            (404, 'NOT_FOUND'),
            (200, {'authenticated': False}),
        ]

        def reply(request, timeout):
            status, result = responses.pop(0)
            if request.selector.endswith('/login/'):
                self.assertEqual(parse_qs(request.data.decode())['password'], [FIXTURE['password']])
                self.assertEqual(request.get_header('X-csrftoken'), 'guest-csrf')
                self.assertEqual(request.get_header('Origin'), 'https://adc.probe.test')
            if 'candidates/' in request.selector:
                self.assertIn('day=2026-11-08', request.selector)
                self.assertEqual(request.get_header('X-adc-workspace'), 'private-workspace')
            payload = {'ok': status == 200, 'request_id': 'a' * 32}
            payload['data' if status == 200 else 'code'] = result
            response = BytesIO(json.dumps(payload).encode())
            response.status = status
            return response

        journey = Journey(FIXTURE)
        with patch.object(journey.opener, 'open', side_effect=reply) as calls:
            journey.run()
        self.assertEqual([call.args[0].get_method() for call in calls.call_args_list],
                         ['GET', 'GET', 'GET', 'POST', 'GET', 'GET', 'GET', 'POST'])
        self.assertEqual(len(journey.steps), 8)
        for secret in (FIXTURE['password'], FIXTURE['username'], 'private-workspace', 'private-result', 'guest-csrf'):
            self.assertNotIn(secret, json.dumps(journey.steps))
        return journey.steps

    def test_patient_journey_keeps_only_operational_fields(self):
        steps = self.run_fixture((200, {'status': 'NO_SCHEDULE', 'rows': []}))
        self.assertTrue(all(step['passed'] for step in steps))

    def test_health_cannot_mask_failure_in_availability_and_logout_still_runs(self):
        steps = self.run_fixture((503, 'OUTAGE'))
        self.assertEqual([step['step'] for step in steps if not step['passed']], ['availability'])
        self.assertTrue(steps[-1]['passed'])

    def test_availability_must_match_rows(self):
        self.assertFalse(availability({'status': 'AVAILABLE', 'rows': []}))
        self.assertFalse(availability({'status': 'NO_SCHEDULE', 'rows': [{'slot': 5}]}))
        self.assertTrue(availability({'status': 'AVAILABLE', 'rows': [{'slot': 5}]}))
        self.assertTrue(availability({'status': 'NO_COMBINATION', 'rows': []}))

    def test_observation_requires_coverage_latency_and_final_healthy_sample(self):
        good = {'passed': True, 'elapsed_ms': 35, 'start_delay_ms': 0}
        rows = [good | {'at': (START + timedelta(minutes=n)).isoformat()} for n in range(1441)]
        self.assertEqual(summarize(rows[:1], 1441)['state'], 'INCOMPLETE')
        self.assertEqual(summarize(rows, 1441)['state'], 'PASS')
        self.assertEqual(summarize([rows[0] | {'elapsed_ms': 5001}] + rows[1:], 1441)['state'], 'PASS')
        self.assertEqual(summarize([rows[0] | {'start_delay_ms': 10001}] + rows[1:], 1441)['state'], 'FAIL')
        self.assertEqual(summarize(rows[:-1] + [rows[-1] | {'elapsed_ms': 5001}], 1441)['state'], 'FAIL')
        self.assertTrue(summarize(rows[:1] + [r | {'elapsed_ms': 5001} for r in rows[1:3]], 3)['incident_open'])
        gap = rows[:720] + [r | {'at': (START + timedelta(minutes=n, days=1)).isoformat()}
                           for n, r in enumerate(rows[720:], start=720)]
        for bad in (gap, rows[:720] + [rows[719]] + rows[721:],
                    rows[:720] + rows[720:722][::-1] + rows[722:]):
            with self.subTest(at=bad[720]['at']):
                result = summarize(bad, 1441)
                self.assertEqual(result['state'], 'FAIL')
                self.assertFalse(result['wall_clock_schedule_verified'])
        delayed = rows[720] | {'at': (START + timedelta(minutes=720, seconds=9)).isoformat(),
                               'start_delay_ms': 9000}
        self.assertEqual(summarize(rows[:720] + [delayed] + rows[721:], 1441)['state'], 'PASS')
        self.assertEqual(summarize(rows, 1441, started_at=(START - timedelta(hours=1)).isoformat())['state'], 'FAIL')

    def test_alarm_events_and_failed_rounds_survive_recovery(self):
        ok = {'passed': True, 'elapsed_ms': 120}
        failed = {'passed': False, 'elapsed_ms': 9}
        rows = iter([ok, failed, failed, failed, ok])
        clock = [0]
        with (TemporaryDirectory() as directory, contextlib.redirect_stdout(StringIO()) as output,
              patch('scripts.g4_patient_probe.time.monotonic', side_effect=lambda: clock[0]),
              patch('scripts.g4_patient_probe.time.sleep', side_effect=lambda delay: clock.__setitem__(0, clock[0] + delay)),
              patch('scripts.g4_patient_probe.datetime') as dt):
            dt.now.side_effect = lambda tz: START + timedelta(seconds=clock[0])
            path = Path(directory) / 'receipt.json'
            summary = observe(lambda: next(rows), path, count=5, interval=5, scope='TEST')
            receipt = json.loads(path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual([row['event'] for row in receipt['samples'] if 'event' in row], ['OPENED', 'RECOVERED'])
        self.assertEqual([json.loads(line)['signal'] for line in output.getvalue().splitlines()],
                         ['PATIENT_JOURNEY', 'PATIENT_JOURNEY'])
        self.assertEqual(summary['good_samples'], 2)
        self.assertEqual(summary['state'], 'FAIL')
        self.assertFalse(summary['incident_open'])
        self.assertTrue(summary['wall_clock_schedule_verified'])

    def test_independent_heartbeat_detects_stop_and_recovers_on_new_activity(self):
        with TemporaryDirectory() as directory:
            receipt, state = (Path(directory) / name for name in ('receipt.json', 'heartbeat.json'))
            data = {'interval_seconds': 60, 'expected_samples': 2, 'started_at': START.isoformat(),
                    'samples': [], 'summary': summarize([], 2)}
            receipt.write_text(json.dumps(data))
            receipt.chmod(0o600)
            self.assertEqual(check(receipt, state, START)['state'], 'FRESH')
            then = START + timedelta(seconds=131)
            outage = check(receipt, state, then)
            self.assertEqual((outage['signal'], outage['state'], outage['event']),
                             ('PROBE_HEARTBEAT', 'STALE', 'OPENED'))
            self.assertNotIn('event', check(receipt, state, then))
            data['samples'] = [{'passed': False, 'at': then.isoformat(), 'start_delay_ms': 0, 'elapsed_ms': 45}]
            data['summary'] = summarize(data['samples'], 2)
            receipt.write_text(json.dumps(data))
            self.assertEqual(check(receipt, state, then)['event'], 'RECOVERED')
            self.assertEqual(state.stat().st_mode & 0o777, 0o600)
            data['samples'].append(data['samples'][0] | {'at': (then + timedelta(minutes=1)).isoformat()})
            data['summary'] = summarize(data['samples'], 2)
            receipt.write_text(json.dumps(data))
            finished = check(receipt, state, then + timedelta(days=1))
            self.assertEqual((finished['state'], finished['observation']), ('FINISHED', 'FAIL'))
            self.assertFalse(finished['incident_open'])
            receipt.unlink()
            self.assertEqual(check(receipt, state, then)['event'], 'OPENED')
