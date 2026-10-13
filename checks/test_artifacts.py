"""Static packaging checks. Passing does not mean ORM or SQL executes."""
import ast
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
APPS = ("registry", "accounts", "patients", "scheduling", "care", "finance")

class ArtifactTests(unittest.TestCase):
    def test_all_python_files_parse(self):
        for p in ROOT.rglob("*.py"):
            if ".runtime" not in p.parts:
                with self.subTest(file=str(p.relative_to(ROOT))): ast.parse(p.read_text(encoding="utf-8"))
    def test_twenty_models_mapped(self):
        m=json.loads((ROOT/"docs/schema_manifest.json").read_text())
        self.assertEqual(len(m),20)
        original=json.loads((ROOT/"docs/reference/schema_model_v0.2.json").read_text())
        self.assertEqual({x["model"] for x in m},{x["name"] for x in original})
    def test_every_model_has_create_migration(self):
        m=json.loads((ROOT/"docs/schema_manifest.json").read_text())
        for app in APPS:
            t=ast.parse((ROOT/app/"migrations/0001_initial.py").read_text())
            created={next(k.value.value for k in n.keywords if k.arg=="name") for n in ast.walk(t)
                     if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="CreateModel"}
            self.assertEqual(created,{x["model"] for x in m if x["app"]==app})
    def test_every_declared_field_in_migration(self):
        m=json.loads((ROOT/"docs/schema_manifest.json").read_text())
        for app in APPS:
            t=ast.parse((ROOT/app/"migrations/0001_initial.py").read_text())
            declared={}
            for n in ast.walk(t):
                if not isinstance(n,ast.Call) or not isinstance(n.func,ast.Attribute): continue
                kw={x.arg:x.value for x in n.keywords}
                if n.func.attr=="CreateModel":
                    name=kw['name'].value.lower()
                    declared[name]={x.elts[0].value for x in kw['fields'].elts}
                if n.func.attr=="AddField":
                    declared.setdefault(kw['model_name'].value,set()).add(kw['name'].value)
            for obj in [x for x in m if x['app']==app]:
                self.assertTrue({x['name'] for x in obj['fields']}<=declared[obj['model'].lower()])
    def test_sql_snapshot_matches_migration(self):
        t=ast.parse((ROOT/"care/migrations/0002_database_guards.py").read_text())
        sql=next(ast.literal_eval(n.value) for n in t.body if isinstance(n,ast.Assign) and n.targets[0].id=='SQL')
        self.assertEqual(sql.strip(),(ROOT/"docs/sql/0002_database_guards.sql").read_text().strip())
    def test_named_database_constraints_unique(self):
        names=[]
        for app in APPS:
            t=ast.parse((ROOT/app/"models.py").read_text())
            for n in ast.walk(t):
                if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr.endswith("Constraint") or isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='ExclusionConstraint':
                    names.extend(x.value.value for x in n.keywords if x.arg=='name')
        self.assertEqual(len(names),len(set(names)))
        self.assertTrue(all(len(n)<=63 for n in names))
    def test_postgres_required_and_no_sqlite_fallback(self):
        settings=(ROOT/'config/settings/base.py').read_text()
        self.assertIn('django.db.backends.postgresql',settings)
        self.assertNotIn('django.db.backends.sqlite3',settings)
        self.assertIn('BtreeGistExtension', (ROOT/'registry/migrations/0001_initial.py').read_text())
    def test_template_urls_are_defined(self):
        from adc_core.route_manifest import named_routes
        names=set(named_routes(ROOT))
        for f in (ROOT/'templates').rglob('*.html'):
            used=set(re.findall(r"\{%\s*url\s+['\"]([^'\"]+)",f.read_text()))
            self.assertTrue(used<=names,(str(f),used-names))
    def test_compose_ports_are_loopback_only(self):
        text=(ROOT/'compose.yaml').read_text()
        self.assertIn('127.0.0.1:8000:8000',text)
        self.assertIn('127.0.0.1:54329:5432',text)
    def test_no_fixed_demo_password_in_seed(self):
        text=(ROOT/'adc_core/management/commands/seed_demo.py').read_text()
        self.assertIn('secrets.token_urlsafe',text)
        self.assertNotIn('admin123',text)
    def test_still_unfinished_modules_have_no_write_urls(self):
        text=(ROOT/'config/urls.py').read_text()
        for feature in ('payments/', 'refunds/', 'tax-invoices/'):
            self.assertNotIn(feature,text)
