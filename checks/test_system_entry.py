"""Public-entry safety contracts. These are not database/runtime evidence."""
from html.parser import HTMLParser
from pathlib import Path
import ast
import unittest
from adc_core.entry_catalog import ENTRY_ROUTES, SCENARIOS, render_entry
from adc_core.route_manifest import named_routes

ROOT = Path(__file__).resolve().parents[1]


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.forms = []
        self.scenarios = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a':
            self.links.append(attrs.get('href', ''))
        if tag == 'form':
            self.forms.append(attrs)
        if 'data-scenario' in attrs:
            self.scenarios.append(attrs['data-scenario'])


class SystemEntryTests(unittest.TestCase):
    def setUp(self):
        self.routes = {name: path for name, path in named_routes(ROOT).items() if name in ENTRY_ROUTES}

    def test_http_destinations_are_existing_resolved_get_pages(self):
        page = Page()
        page.feed(render_entry(self.routes))
        self.assertFalse(page.forms)
        self.assertEqual(page.scenarios, [s.key for s in SCENARIOS])
        for url in page.links:
            self.assertTrue(url.startswith('#') or url in self.routes.values(), url)
            self.assertNotIn('<', url)

    def test_portable_entry_is_built_from_the_same_catalogue(self):
        expected = render_entry(self.routes, standalone=True)
        self.assertEqual((ROOT / 'START_HERE.html').read_text(encoding='utf-8'), expected)
        page = Page()
        page.feed(expected)
        for url in page.links:
            self.assertTrue(url.startswith('#') or url.startswith('http://127.0.0.1:18000/'), url)

    def test_external_redirects_and_unresolved_paths_fail_closed(self):
        for path in ('https://example.invalid/', '//example.invalid/', '/\\example.invalid/',
                     '/visits/<int:pk>/', '/accounts/login/?next=https://example.invalid/', '/x\r\nX:y'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                render_entry(dict(self.routes, login=path))

    def test_incomplete_route_map_cannot_publish_a_partial_entry(self):
        paths = dict(self.routes)
        del paths['portal_login']
        with self.assertRaises(KeyError):
            render_entry(paths)

    def test_public_catalogue_has_no_record_identifiers_or_personal_data_inputs(self):
        self.assertEqual(len(SCENARIOS), 6)
        self.assertEqual(len({s.key for s in SCENARIOS}), 6)
        for scenario in SCENARIOS:
            self.assertTrue(scenario.expected and scenario.exception)
            self.assertTrue(all(step.role in scenario.roles for step in scenario.steps))
        page = Page()
        page.feed(render_entry(self.routes))
        self.assertFalse(page.forms)
        self.assertNotIn('demo-credentials.txt', render_entry(self.routes))

    def test_public_routes_are_explicit_customer_read_pages_and_existing_auth_endpoints(self):
        tree = ast.parse((ROOT / 'workspaces/middleware.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'PUBLIC' for t in n.targets))
        self.assertEqual(ast.literal_eval(node.value), {'system_entry','public_home','public_services',
            'public_service_detail','public_service_guide','public_clinics','login','portal_login','logout',
            'health','mini_session','mini_login','mini_logout','mini_public_discovery','mini_public_service'})

    def test_renderer_has_no_framework_or_business_service_imports(self):
        tree = ast.parse((ROOT / 'adc_core/entry_catalog.py').read_text())
        imports = {n.module.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(imports, {'dataclasses','html','pathlib','string'})

    def test_http_assets_obey_existing_no_inline_script_policy(self):
        html = render_entry(self.routes)
        self.assertNotIn('<style>', html)
        self.assertNotIn('<script defer>', html)
        self.assertIn('src="/static/system_entry.js"', html)
        self.assertIn('href="/static/system_entry.css"', html)


if __name__ == '__main__':
    unittest.main()
