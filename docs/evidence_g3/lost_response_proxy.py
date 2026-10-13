"""Loopback-only G3 fault injection: lose a successful response, never replay it.

Use only against the dedicated synthetic gateway at 127.0.0.1:18001.
Write one absolute POST path to --arm-file; it is consumed once. The upstream
request runs normally, but its response connection is closed. A browser retry
to that path is blocked locally until a different path is armed. Logs contain
only paths and status codes; never bodies, headers, cookies or credentials.
"""
import argparse
import http.client
from html import escape
import json
from pathlib import Path
import socket
from threading import RLock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


class FaultProxy(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == '/__g3_responsive__/':
            query = parse_qs(url.query)
            width = query.get('width', [''])[0]
            path = query.get('src', [''])[0]
            if width not in ('320', '390') or not path.startswith('/') or path.startswith('//') or '..' in path:
                self.send_error(400, 'Use a bounded CSS width and a local Django path.')
                return
            # A real nested browsing context: media queries and controls belong
            # to the live Django response. No fixtures, DOM injection or JS.
            html = ('<!doctype html><html lang="en"><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<title>G3 real Django responsive check</title>'
                    '<body style="margin:16px;font:16px system-ui;background:#e8ece9">'
                    '<h1 style="font-size:20px">G3: real Django page at ' + width + ' CSS px</h1>'
                    '<p>The live page below uses its own ' + width + ' px browsing viewport.</p>'
                    '<iframe title="Live ADC acceptance page" width="' + width + '" height="2400" '
                    'style="border:0;display:block;background:white" src="' + escape(path, quote=True) + '"></iframe>'
                    '</body></html>').encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(html)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(html)
            self.close_connection = True
            return
        self.forward()

    def do_POST(self):
        self.forward()

    def forward(self):
        path = urlsplit(self.path).path
        with self.server.fault_lock:
            arm = self.server.arm_file
            if arm.exists():
                requested = arm.read_text().strip()
                if requested.startswith('/') and '?' not in requested:
                    self.server.armed_path = requested
                    self.server.blocked_path = None
                arm.unlink()
            if self.command == 'POST' and self.server.blocked_path == path:
                self.send_error(503, 'Prior response lost. Read saved facts before another action.')
                self.server.record({'path': path, 'retry_blocked': True})
                return
            lose = self.command == 'POST' and self.server.armed_path == path
            if lose:
                # Block concurrent/automatic retries before forwarding the request.
                self.server.armed_path = None
                self.server.blocked_path = path
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ('connection', 'proxy-connection', 'transfer-encoding')}
        headers['Connection'] = 'close'
        length = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(length) if length else None
        upstream = http.client.HTTPConnection('127.0.0.1', 18001, timeout=20)
        try:
            upstream.request(self.command, self.path, body=body, headers=headers)
            response = upstream.getresponse()
            payload = response.read()
            if lose and 200 <= response.status < 400:
                self.server.record({'path': path, 'upstream_status': response.status,
                                    'response_dropped': True})
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() == 'x-frame-options' and self.headers.get('Sec-Fetch-Dest') == 'iframe':
                    # Test proxy only: permit same-origin responsive frames.
                    # The actual Django gateway retains its frame protection.
                    continue
                if key.lower() == 'content-security-policy' and self.headers.get('Sec-Fetch-Dest') == 'iframe':
                    value = value.replace("frame-ancestors 'none'", "frame-ancestors 'self'")
                if key.lower() not in ('connection', 'transfer-encoding', 'content-length', 'server', 'date'):
                    self.send_header(key, value)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(payload)
            self.close_connection = True
            if lose:
                self.server.record({'path': path, 'upstream_status': response.status,
                                    'response_dropped': False})
        finally:
            upstream.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arm-file', type=Path, required=True)
    parser.add_argument('--events-file', type=Path, required=True)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', 18002), FaultProxy)
    server.arm_file = args.arm_file
    server.events_file = args.events_file
    server.fault_lock = RLock()
    server.armed_path = server.blocked_path = None

    def record(event):
        with server.fault_lock:
            with server.events_file.open('a') as output:
                output.write(json.dumps(event) + '\n')

    server.record = record
    print('G3 response-loss proxy ready on loopback port 18002.', flush=True)
    server.serve_forever()
