"""Real Django entry checks; no business database is needed for these cases."""
from types import SimpleNamespace
from unittest.mock import patch
from django.test import Client, RequestFactory, SimpleTestCase
from django.urls import reverse
from adc_core.entry_views import system_entry
from workspaces.middleware import WorkspaceMiddleware


class SystemEntryHTTPTests(SimpleTestCase):
    def test_anonymous_entry_does_not_need_a_workspace_or_database(self):
        response = Client().get(reverse('system_entry'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '六条路线，亲自核验')
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
        response = system_entry(request)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'example.invalid', response.content)
        self.assertNotIn(b'clinic=123', response.content)
