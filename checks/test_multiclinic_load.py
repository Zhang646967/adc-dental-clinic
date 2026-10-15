"""Host-side safety checks for the synthetic multi-clinic workload launcher."""
from pathlib import Path
import json,tempfile,unittest
from unittest.mock import patch,Mock
from scripts.multiclinic_load import Client,checked_target,Forms,READS,continuous_window

class MultiClinicLoadSafety(unittest.TestCase):
    def test_external_redirect_never_followed(self):
        c=Client(18050);c.request=Mock(return_value=(302,'https://outside.invalid/',b''))
        with self.assertRaises(ValueError):c.follow('GET','/accounts/login/')
        self.assertEqual(c.request.call_count,1)
    def test_absolute_and_scheme_relative_routes_rejected(self):
        c=Client(18050)
        for route in ('https://outside.invalid/','//outside.invalid/','patients/'):
            with self.assertRaises(ValueError):c.request('GET',route)
        self.assertIsNone(c.connection)
    def test_ambiguous_signed_forms_refused(self):
        c=Client(18050);body=b'<form><input name="workspace_token"></form>'*2
        c.request=Mock(return_value=(200,None,body))
        with self.assertRaises(ValueError):c.form('/patients/new/',('workspace_token',))
    def test_note_form_is_selected_by_action_not_logout_token(self):
        c=Client(18050);body=b'<form><input name="workspace_token" value="logout"></form><form><input name="workspace_token" value="note"><input name="expected_version" value="2"><input name="action" value="note"></form>'
        c.request=Mock(return_value=(200,None,body))
        self.assertEqual(c.form('/care/1/',('workspace_token','expected_version'),action='note')['workspace_token'],'note')
    def test_live_mac_ports_refused_before_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'.rc').mkdir();(root/'.rc/project.txt').write_text('adc_rc1_000000000000')
            for port in (18000,18020,80,443,19000):
                with patch('scripts.multiclinic_load.subprocess.check_output') as call,self.assertRaises(ValueError):checked_target(root,'adc_rc1_000000000000',port,'docker')
                call.assert_not_called()
    def test_wrong_project_refused_before_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'.rc').mkdir();(root/'.rc/project.txt').write_text('adc_rc1_000000000000')
            with patch('scripts.multiclinic_load.subprocess.check_output') as call,self.assertRaises(ValueError):checked_target(root,'adc_rc1_111111111111',18050,'docker')
            call.assert_not_called()
    def test_remote_docker_is_never_a_capacity_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'.rc').mkdir();(root/'.rc/project.txt').write_text('adc_rc1_000000000000')
            with patch('scripts.multiclinic_load.subprocess.check_output',return_value='tcp://external.invalid:2376'),self.assertRaises(ValueError):checked_target(root,'adc_rc1_000000000000',18050,'docker')
    def test_unmarked_local_project_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'.rc').mkdir();(root/'.rc/project.txt').write_text('adc_rc1_000000000000')
            rows=[{'Config':{'Labels':{'com.docker.compose.service':name},'Env':[]}} for name in ('db','web','gateway','notification-worker')]
            with patch('scripts.multiclinic_load.subprocess.check_output',side_effect=['unix:///local.sock','a b c d',json.dumps(rows).encode()]),self.assertRaises(ValueError):checked_target(root,'adc_rc1_000000000000',18050,'docker')

    def test_sleep_gap_cannot_pass_with_good_monotonic_latency(self):
        self.assertFalse(continuous_window(1800,2640,844))
        self.assertFalse(continuous_window(1800,2640,4))
    def test_long_arrival_gap_rejected_even_without_clock_difference(self):
        self.assertFalse(continuous_window(1800,1800,15))
    def test_normal_scheduled_waves_and_clock_tolerance(self):
        self.assertTrue(continuous_window(1800.1,1800.12,4.2))
    def test_backward_wall_clock_step_does_not_certify_window(self):
        self.assertFalse(continuous_window(1800,1700,4))

    def test_seed_empty_guard_survives_optimized_python(self):
        import subprocess,sys
        root=Path(__file__).resolve().parents[1]
        for value,expected in [('False',1),('True',0)]:
            result=subprocess.run([sys.executable,'-O','-c','from scripts.multiclinic_seed import require_empty; require_empty('+value+')'],cwd=root,capture_output=True,text=True)
            self.assertEqual(result.returncode,expected)
            if expected:self.assertIn('existing data retained',result.stderr)
