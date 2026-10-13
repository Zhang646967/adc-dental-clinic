"""RC host/configuration contracts; not Docker or database execution."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json,unittest
from scripts.rc_config import prepare,validate
R=Path(__file__).resolve().parents[1]
class ReleaseContractTests(unittest.TestCase):
 def test_fresh_private_configuration(self):
  with TemporaryDirectory() as d:
   name=prepare(d);self.assertEqual(name,validate(d));self.assertTrue(name.startswith('adc_rc1_'))
 def test_no_existing_env_overwrite(self):
  with TemporaryDirectory() as d:
   p=Path(d)/'.env';p.write_text('unchanged')
   with self.assertRaises(ValueError):prepare(d)
   self.assertEqual(p.read_text(),'unchanged')
 def test_no_rc_secret_reset(self):
  with TemporaryDirectory() as d:
   prepare(d);p=Path(d)/'.rc/compose.env';before=p.read_bytes()
   with self.assertRaises(ValueError):prepare(d)
   self.assertEqual(p.read_bytes(),before)
 def test_reject_bad_port(self):
  for port in (0,80,65536):
   with TemporaryDirectory() as d,self.assertRaises(ValueError):prepare(d,port)
 def test_reject_project_injection(self):
  with TemporaryDirectory() as d:
   prepare(d);(Path(d)/'.rc/project.txt').write_text('old_project & del x')
   with self.assertRaises(ValueError):validate(d)
 def test_no_private_data_in_build_or_git(self):
  for n in ('.dockerignore','.gitignore'):self.assertIn('.rc/',(R/n).read_text())
 def config(self):return json.loads((R/'compose.rc.yaml').read_text())
 def test_database_no_published_port(self):self.assertNotIn('ports',self.config()['services']['db'])
 def test_gateway_loopback_only(self):
  p=self.config()['services']['gateway']['ports'];self.assertTrue(all(x.startswith('127.0.0.1:') for x in p))
 def test_web_and_worker_wait_schema_completion(self):
  for name in ('web','notification-worker'):
   self.assertEqual(self.config()['services'][name]['depends_on']['schema']['condition'],'service_completed_successfully')
 def test_no_external_volumes(self):
  self.assertTrue(all(not x.get('external') for x in self.config()['volumes'].values()))
 def test_internal_network(self):self.assertTrue(self.config()['networks']['private']['internal'])
 def test_only_gateway_has_host_facing_network(self):
  services=self.config()['services']
  self.assertIn('loopback',services['gateway']['networks'])
  for name in ('db','schema','web','notification-worker'):
   self.assertEqual(services[name]['networks'],['private'])
 def test_host_facing_network_defaults_to_loopback(self):
  opts=self.config()['networks']['loopback']['driver_opts']
  self.assertEqual(opts['com.docker.network.bridge.host_binding_ipv4'],'127.0.0.1')
 def test_no_ai_keys_in_rc_environment(self):
  env=self.config()['services']['web']['environment']
  self.assertEqual(env['AI_MODE'],'demo');self.assertEqual(env['AI_API_KEY'],'');self.assertEqual(env['OPENAI_API_KEY'],'')
 def test_cmd_no_source_project_no_volume_delete(self):
  s=(R/'RC_WINDOWS.cmd').read_text();self.assertNotIn('down -v',s);self.assertNotIn('volume rm',s)
  self.assertIn('-f compose.rc.yaml',s);self.assertNotIn('-f compose.yaml',s)
 def test_import_does_not_seed(self):
  s=(R/'RC_WINDOWS.cmd').read_text().split(':importcopy\n',1)[1].split('\n:fresh\n',1)[0]
  self.assertNotIn('seed_',s);self.assertNotIn('bootstrap_release',s)
  self.assertIn('--single-transaction --exit-on-error',s);self.assertIn('before-upgrade',s);self.assertIn('fc /b',s)
 def test_start_does_not_seed(self):
  s=(R/'RC_WINDOWS.cmd').read_text().split(':start\n',1)[1].split(':stop\n',1)[0]
  self.assertNotIn('seed_',s);self.assertIn('if not exist .rc\\READY',s)
 def test_old_upgrade_paths_stop(self):
  for n in ('UPGRADE_WINDOWS.cmd','UPGRADE_V09_WINDOWS.cmd'):
   s=(R/n).read_text();self.assertIn('exit /b 2',s);self.assertNotIn('migrate',s)
 def test_isolated_gate_requires_test_database(self):
  s=(R/'scripts/integration_gate.py').read_text();self.assertIn("os.environ.get('POSTGRES_DB') != 'adc_verify'",s)
 def test_readonly_worker_exits_before_dispatch(self):
  s=(R/'scripts/rc_worker.py').read_text();self.assertLess(s.index('ADC_READ_ONLY'),s.index('os.execv('))
 def test_global_templates_readonly_and_error_support(self):
  for n in ('base.html','portal/base.html'):
   s=(R/'templates'/n).read_text();self.assertIn('release/read_only.html',s);self.assertIn('release-ui.js',s)
 def test_original_form_business_controls_preserved(self):
  s=(R/'templates/form.html').read_text();self.assertIn('{% csrf_token %}',s);self.assertIn('{% workspace_token %}',s);self.assertIn('form.non_field_errors',s)
