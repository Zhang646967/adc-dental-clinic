"""Configured proxy routing never disables target certificate verification."""
import ssl
import unittest
from unittest.mock import patch

from scripts.g4_https_probe import TargetHTTPSConnection


class TargetTransportTests(unittest.TestCase):
    def test_configured_http_proxy_keeps_original_tls_tunnel_host(self):
        with patch('scripts.g4_https_probe.getproxies', return_value={'https': 'http://127.0.0.1:7890'}), \
             patch('scripts.g4_https_probe.proxy_bypass', return_value=False):
            conn = TargetHTTPSConnection('demo.trycloudflare.com', 443)
        self.assertTrue(conn.via_configured_proxy)
        self.assertEqual(conn.host, '127.0.0.1')
        self.assertEqual(conn._tunnel_host, 'demo.trycloudflare.com')
        self.assertEqual(conn._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(conn._context.check_hostname)

    def test_explicit_reviewed_connect_ip_does_not_use_a_proxy(self):
        with patch('scripts.g4_https_probe.getproxies') as proxies:
            conn = TargetHTTPSConnection('rehearsal.test', 443, connect_ip='127.0.0.1')
        proxies.assert_not_called()
        self.assertFalse(conn.via_configured_proxy)
        self.assertEqual(conn.host, 'rehearsal.test')
        self.assertEqual(conn.connect_ip, '127.0.0.1')

    def test_proxy_authentication_is_only_on_connect_headers(self):
        with patch('scripts.g4_https_probe.getproxies', return_value={'https': 'http://fixture-user:fixture-password@127.0.0.1:7890'}), \
             patch('scripts.g4_https_probe.proxy_bypass', return_value=False):
            conn = TargetHTTPSConnection('demo.trycloudflare.com', 443)
        self.assertIn('Proxy-Authorization', conn._tunnel_headers)
        self.assertNotIn('fixture-password', repr(conn))

    def test_unsupported_proxy_cannot_silently_fall_back_to_direct_network(self):
        with patch('scripts.g4_https_probe.getproxies', return_value={'https': 'socks5://127.0.0.1:7890'}), \
             patch('scripts.g4_https_probe.proxy_bypass', return_value=False):
            with self.assertRaisesRegex(ValueError, 'no direct fallback'):
                TargetHTTPSConnection('demo.trycloudflare.com', 443)
