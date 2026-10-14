"""Reject readonly targets, duplicate identities and arbitrary HTTP destinations."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from scripts.g4_prepare import prepare
from scripts.g4_course_load import Client, load_plan, read_actors


class WritableLoadSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bundle = Path(self.tmp.name) / '.g4'
        self.inputs = dict(host='course.adc.test', source_commit='a' * 40,
                           app_image='sha256:' + 'b' * 64,
                           db_image='postgres:17@sha256:' + 'c' * 64,
                           nginx_image='nginx:stable-alpine@sha256:' + 'd' * 64)

    def test_readonly_course_target_never_accepts_writes(self):
        prepare(self.bundle, **self.inputs)
        with self.assertRaises(ValueError):
            load_plan(self.bundle, 'public', None)

    def test_public_load_cannot_use_a_custom_ca_or_nonstandard_ports(self):
        prepare(self.bundle, **self.inputs, access_mode='course-writable', https_port=18443)
        with self.assertRaises(ValueError):
            load_plan(self.bundle, 'public', None)
        with self.assertRaises(ValueError):
            load_plan(self.bundle, 'public', 'fake-ca')

    def test_duplicate_users_cannot_claim_ten_distinct_accounts(self):
        plan = prepare(self.bundle, **self.inputs, access_mode='course-writable')
        path = self.bundle / 'private/load-actors.json'
        doc = dict(project=plan['project'], host=plan['host'], run_id='1' * 12,
                   actors=[dict(username='same', clinic='1', grant_confirmed=True)] * 10)
        path.write_text(json.dumps(doc))
        os.chmod(path, 0o600)
        with self.assertRaises(ValueError):
            read_actors(path, plan)

    def test_arbitrary_url_query_and_business_routes_are_refused_before_network(self):
        client = Client({'host': 'course.adc.test', 'ports': [80, 443]}, 'public')
        for route in ('https://other.test/', '/patients/new/?redirect=evil', '/finance/', '//other.test/'):
            with self.subTest(route=route), self.assertRaises(ValueError):
                client.request('POST', route, {'secret': 'must-not-be-sent'})
