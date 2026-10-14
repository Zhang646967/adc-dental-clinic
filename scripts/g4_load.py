"""Bounded, authenticated GET load for the explicitly selected Mac course demo.

Setup uses normal CSRF-protected login and signed clinic selection only. Runs
never POST, follow redirects, retry failures or export credentials/page bodies.
Origin mode measures loopback HTTP with the reviewed proxy scheme; public mode
uses normal TLS/hostname verification. Results do not establish production SLA.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.client import HTTPConnection, HTTPException
from http.cookies import SimpleCookie
import json
import math
from pathlib import Path
import re
import ssl
import sys
import threading
import time
from urllib.parse import urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.g4_mac_demo import atomic_text, checked_bundle
from scripts.g4_https_probe import TargetHTTPSConnection

ACTORS = (
    ('front_a', 'FRONT_DESK_A', '1', ('/frontdesk/', '/patients/', '/visits/')),
    ('front_b', 'FRONT_DESK_B', '2', ('/frontdesk/', '/patients/', '/visits/')),
    ('manager_a', 'MANAGER', '1', ('/manager/', '/slots/', '/coordination/tasks/')),
    ('doctor_a', 'DENTIST', None, ('/doctor/', '/visits/')),
    ('patient_demo_a', 'PATIENT_A', None, ('/portal/', '/portal/slots/', '/portal/appointments/')),
    ('patient_demo_b', 'PATIENT_B', None, ('/portal/', '/portal/slots/', '/portal/appointments/')),
    ('finance_demo', 'FINANCE', None, ('/financial-workspace/', '/finance/')),
    ('hq_demo', 'HQ', None, ('/headquarters/',)),
    ('tech_demo', 'SYSADMIN', None, ('/technical/',)),
)
ROUTES = frozenset(route for _, _, _, routes in ACTORS for route in routes)
LOGIN_ROUTES = frozenset(('/accounts/login/', '/portal/login/'))
READ_ONLY_MARKER = '只读'.encode('utf-8')


def private_path(bundle, name):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}\.json', name):
        raise ValueError('Use a simple JSON filename in the selected private directory.')
    path = bundle / 'private' / name
    if path.resolve().parent != (bundle / 'private').resolve():
        raise ValueError('Private output cannot escape the selected bundle.')
    return path


class Forms(HTMLParser):
    def __init__(self, body):
        super().__init__()
        self.forms, self.current = [], None
        self.feed(body.decode('utf-8'))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.current = {'action': attrs.get('action', ''), 'inputs': {}}
            self.forms.append(self.current)
        elif tag == 'input' and self.current is not None and attrs.get('name'):
            self.current['inputs'][attrs['name']] = attrs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.current = None


class Client:
    def __init__(self, plan, scope, cookies=None, context=None):
        self.plan, self.scope = plan, scope
        self.cookies = dict(cookies or {})
        self.context = context or ssl.create_default_context()
        self.connection = None

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None

    def request(self, method, route, form=None, cookies=None):
        allowed = ROUTES | LOGIN_ROUTES
        if method == 'POST':
            allowed = LOGIN_ROUTES | {'/workspace/clinic/activate/'}
        if method not in ('GET', 'POST') or route not in allowed:
            raise ValueError('Only curated GET routes or explicit setup POSTs are accepted.')
        if self.connection is None:
            self.connection = (HTTPConnection('127.0.0.1', self.plan['ports'][0], timeout=8)
                               if self.scope == 'origin' else
                               TargetHTTPSConnection(self.plan['host'], 443, timeout=8, context=self.context))
        headers = {'Host': self.plan['host'], 'Accept': 'text/html',
                   'Cookie': '; '.join(k + '=' + v for k, v in (cookies if cookies is not None else self.cookies).items())}
        if self.scope == 'origin':
            headers['X-Forwarded-Proto'] = 'https'
        body = None
        if method == 'POST':
            body = urlencode(form or {})
            headers |= {'Content-Type': 'application/x-www-form-urlencoded',
                        'Origin': 'https://' + self.plan['host'],
                        'Referer': 'https://' + self.plan['host'] + route}
        try:
            self.connection.request(method, route, body=body, headers=headers)
            response = self.connection.getresponse()
            data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise ValueError('Unexpected oversized response.')
            for key, value in response.getheaders():
                if key.lower() == 'set-cookie':
                    parsed = SimpleCookie(value)
                    for name in ('sessionid', 'csrftoken'):
                        if name in parsed:
                            self.cookies[name] = parsed[name].value
            return response.status, response.getheader('Location'), data
        except Exception:
            self.close()
            raise

    def follow_setup(self, method, route, form=None):
        status, location, body = self.request(method, route, form)
        for _ in range(6):
            if status not in (301, 302, 303, 307, 308):
                return route, status, body
            target = urlsplit(location or '')
            if target.query or target.fragment or target.netloc not in ('', self.plan['host']) or target.scheme not in ('', 'https'):
                raise ValueError('Unexpected setup redirect.')
            route = target.path
            status, location, body = self.request('GET', route)
        raise ValueError('Unexpected setup redirect loop.')


def prepare_sessions(bundle, plan, scope, path):
    credentials = {}
    for line in (bundle / 'private/demo-credentials.txt').read_text().splitlines():
        fields = [value.strip() for value in line.split('|')]
        if len(fields) == 3 and fields[0].startswith('LOCAL'):
            credentials[fields[1]] = fields[2]
    sessions = []
    for username, label, clinic, routes in ACTORS:
        client = Client(plan, scope)
        try:
            login = '/portal/login/' if label.startswith('PATIENT') else '/accounts/login/'
            _, status, body = client.follow_setup('GET', login)
            forms = [f for f in Forms(body).forms if 'username' in f['inputs'] and 'password' in f['inputs']]
            if status != 200 or len(forms) != 1 or username not in credentials:
                raise ValueError('Synthetic login setup did not pass.')
            form = forms[0]['inputs'] | {'username': username, 'password': credentials[username]}
            route, status, body = client.follow_setup('POST', login, form)
            if clinic:
                forms = [f for f in Forms(body).forms if f['action'] == '/workspace/clinic/activate/'
                         and f['inputs'].get('clinic') == clinic]
                if status != 200 or len(forms) != 1 or not forms[0]['inputs'].get('workspace_token'):
                    raise ValueError('Signed clinic selection setup did not pass.')
                route, status, body = client.follow_setup('POST', '/workspace/clinic/activate/', forms[0]['inputs'])
            if route != routes[0] or status != 200 or 'sessionid' not in client.cookies:
                raise ValueError('Authorized workspace setup did not pass.')
            for route in routes:
                status, _, body = client.request('GET', route)
                if status != 200 or READ_ONLY_MARKER not in body:
                    raise ValueError('Curated read-only route preflight did not pass.')
                time.sleep(.2)
            sessions.append({'label': label, 'cookies': client.cookies, 'routes': list(routes)})
        finally:
            client.close()
        # Initial 9 POST attempts fit the reviewed login burst. Pace GET preflight.
        time.sleep(.5)
    atomic_text(path, json.dumps({'project': plan['project'], 'host': plan['host'],
                                'created_at_utc': datetime.now(timezone.utc).isoformat(),
                                'sessions': sessions}, indent=2) + '\n')
    return len(sessions)


def read_sessions(path, plan):
    if path.stat().st_mode & 0o077:
        raise ValueError('Session file must remain private.')
    doc = json.loads(path.read_text())
    if doc['project'] != plan['project'] or doc['host'] != plan['host'] or len(doc['sessions']) != len(ACTORS):
        raise ValueError('Sessions must match this explicit demo instance.')
    for session, (_, label, _, routes) in zip(doc['sessions'], ACTORS):
        if (session['label'] != label or session['routes'] != list(routes) or
                set(session['cookies']) - {'sessionid', 'csrftoken'} or not session['cookies'].get('sessionid')):
            raise ValueError('Only the preflighted synthetic sessions/routes are accepted.')
    return doc['sessions']


def percentile(values, percent):
    return round(sorted(values)[max(0, math.ceil(len(values) * percent / 100) - 1)], 3) if values else None


def assess(attempted, successful, drops, throttled, p95, limit, expect_throttle):
    if attempted <= 0 or drops:
        return False
    if expect_throttle:
        return 0 < throttled < attempted and successful + throttled == attempted
    return successful == attempted and p95 is not None and 0 <= p95 <= limit


def run_load(plan, sessions, *, scope, users, rps, duration, max_p95_ms, expect_throttle=False, progress_path=None):
    if not (1 <= users <= 40 and 1 <= rps <= 60 and 5 <= duration <= 1800 and 0 < max_p95_ms <= 60000):
        raise ValueError('Load exceeds the bounded course-test envelope.')
    local = threading.local()
    context = ssl.create_default_context()
    start = time.monotonic()
    samples, pending = [], set()
    attempted, drops, max_lag = 0, 0, 0
    last_progress = start
    clients, client_lock = [], threading.Lock()
    warm_barrier = threading.Barrier(users)

    def warm_connection(index):
        local.client = Client(plan, scope, context=context)
        with client_lock:
            clients.append(local.client)
        began = time.monotonic()
        status, category = 0, 'transport_error'
        session = sessions[index % len(sessions)]
        try:
            status, _, body = local.client.request('GET', session['routes'][0], cookies=session['cookies'])
            category = ('ok' if READ_ONLY_MARKER in body else 'unexpected_body') if status == 200 else 'http_' + str(status)
        except Exception:
            pass
        elapsed = (time.monotonic() - began) * 1000
        warm_barrier.wait(timeout=20)
        return {'status': status, 'category': category, 'elapsed_ms': elapsed}

    def measure(index, scheduled):
        if not hasattr(local, 'client'):
            local.client = Client(plan, scope, context=context)
            with client_lock:
                clients.append(local.client)
        session = sessions[index % users % len(sessions)]
        route = session['routes'][(index // users) % len(session['routes'])]
        began = time.monotonic()
        status, category = 0, 'transport_error'
        try:
            status, _, body = local.client.request('GET', route, cookies=session['cookies'])
            category = ('ok' if READ_ONLY_MARKER in body else 'unexpected_body') if status == 200 else 'http_' + str(status)
        except Exception:
            pass  # One failed observation is retained; no retry or raw error/body export.
        ended = time.monotonic()
        return {'status': status, 'category': category, 'role': session['label'], 'route': route,
                'elapsed_ms': (ended - scheduled) * 1000, 'http_ms': (ended - began) * 1000}

    with ThreadPoolExecutor(max_workers=users) as pool:
        warm_tasks = [pool.submit(warm_connection, index) for index in range(users)]
        warm_results = [task.result() for task in warm_tasks]
        # Cold connection startup is reported and gated separately; the timed
        # open-loop phase begins only after every worker has its connection.
        start = last_progress = time.monotonic()
        while attempted < math.ceil(duration * rps):
            scheduled = start + attempted / rps
            delay = scheduled - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            completed = {task for task in pending if task.done()}
            samples.extend(task.result() for task in completed)
            pending -= completed
            max_lag = max(max_lag, (time.monotonic() - scheduled) * 1000)
            if len(pending) >= users * 2:
                drops += 1
            else:
                pending.add(pool.submit(measure, attempted, scheduled))
            attempted += 1
            if progress_path and time.monotonic() - last_progress >= 30:
                atomic_text(progress_path, json.dumps({
                    'status': 'RUNNING', 'elapsed_seconds': round(time.monotonic() - start, 3),
                    'attempted': attempted, 'completed': len(samples), 'pending': len(pending),
                    'queue_dropped': drops,
                    'statuses': dict(Counter(str(sample['status']) for sample in samples)),
                    'successful': sum(sample['category'] == 'ok' for sample in samples),
                }, indent=2) + '\n')
                last_progress = time.monotonic()
        samples.extend(task.result() for task in pending)
        remaining = start + duration - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
    elapsed = time.monotonic() - start
    for client in clients:
        client.close()
    successes = [sample for sample in samples if sample['category'] == 'ok']
    statuses = dict(Counter(str(sample['status']) for sample in samples))
    failures = attempted - len(successes)
    throttled = statuses.get('429', 0)
    p95 = percentile([sample['elapsed_ms'] for sample in successes], 95)
    warm_passed = all(sample['category'] == 'ok' and sample['elapsed_ms'] <= max_p95_ms for sample in warm_results)
    passed = warm_passed and assess(attempted, len(successes), drops, throttled, p95, max_p95_ms, expect_throttle)
    return {'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
            'scope': 'Authenticated synthetic GET load; no measurement POST, redirect following or retry',
            'project': plan['project'], 'host': plan['host'], 'transport': scope,
            'virtual_users': users, 'distinct_seeded_accounts': min(users, len(sessions)),
            'offered_rps': rps, 'planned_seconds': duration, 'elapsed_seconds': round(elapsed, 3),
            'attempted': attempted, 'completed': len(samples), 'queue_dropped': drops,
            'max_scheduler_lag_ms': round(max_lag, 3), 'successful': len(successes),
            'failure_rate': round(failures / attempted, 6), 'statuses': statuses,
            'categories': dict(Counter(sample['category'] for sample in samples)),
            'successful_rps': round(len(successes) / elapsed, 3),
            'success_p50_ms': percentile([sample['elapsed_ms'] for sample in successes], 50),
            'success_p95_ms': p95, 'success_p99_ms': percentile([sample['elapsed_ms'] for sample in successes], 99),
            'all_response_p95_ms': percentile([sample['elapsed_ms'] for sample in samples], 95),
            'max_p95_ms': max_p95_ms, 'expected_throttle': expect_throttle,
            'connection_warmup': {'requests': len(warm_results), 'passed': warm_passed,
                                  'statuses': dict(Counter(str(row['status']) for row in warm_results)),
                                  'max_latency_ms': round(max(row['elapsed_ms'] for row in warm_results), 3)},
            'routes': dict(Counter(sample['route'] for sample in samples)),
            'roles': dict(Counter(sample['role'] for sample in samples)),
            'passed': passed, 'full_G4_accepted': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('setup', 'run'))
    parser.add_argument('--output', default=str(ROOT / '.g4'))
    parser.add_argument('--scope', choices=('origin', 'public'), default='public')
    parser.add_argument('--sessions', default='load-sessions.json')
    parser.add_argument('--report', default='load-result.json')
    parser.add_argument('--progress', default='load-progress.json')
    parser.add_argument('--users', type=int, default=10)
    parser.add_argument('--rps', type=float, default=10)
    parser.add_argument('--duration', type=int, default=60)
    parser.add_argument('--max-p95-ms', type=int, default=None)
    parser.add_argument('--expect-throttle', action='store_true')
    args = parser.parse_args()
    bundle = Path(args.output).resolve()
    try:
        plan = checked_bundle(bundle)
        sessions = private_path(bundle, args.sessions)
        if args.action == 'setup':
            count = prepare_sessions(bundle, plan, args.scope, sessions)
            print(json.dumps({'setup': 'PASS', 'seeded_accounts': count, 'credentials': 'private only'}))
            return 0
        report = run_load(plan, read_sessions(sessions, plan), scope=args.scope, users=args.users,
                          rps=args.rps, duration=args.duration, expect_throttle=args.expect_throttle,
                          max_p95_ms=args.max_p95_ms or (2000 if args.scope == 'origin' else 5000),
                          progress_path=private_path(bundle, args.progress))
        atomic_text(private_path(bundle, args.report), json.dumps(report, indent=2) + '\n')
        atomic_text(private_path(bundle, args.progress), json.dumps({
            'status': 'PASS' if report['passed'] else 'FAIL',
            'elapsed_seconds': report['elapsed_seconds'], 'attempted': report['attempted'],
            'completed': report['completed'], 'pending': 0, 'queue_dropped': report['queue_dropped'],
            'statuses': report['statuses'], 'successful': report['successful'],
        }, indent=2) + '\n')
        print(json.dumps({key: report[key] for key in ('passed', 'attempted', 'successful', 'statuses',
                                                     'success_p95_ms', 'failure_rate', 'queue_dropped')}))
        return 0 if report['passed'] else 1
    except (OSError, ValueError, KeyError, HTTPException):
        print('Course load check stopped. Inspect private setup/state; credentials and bodies were not exported.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
