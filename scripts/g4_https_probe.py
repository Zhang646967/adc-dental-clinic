"""Read-only target HTTPS probe. Does not log in, write data, or approve G4.

Uses normal certificate/hostname verification. --connect-ip supports a reviewed
pre-DNS-cutover target while retaining domain SNI/Host. --ca-file is for a local
rehearsal/private CA only and is explicitly distinguished from public trust.
"""
import argparse
import base64
from http.client import HTTPConnection, HTTPSConnection
from http.cookies import SimpleCookie
import ipaddress
import json
import re
import socket
import ssl
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, getproxies, proxy_bypass


class TargetHTTPSConnection(HTTPSConnection):
    def __init__(self, host, port, *, connect_ip=None, context=None, timeout=10):
        proxy = None if connect_ip or proxy_bypass(host) else getproxies().get('https')
        self.via_configured_proxy = bool(proxy)
        if proxy:
            parsed = urlsplit(proxy)
            if parsed.scheme != 'http' or not parsed.hostname or parsed.query or parsed.fragment:
                raise ValueError('Configured proxy transport is unsupported; no direct fallback.')
            super().__init__(parsed.hostname, parsed.port or 80, timeout=timeout, context=context)
            headers = {}
            if parsed.username is not None:
                auth = unquote(parsed.username) + ':' + unquote(parsed.password or '')
                headers['Proxy-Authorization'] = 'Basic ' + base64.b64encode(auth.encode()).decode()
            self.set_tunnel(host, port, headers)
        else:
            super().__init__(host, port, timeout=timeout, context=context)
        self.connect_ip = connect_ip

    def connect(self):
        if self.via_configured_proxy:
            # HTTPSConnection verifies the original tunnel hostname after CONNECT.
            # Proxy credentials remain on CONNECT, outside application requests.
            return super().connect()
        connection = socket.create_connection((self.connect_ip or self.host, self.port), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(connection, server_hostname=self.host)
        except Exception:
            connection.close()
            raise


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def probe(host, *, connect_ip=None, http_port=80, https_port=443, ca_file=None):
    if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', host):
        raise ValueError('Use one DNS hostname, without URL/path/wildcard.')
    if connect_ip:
        ipaddress.ip_address(connect_ip)
    context = ssl.create_default_context(cafile=ca_file)
    results = []

    def get(path, extra_headers=None):
        connection = TargetHTTPSConnection(host, https_port, connect_ip=connect_ip, context=context)
        try:
            connection.request('GET', path, headers={'Host': host} | (extra_headers or {}))
            response = connection.getresponse()
            status, headers = response.status, response.getheaders()
            response.read(1024 * 1024)
            return status, headers
        finally:
            connection.close()

    plain = HTTPConnection(connect_ip, http_port, timeout=10) if connect_ip else None
    try:
        if plain:
            plain.request('GET', '/accounts/login/', headers={'Host': host})
            response = plain.getresponse()
        else:
            request = Request('http://' + host + ':' + str(http_port) + '/accounts/login/', headers={'Host': host})
            try:
                response = build_opener(NoRedirect).open(request, timeout=10)
            except HTTPError as error:
                response = error  # Preserve the actual redirect/status, never follow it.
        redirect = response.getheader('Location')
        results.append({'check': 'HTTP redirects to domain HTTPS',
                        'passed': response.status == 308 and redirect == 'https://' + host + '/accounts/login/'})
        response.read(1024)
        response.close()
    finally:
        if plain:
            plain.close()
    status, headers = get('/accounts/login/')
    results.append({'check': 'Verified TLS and login GET', 'passed': status == 200})
    header_map = {k.lower(): v for k, v in headers}
    cookies = SimpleCookie()
    for key, value in headers:
        if key.lower() == 'set-cookie':
            cookies.load(value)
    csrf = cookies.get('csrftoken')
    results.append({'check': 'CSRF cookie is Secure and SameSite Lax',
                    'passed': bool(csrf and csrf['secure'] and csrf['samesite'].lower() == 'lax')})
    results.append({'check': 'HSTS, no-store and frame protection',
                    'passed': ('max-age=' in header_map.get('strict-transport-security', '') and
                               'no-store' in header_map.get('cache-control', '') and
                               header_map.get('x-frame-options') == 'DENY')})
    status, _ = get('/static/experience.css')
    results.append({'check': 'Collected static asset', 'passed': status == 200})
    status, _ = get('/health/', {'X-Forwarded-Proto': 'http'})
    results.append({'check': 'Gateway overwrites spoofed proxy scheme', 'passed': status == 200})
    try:
        status, _ = get('/accounts/login/', {'Host': 'wrong-host.invalid'})
        refused = status in (400, 403, 421, 444)
    except (ConnectionError, OSError):
        refused = True
    results.append({'check': 'Foreign Host is not served', 'passed': refused})
    return {'scope': 'Read-only network preflight; not full G4 acceptance', 'host': host,
            'trust': 'explicit CA (rehearsal/private)' if ca_file else 'system certificate trust',
            'dns_cutover_verified': not bool(connect_ip), 'results': results,
            'network_checks_passed': all(r['passed'] for r in results), 'public_acceptance_executed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--connect-ip')
    parser.add_argument('--http-port', type=int, default=80)
    parser.add_argument('--https-port', type=int, default=443)
    parser.add_argument('--ca-file')
    args = parser.parse_args()
    try:
        result = probe(args.host, connect_ip=args.connect_ip, http_port=args.http_port,
                       https_port=args.https_port, ca_file=args.ca_file)
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result['network_checks_passed'] else 1)
    except (OSError, ValueError, ConnectionError):
        raise SystemExit('G4 target probe did not pass. No authentication/business write performed.') from None
