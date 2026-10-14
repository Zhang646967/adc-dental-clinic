"""Bounded 80% GET / 20% patient-creation POST course acceptance workload.

Ten DISTINCT synthetic front-desk users are created/granted via existing,
CSRF-protected technical UI, then log in and choose their clinic normally.
No retries, direct SQL writes, permission bypass, or record cleanup. Write
responses must redirect to a patient; the matching DB run-prefix counts must
be checked separately. This cannot certify all booking/care/finance workflows.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.cookies import SimpleCookie
import json
import math
from pathlib import Path
import re
import secrets
import ssl
import sys
import threading
import time
from urllib.parse import urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.g4_course import OriginHTTPS, private_file
from scripts.g4_prepare import inspect_bundle
from scripts.g4_load import Forms, percentile
from scripts.g4_mac_demo import atomic_text
from scripts.g4_https_probe import TargetHTTPSConnection

READ_ROUTES = ('/frontdesk/', '/patients/', '/visits/', '/patients/new/')
SETUP_PATTERN = re.compile(r'/(?:accounts/login/|workspace/(?:clinic|role)/activate/|'
    r'workspace/(?:select-clinic|select-role|activate)/|technical/|technical/accounts/(?:new/|[0-9]+/(?:grant/)?)|'
    r'frontdesk/|patients/(?:new/|[0-9]+/)?|visits/)')


class Client:
    def __init__(self, plan, scope, ca_file=None):
        self.plan, self.scope, self.cookies = plan, scope, {}
        self.context = ssl.create_default_context(cafile=ca_file)
        self.connection = None
        self.lock = threading.Lock()

    def close(self):
        if self.connection:
            self.connection.close()
        self.connection = None

    def request(self, method, route, form=None):
        if method not in ('GET', 'POST') or not SETUP_PATTERN.fullmatch(route):
            raise ValueError('Only curated course setup and patient routes are allowed.')
        if self.connection is None:
            self.connection = (OriginHTTPS(self.plan['host'], self.plan['ports'][1], timeout=10, context=self.context)
                               if self.scope == 'origin' else
                               TargetHTTPSConnection(self.plan['host'], 443, timeout=10, context=self.context))
        headers = {'Host': self.plan['host'], 'Cookie': '; '.join(k + '=' + v for k, v in self.cookies.items())}
        body = None
        if method == 'POST':
            body = urlencode(form or {})
            headers |= {'Content-Type': 'application/x-www-form-urlencoded',
                        'Origin': 'https://' + self.plan['host'], 'Referer': 'https://' + self.plan['host'] + route}
        try:
            self.connection.request(method, route, body=body, headers=headers)
            reply = self.connection.getresponse()
            data = reply.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise ValueError('Unexpected oversized response.')
            for name, value in reply.getheaders():
                if name.lower() == 'set-cookie':
                    cookie = SimpleCookie(value)
                    for key in ('csrftoken', 'sessionid'):
                        if key in cookie:
                            self.cookies[key] = cookie[key].value
            return reply.status, reply.getheader('Location'), data
        except Exception:
            self.close()
            raise

    def follow(self, method, route, form=None):
        status, location, body = self.request(method, route, form)
        for _ in range(6):
            if status not in (301, 302, 303):
                return route, status, body
            target = urlsplit(location or '')
            if target.scheme not in ('', 'https') or target.netloc not in ('', self.plan['host']) or target.query or target.fragment:
                raise ValueError('Unexpected setup redirect.')
            route = target.path
            status, location, body = self.request('GET', route)
        raise ValueError('Setup redirect loop.')

    def form(self, route, required):
        status, _, body = self.request('GET', route)
        forms = [f for f in Forms(body).forms if set(required) <= set(f['inputs'])]
        if status != 200 or len(forms) != 1:
            raise ValueError('Expected one signed server form.')
        return forms[0]['inputs']

    def login(self, username, password, clinic=None):
        fields = self.form('/accounts/login/', ('username', 'password', 'csrfmiddlewaretoken'))
        route, status, body = self.follow('POST', '/accounts/login/', fields | {'username': username, 'password': password})
        if clinic:
            forms = [f for f in Forms(body).forms if f['action'] == '/workspace/clinic/activate/'
                     and f['inputs'].get('clinic') == str(clinic)]
            if len(forms) != 1:
                raise ValueError('Expected explicit signed clinic choice.')
            route, status, body = self.follow('POST', '/workspace/clinic/activate/', forms[0]['inputs'])
        if status != 200 or 'sessionid' not in self.cookies or username.encode() not in body:
            raise ValueError('Normal authenticated workspace login failed.')
        return route


def load_plan(bundle, scope, ca_file):
    inspect_bundle(bundle)
    plan = json.loads((bundle / 'plan.json').read_text())
    if plan.get('access_mode') != 'course-writable' or plan['read_only'] or plan.get('mode') != 'direct_tls':
        raise ValueError('Use only a separate course-writable synthetic bundle.')
    if scope == 'origin' and plan['bind_ip'] != '127.0.0.1':
        raise ValueError('Local workload requires a separate loopback bundle.')
    if scope == 'public' and (plan['ports'] != [80, 443] or ca_file):
        raise ValueError('Public workload requires normal trusted HTTPS on port 443.')
    return plan


def prepare_actors(bundle, plan, scope, ca_file):
    path = bundle / 'private/load-actors.json'
    if path.exists():
        raise ValueError('Load accounts already recorded; never recreate/reset them.')
    passwords = {}
    for line in private_file(bundle / 'private/demo-credentials.txt').read_text().splitlines():
        fields = [s.strip() for s in line.split('|')]
        if len(fields) == 3 and fields[0].startswith('LOCAL'):
            passwords[fields[1]] = fields[2]
    technical = Client(plan, scope, ca_file)
    run_id = secrets.token_hex(6)
    actors = []
    document = {'project': plan['project'], 'host': plan['host'], 'run_id': run_id, 'actors': actors}
    try:
        if technical.login('tech_demo', passwords['tech_demo']) != '/technical/':
            raise ValueError('Expected technical workspace.')
        for index in range(10):
            username, password = 'load_' + run_id + '_' + str(index), secrets.token_urlsafe(24)
            fields = technical.form('/technical/accounts/new/', ('operator_password', 'csrfmiddlewaretoken'))
            route, status, _ = technical.follow('POST', '/technical/accounts/new/', fields | {
                'username': username, 'dentist': '', 'password1': password, 'password2': password,
                'operator_password': passwords['tech_demo'], 'reason': 'Synthetic bounded course load acceptance',
                'confirmed': 'on'})
            if status != 200 or not re.fullmatch(r'/technical/accounts/[0-9]+/', route):
                raise ValueError('Account creation did not produce an ordinary account.')
            actor = {'username': username, 'password': password, 'clinic': '1', 'account_route': route}
            actors.append(actor)
            atomic_text(path, json.dumps(document, indent=2) + '\n')
            action = route + 'grant/'
            fields = technical.form(action, ('target_token', 'operator_password', 'workspace_token'))
            status, _, _ = technical.request('POST', action, fields | {
                'role': 'FRONT_DESK', 'clinic': '1', 'operator_password': passwords['tech_demo'],
                'reason': 'Synthetic current-clinic course load access', 'confirmed': 'on'})
            if status != 302:
                raise ValueError('Explicit account grant did not commit.')
            actor['grant_confirmed'] = True
            atomic_text(path, json.dumps(document, indent=2) + '\n')
    finally:
        technical.close()
    return {'status': 'LOAD_ACTORS_PREPARED', 'distinct_users': 10, 'project': plan['project'],
            'run_id': run_id, 'passwords': 'private file only'}


def read_actors(path, plan):
    doc = json.loads(private_file(path).read_text())
    if (doc['project'] != plan['project'] or doc['host'] != plan['host'] or
            not re.fullmatch('[0-9a-f]{12}', doc['run_id']) or len(doc['actors']) != 10 or
            len({a['username'] for a in doc['actors']}) != 10 or
            any(not a.get('grant_confirmed') or a['clinic'] != '1' for a in doc['actors'])):
        raise ValueError('Use ten distinct fully granted synthetic accounts from this course instance.')
    return doc


def workload(bundle, plan, scope, ca_file, duration=1800, rps=5):
    if not (5 <= duration <= 1800 and 1 <= rps <= 5):
        raise ValueError('Workload exceeds the bounded ten-user course envelope.')
    doc = read_actors(bundle / 'private/load-actors.json', plan)
    clients, forms = [], []
    try:
        for actor in doc['actors']:
            client = Client(plan, scope, ca_file)
            clients.append(client)
            if client.login(actor['username'], actor['password'], actor['clinic']) != '/frontdesk/':
                raise ValueError('Expected the assigned front-desk workspace.')
            forms.append(client.form('/patients/new/', ('csrfmiddlewaretoken', 'workspace_token')))
            time.sleep(.6)
        prefix = 'COURSE-LOAD-' + doc['run_id'] + '-' + secrets.token_hex(4) + '-'
        planned = duration * rps
        samples, pending, drops = [], set(), 0
        start = time.monotonic()
        def measure(index, scheduled):
            write = index % 5 == 4
            actor_index = (index // 5) % 10 if write else index % 10
            client, actor = clients[actor_index], doc['actors'][actor_index]
            status, ok = 0, False
            with client.lock:
                try:
                    if write:
                        fields = forms[actor_index] | {
                            'clinic': actor['clinic'], 'name': prefix + str(index),
                            'date_of_birth': '2000-01-01', 'billing_address': 'Synthetic course address',
                            'phone': '000-DEMO', 'email': 'load@example.invalid',
                            'emergency_name': 'Synthetic contact', 'emergency_phone': '000-DEMO',
                            'allergy_status': 'UNKNOWN'}
                        status, location, _ = client.request('POST', '/patients/new/', fields)
                        ok = status == 302 and bool(re.fullmatch(r'/patients/[0-9]+/', location or ''))
                    else:
                        route = READ_ROUTES[(index // 10) % len(READ_ROUTES)]
                        status, _, body = client.request('GET', route)
                        ok = status == 200 and actor['username'].encode() in body
                        if ok and route == '/patients/new/':
                            current = [f for f in Forms(body).forms if
                                       {'workspace_token', 'name', 'date_of_birth'} <= set(f['inputs'])]
                            if len(current) != 1:
                                ok = False
                            else:
                                forms[actor_index] = current[0]['inputs']
                except Exception:
                    pass  # Retain failures; no write retry after an uncertain response.
            return {'status': status, 'ok': ok, 'write': write,
                    'elapsed_ms': (time.monotonic() - scheduled) * 1000}
        with ThreadPoolExecutor(max_workers=10) as pool:
            for index in range(planned):
                scheduled = start + index / rps
                time.sleep(max(0, scheduled - time.monotonic()))
                completed = {t for t in pending if t.done()}
                samples.extend(t.result() for t in completed)
                pending -= completed
                if len(pending) >= 20:
                    drops += 1
                else:
                    pending.add(pool.submit(measure, index, scheduled))
                if index % (rps * 30) == 0:
                    atomic_text(bundle / 'private/course-load-progress.json', json.dumps({
                        'attempted': index + 1, 'completed': len(samples), 'queue_dropped': drops,
                        'successful': sum(s['ok'] for s in samples)}) + '\n')
            samples.extend(t.result() for t in pending)
            time.sleep(max(0, start + duration - time.monotonic()))
        p95 = percentile([s['elapsed_ms'] for s in samples], 95)
        writes = [s for s in samples if s['write']]
        result = {'scope': scope, 'users': 10, 'distinct_accounts': 10, 'duration_seconds': duration,
                  'elapsed_seconds': round(time.monotonic() - start, 3), 'rps': rps,
                  'attempted': planned, 'successful': sum(s['ok'] for s in samples),
                  'statuses': dict(Counter(str(s['status']) for s in samples)), 'queue_dropped': drops,
                  'successful_writes': sum(s['ok'] for s in writes), 'planned_writes': planned // 5,
                  'p95_ms': p95, 'patient_name_prefix': prefix, 'db_oracle': 'REQUIRED',
                  'http_passed': not drops and len(samples) == planned and all(s['ok'] for s in samples) and p95 <= 5000,
                  'public_acceptance_executed': scope == 'public',
                  'course_online_readiness': 'NOT_GRANTED_BY_LOAD_ALONE'}
        atomic_text(bundle / 'private/course-load.json', json.dumps(result, indent=2) + '\n')
        return result
    finally:
        for client in clients:
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--scope', choices=('origin', 'public'), required=True)
    parser.add_argument('--ca-file')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('prepare-synthetic-actors')
    execute = sub.add_parser('run')
    execute.add_argument('--duration', type=int, default=1800)
    execute.add_argument('--rps', type=int, default=5)
    args = parser.parse_args()
    bundle = Path(args.output).absolute()
    plan = load_plan(bundle, args.scope, args.ca_file)
    result = (prepare_actors(bundle, plan, args.scope, args.ca_file) if args.action == 'prepare-synthetic-actors'
              else workload(bundle, plan, args.scope, args.ca_file, args.duration, args.rps))
    print(json.dumps(result, indent=2))
    return 0 if result.get('http_passed', True) else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError):
        raise SystemExit('Course workload stopped. Preserve private setup/results; no cloud acceptance granted.') from None
