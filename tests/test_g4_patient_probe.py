import contextlib
from io import BytesIO, StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs

from scripts.g4_patient_probe import Journey, availability, load_fixture, observe, summarize


FIXTURE = {'scope': 'synthetic-patient', 'host': 'adc.probe.test',
           'username': 'probe_fixture', 'password': 'do-not-record-fixture-password',
           'clinic': 1, 'service': 17, 'own_visit': 20, 'foreign_visit': 21}


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
        late = good | {'start_delay_ms': 10001}
        slow = good | {'elapsed_ms': 5001}
        self.assertEqual(summarize([good], 1441)['state'], 'INCOMPLETE')
        self.assertEqual(summarize([good] * 1441, 1441)['state'], 'PASS')
        self.assertEqual(summarize([slow] + [good] * 1440, 1441)['state'], 'PASS')
        self.assertEqual(summarize([late] + [good] * 1440, 1441)['state'], 'FAIL')
        self.assertEqual(summarize([good] * 1440 + [slow], 1441)['state'], 'FAIL')
        self.assertTrue(summarize([good, slow, slow], 3)['incident_open'])

    def test_alarm_events_and_failed_rounds_survive_recovery(self):
        ok = {'passed': True, 'elapsed_ms': 120}
        failed = {'passed': False, 'elapsed_ms': 9}
        rows = iter([ok, failed, failed, failed, ok])
        with TemporaryDirectory() as directory, contextlib.redirect_stdout(StringIO()):
            path = Path(directory) / 'receipt.json'
            summary = observe(lambda: next(rows), path, count=5, interval=0, scope='TEST')
            receipt = json.loads(path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual([row['event'] for row in receipt['samples'] if 'event' in row], ['OPENED', 'RECOVERED'])
        self.assertEqual(summary['good_samples'], 2)
        self.assertEqual(summary['state'], 'FAIL')
        self.assertFalse(summary['incident_open'])
