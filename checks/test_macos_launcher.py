"""Exercise host isolation and instance lifecycle without starting Docker."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
FAKE_DOCKER = r'''
import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
with open(os.environ['MOCK_LOG'], 'a') as out:
    out.write(json.dumps({'args':args,'compose_file':os.environ.get('COMPOSE_FILE'),
                         'rc_project':os.environ.get('RC_PROJECT')})+'\n')
if args[:1] == ['--context']: args = args[2:]
if args[:2] == ['context','show']: print('desktop-linux')
elif args[:2] == ['context','inspect']: print(os.environ.get('MOCK_ENDPOINT','unix:///local/docker.sock'))
elif args[:1] == ['info']: print('linux')
elif args[:1] == ['run']:
    root = pathlib.Path(os.environ['MOCK_ROOT'])
    action = args[args.index('scripts/rc_config.py')+1]
    sys.exit(subprocess.call([sys.executable,str(root/'scripts/rc_config.py'),action,'--root',str(root)]))
elif args[:2] == ['volume','ls']:
    if os.environ.get('MOCK_VOLUME_ERROR'): sys.exit(7)
    if os.environ.get('MOCK_VOLUME_EXISTS'): print('existing_rc_data')
elif args[:1] == ['compose']:
    if args[-3:] == ['run','--rm','schema'] and os.environ.get('MOCK_SCHEMA_ERROR'): sys.exit(7)
    if args[-1:] == ['bootstrap_release_demo']: print('mock-credentials-only')
else: sys.exit(9)
'''

class MacLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'course folder'
        (self.root / 'scripts').mkdir(parents=True)
        shutil.copyfile(ROOT / 'RC_MACOS.sh', self.root / 'RC_MACOS.sh')
        shutil.copyfile(ROOT / 'scripts/rc_config.py', self.root / 'scripts/rc_config.py')
        (self.root / 'VERIFY_ISOLATED_MAC.sh').write_text('printf "verify:%s\\n" "$DOCKER_CONTEXT"\n')
        self.binary = Path(self.temp.name) / 'docker'
        self.binary.write_text('#!' + sys.executable + '\n' + FAKE_DOCKER)
        self.binary.chmod(0o755)
        self.log = Path(self.temp.name) / 'docker.jsonl'
        self.env = {**os.environ, 'ADC_DOCKER_BIN': str(self.binary),
                    'MOCK_LOG': str(self.log), 'MOCK_ROOT': str(self.root)}
        for key in ('DOCKER_HOST','DOCKER_CONTEXT','MOCK_ENDPOINT','MOCK_VOLUME_EXISTS',
                    'MOCK_VOLUME_ERROR','MOCK_SCHEMA_ERROR'):
            self.env.pop(key, None)

    def invoke(self, *args, **overrides):
        return subprocess.run(['/bin/bash', str(self.root / 'RC_MACOS.sh'), *args],
                              env={**self.env, **overrides}, capture_output=True, text=True)

    def calls(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

    def prepare(self):
        self.assertEqual(self.invoke('prepare').returncode, 0)
        self.log.write_text('')

    def test_missing_demo_acknowledgement_does_not_call_docker(self):
        self.assertEqual(self.invoke('new-demo').returncode, 2)
        self.assertEqual(self.calls(), [])

    def test_remote_docker_host_is_rejected_before_access(self):
        self.assertEqual(self.invoke('prepare', DOCKER_HOST='tcp://remote:2375').returncode, 2)
        self.assertEqual(self.calls(), [])

    def test_remote_context_cannot_create_resources(self):
        self.assertEqual(self.invoke('prepare', MOCK_ENDPOINT='tcp://remote:2376').returncode, 2)
        self.assertFalse(any(x['args'][0] in ('run','compose') for x in self.calls()))

    def test_ambient_compose_and_rc_values_are_removed(self):
        result = self.invoke('prepare', COMPOSE_FILE='/wrong.yaml', RC_PROJECT='wrong')
        self.assertEqual(result.returncode, 0)
        runs = [x for x in self.calls() if 'run' in x['args']]
        self.assertTrue(runs)
        self.assertTrue(all(x['compose_file'] is None and x['rc_project'] is None for x in runs))

    def test_existing_data_volume_is_preserved(self):
        self.prepare()
        result = self.invoke('new-demo', '--synthetic-empty-only', MOCK_VOLUME_EXISTS='1')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(any('compose' in x['args'] for x in self.calls()))
        self.assertFalse((self.root / '.rc/READY').exists())

    def test_failed_volume_query_does_not_assume_an_empty_database(self):
        self.prepare()
        self.assertNotEqual(self.invoke('new-demo', '--synthetic-empty-only', MOCK_VOLUME_ERROR='1').returncode, 0)
        self.assertFalse(any('compose' in x['args'] for x in self.calls()))

    def test_successful_new_demo_waits_for_db_and_keeps_credentials_private(self):
        self.prepare()
        self.assertEqual(self.invoke('new-demo', '--synthetic-empty-only').returncode, 0)
        commands = [x['args'] for x in self.calls() if 'compose' in x['args']]
        self.assertTrue(any(x[-4:] == ['up','-d','--wait','db'] for x in commands))
        self.assertEqual((self.root / '.rc/READY').read_text().strip(), 'synthetic-demo')
        self.assertEqual((self.root / '.rc/private/demo-credentials.txt').stat().st_mode & 0o777, 0o600)

    def test_schema_failure_prevents_seeding_and_ready_marker(self):
        self.prepare()
        self.assertNotEqual(self.invoke('new-demo', '--synthetic-empty-only', MOCK_SCHEMA_ERROR='1').returncode, 0)
        self.assertFalse(any('bootstrap_release_demo' in x['args'] for x in self.calls()))
        self.assertFalse((self.root / '.rc/READY').exists())

    def test_start_does_not_seed_uninitialized_database(self):
        self.prepare()
        self.assertEqual(self.invoke('start').returncode, 2)
        self.assertFalse(any('compose' in x['args'] for x in self.calls()))

    def test_start_orders_schema_before_web_worker_and_never_seeds(self):
        self.prepare()
        (self.root / '.rc/READY').write_text('synthetic-demo\n')
        self.assertEqual(self.invoke('start').returncode, 0)
        commands = [x['args'] for x in self.calls() if 'compose' in x['args']]
        schema = next(i for i,x in enumerate(commands) if x[-3:] == ['run','--rm','schema'])
        start = next(i for i,x in enumerate(commands) if x[-5:] == ['up','-d','web','gateway','notification-worker'])
        self.assertLess(schema, start)
        self.assertFalse(any('bootstrap_release_demo' in x for x in commands))

    def test_stop_preserves_database_volumes(self):
        self.prepare()
        self.assertEqual(self.invoke('stop').returncode, 0)
        commands = [x['args'] for x in self.calls() if 'compose' in x['args']]
        self.assertEqual(commands[-1][-5:], ['stop','gateway','web','notification-worker','db'])
        self.assertFalse(any('down' in x or '--volumes' in x for x in commands))

    def test_verify_delegates_with_the_selected_local_context(self):
        self.assertIn('verify:desktop-linux', self.invoke('verify').stdout)
