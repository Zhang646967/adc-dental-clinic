"""Reject readonly targets, duplicate identities and arbitrary HTTP destinations."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from scripts.g4_prepare import prepare
from scripts.g4_course_load import Client, load_plan, read_actors, actor_index_for, patient_submission


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

    def test_patient_form_selection_excludes_signed_logout_form(self):
        client = Client({'host': 'course.adc.test', 'ports': [80, 443]}, 'public')
        client.request = Mock(return_value=(200, None, b'<form action="/accounts/logout/">'
            b'<input name="csrfmiddlewaretoken" value="logout"><input name="workspace_token" value="logout"></form>'
            b'<form method="post"><input name="csrfmiddlewaretoken" value="patient">'
            b'<input name="workspace_token" value="patient"><input name="name"><input name="date_of_birth"></form>'))
        fields = client.form('/patients/new/', ('csrfmiddlewaretoken', 'workspace_token', 'name', 'date_of_birth'))
        self.assertEqual(fields['workspace_token'], 'patient')

    def test_unknown_allergy_submission_does_not_include_unchecked_checkboxes(self):
        result = patient_submission({'csrfmiddlewaretoken':'signed', 'workspace_token':'signed',
                                     'allergies':'2', 'untrusted':'discard'}, '1', 'Synthetic')
        self.assertEqual(result['allergy_status'], 'UNKNOWN')
        self.assertNotIn('allergies', result)
        self.assertNotIn('untrusted', result)

    def test_ten_users_all_receive_reads_and_writes_at_the_fixed_ratio(self):
        selected = [actor_index_for(i) for i in range(50)]
        self.assertEqual(sum(write for _, write in selected), 10)
        self.assertEqual({actor for actor, write in selected if write}, set(range(10)))
        self.assertEqual({actor for actor, write in selected if not write}, set(range(10)))
