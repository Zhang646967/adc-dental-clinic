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

    def test_course_mode_requires_direct_tls_and_starts_separate_runtime_worker(self):
        plan = prepare(self.folder, **self.inputs, access_mode='course-writable')
        runtime = read_env(self.folder / 'private/runtime.env')
        self.assertEqual(runtime['ADC_READ_ONLY'], '0')
        self.assertEqual(runtime['ADC_DEPLOYMENT_STAGE'], 'production')
        self.assertNotIn('ADC_MIGRATION_PASSWORD', runtime)
        self.assertFalse(plan['read_only'])
        self.assertFalse(inspect_bundle(self.folder)['read_only'])
        compose = (self.folder / 'compose.yaml').read_text()
        self.assertNotIn('profiles: [writer]', compose)
        self.assertIn('notification-worker:', compose)
        self.assertNotIn('on-failure:5', compose)
        self.assertFalse(plan['public_acceptance_executed'])

    def test_course_mode_cannot_enable_mac_tunnel_writes(self):
        with self.assertRaises(ValueError):
            prepare(self.folder, **(self.inputs | dict(
                host='course-demo.trycloudflare.com', http_port=18020,
                mode='mac_tunnel', access_mode='course-writable')))
        self.assertFalse(self.folder.exists())

    def test_access_mode_and_runtime_disagreement_is_refused(self):
        prepare(self.folder, **self.inputs, access_mode='course-writable')
        path = self.folder / 'private/runtime.env'
        path.write_text(path.read_text().replace('ADC_READ_ONLY=0', 'ADC_READ_ONLY=1'))
        with self.assertRaises(ValueError):
            inspect_bundle(self.folder)

    def test_readonly_bundle_cannot_become_writable_by_flipping_env(self):
        prepare(self.folder, **self.inputs)
        path = self.folder / 'private/runtime.env'
        path.write_text(path.read_text().replace('ADC_READ_ONLY=1', 'ADC_READ_ONLY=0'))
        with self.assertRaises(ValueError):
            inspect_bundle(self.folder)

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
        doc = {'services': {name: {} for name in ('db', 'schema', 'bootstrap', 'web', 'notification-worker', 'gateway', 'operations')},
               'networks': {'private': {'internal': True}, 'edge': {}}}
        for name in ('web', 'notification-worker', 'operations'):
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
        doc = {'services': {name: {} for name in ('db', 'schema', 'bootstrap', 'web', 'notification-worker', 'gateway', 'operations')},
               'networks': {'private': {'internal': True, 'external': True}}}
        rendered.write_text(json.dumps(doc))
        with self.assertRaises(ValueError):
            inspect_bundle(self.folder, rendered)

    def test_mac_tunnel_has_one_loopback_origin_and_no_tls_key_mount(self):
        plan = prepare(self.folder, **(self.inputs | dict(host='course-demo.trycloudflare.com',
                       http_port=18020, mode='mac_tunnel')))
        self.assertEqual(plan['ports'], [18020])
        compose = (self.folder / 'compose.yaml').read_text()
        self.assertIn('127.0.0.1:${G4_HTTP_PORT:', compose)
        self.assertNotIn('./tls:', compose)
        self.assertNotIn('}:443', compose)
        nginx = (self.folder / 'nginx.conf').read_text()
        self.assertIn("if ($http_x_forwarded_proto != 'https')", nginx)
        self.assertTrue(inspect_bundle(self.folder)['read_only'])

    def test_mac_tunnel_refuses_public_binding_original_port_and_unassigned_host(self):
        inputs = self.inputs | dict(host='course-demo.trycloudflare.com', http_port=18020, mode='mac_tunnel')
        for change in (dict(bind_ip='0.0.0.0'), dict(http_port=18000), dict(host='adc.example.com')):
            with self.subTest(change=change), self.assertRaises(ValueError):
                prepare(self.folder, **(inputs | change))
            self.assertFalse(self.folder.exists())

    def test_mac_tunnel_rendered_port_change_refused(self):
        plan = prepare(self.folder, **(self.inputs | dict(host='course-demo.trycloudflare.com',
                       http_port=18020, mode='mac_tunnel')))
        runtime = read_env(self.folder / 'private/runtime.env')
        doc = {'services': {name: {} for name in ('db', 'schema', 'bootstrap', 'web', 'notification-worker', 'gateway', 'operations')},
               'networks': {'private': {'internal': True}, 'edge': {}}}
        for name in ('web', 'notification-worker', 'operations'):
            doc['services'][name] = {'environment': runtime, 'image': plan['images']['app']}
        doc['services']['gateway']['ports'] = [{'target': 80, 'published': '18020', 'host_ip': '127.0.0.1'}]
        rendered = self.folder / 'private/rendered.json'
        rendered.write_text(json.dumps(doc))
        self.assertEqual(inspect_bundle(self.folder, rendered)['configuration_checks'], 'PASS')
        doc['services']['gateway']['ports'][0]['published'] = '18000'
        rendered.write_text(json.dumps(doc))
        with self.assertRaises(ValueError):
            inspect_bundle(self.folder, rendered)
