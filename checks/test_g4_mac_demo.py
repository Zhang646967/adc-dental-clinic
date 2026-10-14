"""Process-identity safeguards; no tunnel, Docker or OS signal is executed."""
import json
from http.client import HTTPException
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.g4_prepare import prepare
from scripts.g4_mac_demo import (atomic_text, check_origin, matches_process, refresh_access,
                                 start, status_or_stop, tunnel_registration, tunnel_protocol, wait_for_registration)


class MacDemoProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / '.g4'
        prepare(self.folder, host='course-demo.trycloudflare.com', source_commit='a' * 40,
                app_image='sha256:' + 'b' * 64, db_image='postgres:17@sha256:' + 'c' * 64,
                nginx_image='nginx:stable-alpine@sha256:' + 'd' * 64, http_port=18020, mode='mac_tunnel')
        self.metadata = self.folder / 'private/tunnel.json'
        self.plan = json.loads((self.folder / 'plan.json').read_text())
        atomic_text(self.metadata, json.dumps({'pid': 12345, 'process_stamp': 'original process',
                                              'project': self.plan['project'],
                                              'url': 'https://course-demo.trycloudflare.com'}))
        atomic_text(self.folder / 'private/tunnel.log',
                    'INF Registered tunnel connection protocol=http2\n')

    def test_reused_pid_is_never_signalled(self):
        with patch('scripts.g4_mac_demo.sys.platform', 'darwin'), \
             patch('scripts.g4_mac_demo.process_stamp', return_value='different process'), \
             patch('scripts.g4_mac_demo.os.kill') as kill:
            self.assertEqual(status_or_stop(self.folder)['status'], 'STOPPED')
            self.assertEqual(status_or_stop(self.folder, stop=True)['database'], 'preserved')
            kill.assert_not_called()

    def test_stop_targets_only_the_recorded_matching_process(self):
        with patch('scripts.g4_mac_demo.sys.platform', 'darwin'), \
             patch('scripts.g4_mac_demo.process_stamp', return_value='original process'), \
             patch('scripts.g4_mac_demo.os.kill') as kill:
            self.assertEqual(status_or_stop(self.folder, stop=True)['status'], 'STOP_REQUESTED')
            kill.assert_called_once_with(12345, signal.SIGTERM)
        self.assertTrue(json.loads(self.metadata.read_text())['stopped'])
        self.assertEqual(self.metadata.stat().st_mode & 0o077, 0)

    def test_running_tunnel_cannot_be_replaced_by_another_start(self):
        with patch('scripts.g4_mac_demo.sys.platform', 'darwin'), \
             patch('scripts.g4_mac_demo.process_stamp', return_value='original process'), \
             patch('scripts.g4_mac_demo.subprocess.Popen') as launch:
            with self.assertRaises(ValueError):
                start(self.folder, '/does-not-exist')
            launch.assert_not_called()

    def test_running_status_requires_the_actual_origin(self):
        with patch('scripts.g4_mac_demo.sys.platform', 'darwin'), \
             patch('scripts.g4_mac_demo.process_stamp', return_value='original process'), \
             patch('scripts.g4_mac_demo.check_origin') as origin:
            result = status_or_stop(self.folder)
        origin.assert_called_once_with('course-demo.trycloudflare.com', 18020)
        self.assertEqual(result['status'], 'RUNNING')
        self.assertTrue(result['origin_ready'])
        self.assertEqual(result['public_https'], 'NOT_CHECKED')
        self.assertFalse(result['public_acceptance_executed'])

    def test_tunnel_with_unavailable_origin_reports_degraded(self):
        for error in (RuntimeError('not ready'), OSError('connection refused'), HTTPException('bad response')):
            with self.subTest(error=type(error).__name__), \
                 patch('scripts.g4_mac_demo.sys.platform', 'darwin'), \
                 patch('scripts.g4_mac_demo.process_stamp', return_value='original process'), \
                 patch('scripts.g4_mac_demo.check_origin', side_effect=error), \
                 patch('scripts.g4_mac_demo.os.kill') as kill:
                result = status_or_stop(self.folder)
                self.assertEqual(result['status'], 'DEGRADED')
                self.assertTrue(result['tunnel_running'])
                self.assertFalse(result['origin_ready'])
                kill.assert_not_called()

    def test_broken_origin_does_not_prevent_stopping_the_owned_tunnel(self):
        with patch('scripts.g4_mac_demo.sys.platform', 'darwin'), \
             patch('scripts.g4_mac_demo.process_stamp', return_value='original process'), \
             patch('scripts.g4_mac_demo.check_origin') as origin, \
             patch('scripts.g4_mac_demo.os.kill') as kill:
            self.assertEqual(status_or_stop(self.folder, stop=True)['status'], 'STOP_REQUESTED')
            origin.assert_not_called()
            kill.assert_called_once_with(12345, signal.SIGTERM)

    def test_stopped_status_does_not_offer_a_stale_url(self):
        with patch('scripts.g4_mac_demo.sys.platform', 'darwin'), \
             patch('scripts.g4_mac_demo.process_stamp', return_value=''), \
             patch('scripts.g4_mac_demo.check_origin') as origin:
            result = status_or_stop(self.folder, stop=True)
            self.assertEqual(result['status'], 'STOPPED')
            self.assertIsNone(result['url'])
            origin.assert_not_called()

    def test_metadata_from_another_project_is_never_signalled(self):
        metadata = json.loads(self.metadata.read_text())
        metadata['project'] = 'adc_g4_another_project'
        atomic_text(self.metadata, json.dumps(metadata))
        with patch('scripts.g4_mac_demo.sys.platform', 'darwin'), \
             patch('scripts.g4_mac_demo.process_stamp', return_value='original process'), \
             patch('scripts.g4_mac_demo.os.kill') as kill:
            self.assertEqual(status_or_stop(self.folder, stop=True)['status'], 'STOPPED')
            kill.assert_not_called()

    def test_process_group_or_malformed_pid_is_not_accepted(self):
        with patch('scripts.g4_mac_demo.process_stamp') as stamp:
            for pid in (-1, 0, True, '12345', None):
                self.assertFalse(matches_process({'pid': pid, 'process_stamp': 'original process'}))
            stamp.assert_not_called()

    def test_origin_checks_database_health_body_and_closes_connection(self):
        response = Mock(status=200)
        response.read.return_value = b'{"status":"ok","version":"1.0.0-rc.1"}'
        with patch('scripts.g4_mac_demo.HTTPConnection') as connect:
            connection = connect.return_value
            connection.getresponse.return_value = response
            check_origin('course-demo.trycloudflare.com', 18020)
        connect.assert_called_once_with('127.0.0.1', 18020, timeout=10)
        connection.request.assert_called_once_with('GET', '/health/', headers={
            'Host': 'course-demo.trycloudflare.com', 'X-Forwarded-Proto': 'https'})
        connection.close.assert_called_once()

    def test_origin_rejects_unhealthy_or_unrelated_success_responses(self):
        for status, body in ((503, b'{"status":"not_ready"}'), (200, b'not JSON'),
                             (200, b'{"status":"not_ready"}'), (200, b'[]'),
                             (200, b' ' * 4097)):
            with self.subTest(status=status, body_size=len(body)), \
                 patch('scripts.g4_mac_demo.HTTPConnection') as connect:
                response = Mock(status=status)
                response.read.return_value = body
                connect.return_value.getresponse.return_value = response
                with self.assertRaises(RuntimeError):
                    check_origin('course-demo.trycloudflare.com', 18020)
                connect.return_value.close.assert_called_once()

    def test_new_hostname_updates_private_guide_without_changing_accounts(self):
        path = self.folder / 'private/DEMO_ACCESS.md'
        original = ('Staff login: https://old-demo.trycloudflare.com/accounts/login/\n'
                    'Patient login: https://old-demo.trycloudflare.com/portal/login/\n'
                    '| synthetic_user | synthetic_password |\n'
                    '| another_user | https://old-demo.trycloudflare.com/opaque-account-text |\n'
                    'Reference: https://github.com/Zhang646967/adc-dental-clinic\n'
                    'Unrelated: https://old-demo.trycloudflare.com.example.org/\n')
        path.write_text(original)
        refresh_access(self.folder, 'new-demo.trycloudflare.com')
        expected = original.replace('Staff login: https://old-demo.trycloudflare.com/accounts/login/',
                                    'Staff login: https://new-demo.trycloudflare.com/accounts/login/').replace(
                                    'Patient login: https://old-demo.trycloudflare.com/portal/login/',
                                    'Patient login: https://new-demo.trycloudflare.com/portal/login/')
        self.assertEqual(path.read_text(), expected)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        refresh_access(self.folder, 'new-demo.trycloudflare.com')
        self.assertEqual(path.read_text(), expected)

    def test_missing_guide_is_created_privately_without_copying_passwords(self):
        credentials = self.folder / 'private/demo-credentials.txt'
        credentials.write_text('synthetic_secret_not_for_copying')
        refresh_access(self.folder, 'new-demo.trycloudflare.com')
        path = self.folder / 'private/DEMO_ACCESS.md'
        self.assertIn('https://new-demo.trycloudflare.com/accounts/login/', path.read_text())
        self.assertIn('https://new-demo.trycloudflare.com/portal/login/', path.read_text())
        self.assertNotIn('synthetic_secret_not_for_copying', path.read_text())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_hostname_cannot_change_access_guide(self):
        path = self.folder / 'private/DEMO_ACCESS.md'
        path.write_text('unchanged')
        with self.assertRaises(ValueError):
            refresh_access(self.folder, 'course-demo.trycloudflare.com/untrusted')
        self.assertEqual(path.read_text(), 'unchanged')

    def test_retired_public_tunnel_is_degraded_even_with_a_healthy_origin(self):
        atomic_text(self.folder / 'private/tunnel.log',
                    'INF Registered tunnel connection\nERR Unauthorized: Tunnel not found\n')
        with patch('scripts.g4_mac_demo.sys.platform', 'darwin'), \
             patch('scripts.g4_mac_demo.process_stamp', return_value='original process'), \
             patch('scripts.g4_mac_demo.check_origin'):
            result = status_or_stop(self.folder)
        self.assertTrue(result['origin_ready'])
        self.assertEqual(result['status'], 'DEGRADED')
        self.assertEqual(result['tunnel_registration'], 'RETIRED')
        self.assertIsNone(result['url'])

    def test_latest_registration_event_can_recover_an_older_failure(self):
        path = self.folder / 'private/tunnel.log'
        atomic_text(path, 'ERR Unauthorized: Tunnel not found\nINF Registered tunnel connection\n')
        self.assertEqual(tunnel_registration(path), 'REGISTERED')
        wait_for_registration(Mock(poll=Mock(return_value=None)), path)

    def test_start_cannot_claim_readiness_from_a_retired_registration(self):
        path = self.folder / 'private/tunnel.log'
        atomic_text(path, 'ERR Unauthorized: Tunnel not found\n')
        with self.assertRaises(RuntimeError):
            wait_for_registration(Mock(poll=Mock(return_value=None)), path)

    def test_single_connection_reconnect_is_not_reported_as_ready(self):
        path = self.folder / 'private/tunnel.log'
        atomic_text(path, 'INF Registered tunnel connection protocol=http2\nERR Connection terminated\n')
        self.assertEqual(tunnel_registration(path), 'RECONNECTING')
        with patch('scripts.g4_mac_demo.sys.platform', 'darwin'), \
             patch('scripts.g4_mac_demo.process_stamp', return_value='original process'), \
             patch('scripts.g4_mac_demo.check_origin'):
            self.assertEqual(status_or_stop(self.folder)['status'], 'DEGRADED')
        atomic_text(path, path.read_text() + 'INF Registered tunnel connection protocol=quic\n')
        self.assertEqual(tunnel_registration(path), 'REGISTERED')
        self.assertEqual(tunnel_protocol(path), 'quic')

    def test_unreviewed_protocol_is_refused_before_deployment_or_launch(self):
        with patch('scripts.g4_mac_demo.subprocess.Popen') as launch:
            with self.assertRaises(ValueError):
                start(self.folder, '/unused', protocol='unreviewed')
            launch.assert_not_called()

    def test_auto_protocol_can_register_after_the_initial_sixty_seconds(self):
        with patch('scripts.g4_mac_demo.tunnel_registration',
                   side_effect=['UNOBSERVED'] * 250 + ['REGISTERED']), \
             patch('scripts.g4_mac_demo.time.sleep') as sleep:
            wait_for_registration(Mock(poll=Mock(return_value=None)),
                                  self.folder / 'private/tunnel.log', 180)
        self.assertEqual(sleep.call_count, 250)

    def test_a_live_process_without_registration_evidence_is_degraded(self):
        atomic_text(self.folder / 'private/tunnel.log', 'INF Starting tunnel\n')
        with patch('scripts.g4_mac_demo.sys.platform', 'darwin'), \
             patch('scripts.g4_mac_demo.process_stamp', return_value='original process'), \
             patch('scripts.g4_mac_demo.check_origin'):
            result = status_or_stop(self.folder)
        self.assertEqual(result['status'], 'DEGRADED')
        self.assertEqual(result['tunnel_registration'], 'UNOBSERVED')
