"""Real Django public-boundary checks; catalogue reads are stubbed here."""
from types import SimpleNamespace
from unittest.mock import patch
from django.contrib.auth.models import AnonymousUser
from django.test import Client, RequestFactory, SimpleTestCase
from django.urls import resolve, reverse
from adc_core.entry_views import system_entry
from workspaces.middleware import WorkspaceMiddleware


class SystemEntryHTTPTests(SimpleTestCase):
    def setUp(self):
        self.catalogue=patch('portal.service_views.public_profiles',return_value=[])
        self.catalogue.start();self.addCleanup(self.catalogue.stop)
        self.discovery=patch('portal.service_views.discovery_data',return_value={'clinics':[],'offerings':[]})
        self.discovery.start();self.addCleanup(self.discovery.stop)

    def test_anonymous_entry_does_not_need_a_workspace_or_database(self):
        response = Client().get(reverse('system_entry'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '每一次就诊。')
        self.assertNotContains(response,'亲自核验')
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertIn("script-src 'self'", response['Content-Security-Policy'])

    def test_post_cannot_change_anything(self):
        response = Client().post(reverse('system_entry'), {'role': 'SYSADMIN', 'clinic': '1'})
        self.assertEqual(response.status_code, 405)

    def test_head_works_without_creating_a_workspace(self):
        response = Client().head(reverse('system_entry'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'')

    def test_authenticated_entry_does_not_activate_or_update_context(self):
        request = RequestFactory().get(reverse('system_entry'))
        request.user = SimpleNamespace(is_authenticated=True)
        with patch('workspaces.middleware.ensure_context', side_effect=AssertionError('No context creation is allowed')):
            response = WorkspaceMiddleware(system_entry)(request)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(hasattr(request, 'workspace'))

    def test_query_parameters_are_not_destinations_or_rendered_input(self):
        request = RequestFactory().get(reverse('system_entry'), {'next': 'https://example.invalid/', 'role': 'SYSADMIN', 'clinic': '123'})
        request.user = AnonymousUser()
        response = system_entry(request)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'example.invalid', response.content)
        self.assertNotIn(b'clinic=123', response.content)

    def test_patient_guides_do_not_intercept_clinical_workspace(self):
        self.assertEqual(resolve('/care/123/').url_name, 'care_workspace')
        self.assertEqual(resolve('/care/123/complete/').url_name, 'care_complete')
        self.assertEqual(resolve(reverse('public_service_guide', args=['CHECKUP'])).url_name,
                         'public_service_guide')
        self.assertEqual(Client().get(reverse('public_service_guide', args=['CHECKUP'])).status_code, 200)
