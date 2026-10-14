"""Offline preparation contracts; these do not prove public deployment."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts.g4_prepare import prepare, inspect_bundle, read_env


class G4PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / '.g4'
        self.inputs = dict(host='adc.g4.test', source_commit='a' * 40,
                           app_image='sha256:' + 'b' * 64,
                           db_image='postgres:17@sha256:' + 'c' * 64,
                           nginx_image='nginx:stable-alpine@sha256:' + 'd' * 64)

    def test_runtime_cannot_receive_owner_credentials_and_defaults_read_only(self):
        prepare(self.folder, **self.inputs)
        runtime = read_env(self.folder / 'private/runtime.env')
        owner = read_env(self.folder / 'private/maintenance.env')
        self.assertEqual(runtime['ADC_READ_ONLY'], '1')
        self.assertNotIn('ADC_MIGRATION_PASSWORD', runtime)
        self.assertNotEqual(runtime['POSTGRES_PASSWORD'], owner['ADC_MIGRATION_PASSWORD'])
        self.assertEqual(runtime['AI_MODE'], 'disabled')
        self.assertEqual((self.folder / 'acme/.well-known/acme-challenge').stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.folder / 'private').stat().st_mode & 0o077, 0)
        self.assertFalse(inspect_bundle(self.folder)['public_acceptance_executed'])

    def test_existing_private_state_is_never_overwritten(self):
        prepare(self.folder, **self.inputs)
        before = (self.folder / 'private/runtime.env').read_bytes()
        with self.assertRaises(ValueError):
            prepare(self.folder, **self.inputs)
        self.assertEqual((self.folder / 'private/runtime.env').read_bytes(), before)

    def test_invalid_host_and_mutable_image_create_no_output(self):
        for update in (dict(host='*'), dict(host='https://adc.g4.test'),
                       dict(app_image='adc:latest'), dict(db_image='postgres:17')):
            with self.subTest(update=update), self.assertRaises(ValueError):
                prepare(self.folder, **(self.inputs | update))
            self.assertFalse(self.folder.exists())

    def test_bad_revision_binding_and_port_collision_refused(self):
        for update in (dict(source_commit='main'), dict(http_port=443, https_port=443), dict(bind_ip='::')):
            with self.subTest(update=update), self.assertRaises(ValueError):
                prepare(self.folder, **(self.inputs | update))
            self.assertFalse(self.folder.exists())

    def test_private_permissions_and_runtime_secret_exposure_refused(self):
        prepare(self.folder, **self.inputs)
        runtime = self.folder / 'private/runtime.env'
        os.chmod(runtime, 0o644)
        with self.assertRaises(ValueError):
            inspect_bundle(self.folder)
        os.chmod(runtime, 0o600)
        runtime.write_text(runtime.read_text() + 'ADC_MIGRATION_PASSWORD=do-not-expose\n')
        with self.assertRaises(ValueError):
            inspect_bundle(self.folder)

    def test_default_binding_is_loopback_and_modified_template_refused(self):
        plan = prepare(self.folder, **self.inputs)
        self.assertEqual(plan['bind_ip'], '127.0.0.1')
        nginx = self.folder / 'nginx.conf'
        nginx.write_text(nginx.read_text() + '\n# unreviewed change\n')
        with self.assertRaises(ValueError):
            inspect_bundle(self.folder)

    def test_rendered_public_database_port_refused(self):
        plan = prepare(self.folder, **self.inputs)
        runtime = read_env(self.folder / 'private/runtime.env')
        doc = {'services': {name: {} for name in ('db', 'schema', 'bootstrap', 'web', 'notification-worker', 'gateway')},
               'networks': {'private': {'internal': True}, 'edge': {}}}
        for name in ('web', 'notification-worker'):
            doc['services'][name] = {'environment': runtime, 'image': plan['images']['app']}
        doc['services']['gateway']['ports'] = [{'target': 80, 'host_ip': '127.0.0.1'},
                                               {'target': 443, 'host_ip': '127.0.0.1'}]
        rendered = self.folder / 'private/rendered.json'
        rendered.write_text(json.dumps(doc))
        self.assertEqual(inspect_bundle(self.folder, rendered)['configuration_checks'], 'PASS')
        bad = copy.deepcopy(doc)
        bad['services']['db']['ports'] = [{'target': 5432, 'published': '5432'}]
        rendered.write_text(json.dumps(bad))
        with self.assertRaises(ValueError):
            inspect_bundle(self.folder, rendered)

    def test_rendered_external_network_refused(self):
        prepare(self.folder, **self.inputs)
        rendered = self.folder / 'private/rendered.json'
        doc = {'services': {name: {} for name in ('db', 'schema', 'bootstrap', 'web', 'notification-worker', 'gateway')},
               'networks': {'private': {'internal': True, 'external': True}}}
        rendered.write_text(json.dumps(doc))
        with self.assertRaises(ValueError):
            inspect_bundle(self.folder, rendered)
