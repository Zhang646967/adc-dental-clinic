import json
from pathlib import Path
import tempfile
import unittest
from scripts.prepare_wechat import prepare


class WeChatPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)/'native'

    def test_local_package_is_importable_without_secrets(self):
        r = prepare(self.output, api_base='http://127.0.0.1:18000')
        self.assertFalse(r['uploaded'])
        config = json.loads((self.output/'project.config.json').read_text())
        self.assertEqual(config['appid'], 'touristappid')
        self.assertFalse(config['setting']['urlCheck'])
        self.assertTrue((self.output/'miniprogram/pages/login/index.wxml').exists())

    def test_experience_enables_domain_checks_and_has_real_appid(self):
        prepare(self.output, api_base='https://course.example.edu.cn', appid='wx0123456789abcdef', mode='experience')
        config = json.loads((self.output/'project.config.json').read_text())
        self.assertTrue(config['setting']['urlCheck'])
        self.assertEqual(config['appid'], 'wx0123456789abcdef')

    def test_existing_output_never_overwritten(self):
        self.output.mkdir(); (self.output/'keep').write_text('unchanged')
        with self.assertRaises(ValueError): prepare(self.output, api_base='http://localhost:18000')
        self.assertEqual((self.output/'keep').read_text(), 'unchanged')

    def test_credentials_and_paths_rejected(self):
        for url in ('https://name:secret@example.edu.cn','https://example.edu.cn/api/','https://example.edu.cn/?token=secret'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                prepare(self.output, api_base=url, appid='wx0123456789abcdef', mode='experience')

    def test_experience_refuses_loopback_http_and_tourist(self):
        for url, appid in [('http://127.0.0.1:18000','wx0123456789abcdef'),('https://example.edu.cn','touristappid'),('https://127.0.0.1','wx0123456789abcdef')]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                prepare(self.output, api_base=url, appid=appid, mode='experience')

    def test_local_package_refuses_remote_plain_http(self):
        with self.assertRaises(ValueError): prepare(self.output, api_base='http://192.168.1.2:18000')
