import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from config.env import read_secret
from scripts.rc_config import prepare, validate
from scripts.wx1_platform import apply_rc


class WechatSecretFileTests(unittest.TestCase):
    def test_legacy_optional_value_remains_compatible(self):
        with patch.dict(os.environ, {'EXAMPLE_SECRET':'old-value'}, clear=True):
            self.assertEqual(read_secret('EXAMPLE_SECRET'),'old-value')

    def test_file_value_is_not_exported_into_process_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'secret';p.write_text('file-only-value\n')
            with patch.dict(os.environ, {'EXAMPLE_SECRET_FILE':str(p)}, clear=True):
                self.assertEqual(read_secret('EXAMPLE_SECRET'),'file-only-value')
                self.assertNotIn('EXAMPLE_SECRET',os.environ)

    def test_file_takes_precedence_and_bad_file_never_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'secret';p.write_text('new-value')
            with patch.dict(os.environ, {'EXAMPLE_SECRET_FILE':str(p),'EXAMPLE_SECRET':'old-value'}, clear=True):
                self.assertEqual(read_secret('EXAMPLE_SECRET'),'new-value')
                p.unlink()
                with self.assertRaisesRegex(ValueError,'EXAMPLE_SECRET_FILE'):
                    read_secret('EXAMPLE_SECRET')

    def test_invalid_file_does_not_disclose_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'secret'
            for value in ['', 'PRIVATE_SECRET\nSECOND_VALUE', 'x'*4097]:
                p.write_text(value)
                with patch.dict(os.environ, {'EXAMPLE_SECRET_FILE':str(p)}, clear=True):
                    with self.assertRaises(ValueError) as error:read_secret('EXAMPLE_SECRET')
                    self.assertNotIn('PRIVATE_SECRET',str(error.exception))

    def test_apply_rc_uses_dedicated_read_only_file_and_keeps_other_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepare(root);before=(root/'.rc/compose.env').read_text()
            values={'ADC_PATIENT_AUTH_MODE':'live','ADC_PATIENT_IDENTITY_PROVIDER':'disabled',
                    'ADC_WECHAT_MINI_APP_ID':'wx'+'1'*16,'ADC_WECHAT_MINI_APP_SECRET':'synthetic-test-secret'}
            result=apply_rc(values,root);after=(root/'.rc/compose.env').read_text()
            self.assertEqual(result['secret_storage'],'WEB_READ_ONLY_FILE')
            self.assertIn('RC_WECHAT_MINI_APP_SECRET=\n',after)
            self.assertIn('RC_WECHAT_MINI_APP_SECRET_FILE=/run/adc-wechat/mini-app-secret',after)
            self.assertNotIn('synthetic-test-secret',after)
            self.assertEqual((root/'.rc/private/wechat/mini-app-secret').read_text(),'synthetic-test-secret\n')
            self.assertEqual((root/'.rc/private').stat().st_mode&0o777,0o700)
            self.assertEqual(Path(result['backup_file']).read_text(),before)
            validate(root)
            compose=json.loads((Path(__file__).resolve().parents[1]/'compose.rc.yaml').read_text())
            self.assertTrue(any(isinstance(v,dict) and v.get('target')=='/run/adc-wechat' and v['read_only'] for v in compose['services']['web']['volumes']))
            for name in ['schema','notification-worker','operations','bootstrap']:
                self.assertNotIn('ADC_WECHAT_MINI_APP_SECRET_FILE',compose['services'][name]['environment'])

    def test_private_parent_exposure_is_rejected_before_writing_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepare(root);(root/'.rc/private').chmod(0o755)
            with self.assertRaises(ValueError):apply_rc({'ADC_PATIENT_AUTH_MODE':'live','ADC_PATIENT_IDENTITY_PROVIDER':'disabled','ADC_WECHAT_MINI_APP_ID':'wx'+'1'*16,'ADC_WECHAT_MINI_APP_SECRET':'synthetic-test-secret'},root)
            self.assertFalse((root/'.rc/private/wechat/mini-app-secret').exists())
