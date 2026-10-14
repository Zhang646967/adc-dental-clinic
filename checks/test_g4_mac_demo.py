"""Process-identity safeguards; no tunnel, Docker or OS signal is executed."""
import json
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch

from scripts.g4_prepare import prepare
from scripts.g4_mac_demo import atomic_text, start, status_or_stop


class MacDemoProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / '.g4'
        prepare(self.folder, host='course-demo.trycloudflare.com', source_commit='a' * 40,
                app_image='sha256:' + 'b' * 64, db_image='postgres:17@sha256:' + 'c' * 64,
                nginx_image='nginx:stable-alpine@sha256:' + 'd' * 64, http_port=18020, mode='mac_tunnel')
        self.metadata = self.folder / 'private/tunnel.json'
        atomic_text(self.metadata, json.dumps({'pid': 12345, 'process_stamp': 'original process',
                                              'url': 'https://course-demo.trycloudflare.com'}))

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
