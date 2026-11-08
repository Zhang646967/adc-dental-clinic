"""Observe the synthetic patient journey from outside the application host."""
import argparse
from datetime import date, datetime, timedelta, timezone
from http.client import HTTPException
from http.cookiejar import CookieJar
import json
from pathlib import Path
import re
import ssl
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, HTTPCookieProcessor, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.g4_course import private_directory, private_file
from scripts.g4_https_probe import NoRedirect, TargetHTTPSConnection
from scripts.g4_mac_demo import atomic_text
from scripts.g4_prepare import write_private
from scripts.recovery_receipts import instant

API = '/api/mini/v1/'
MAX_RESPONSE = 256 * 1024
LATENCY_MS = 5000
MAX_START_DELAY_MS = 10000
CLOCK_TOLERANCE_MS = 1000
TARGET_ROUNDS = 24 * 60 + 1
HOSTNAME = re.compile(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?')


def load_fixture(path):
    fixture = json.loads(private_file(path).read_text(encoding='utf-8'))
    if (fixture.get('scope') != 'synthetic-patient' or
            not HOSTNAME.fullmatch(fixture['host']) or
            not all(type(fixture[k]) is int and fixture[k] > 0
                    for k in ('clinic', 'service', 'own_visit', 'foreign_visit')) or
            fixture['own_visit'] == fixture['foreign_visit'] or
            not all(isinstance(fixture[k], str) and fixture[k] for k in ('username', 'password'))):
        raise ValueError('Use a private synthetic patient fixture bound to one DNS hostname.')
    return fixture


class LoopbackHTTPS(HTTPSHandler):
    def https_open(self, request):
        def connection(address, **kwargs):
            host, port = address.rsplit(':', 1)
            return TargetHTTPSConnection(host, int(port), connect_ip='127.0.0.1',
                                         context=self._context, **kwargs)
        return self.do_open(connection, request)


class Journey:
    def __init__(self, fixture, *, rehearsal=False, https_port=443, ca_file=None):
        self.fixture = fixture
        self.origin = 'https://' + fixture['host']
        if rehearsal:
            self.origin += f':{https_port}'
        context = ssl.create_default_context(cafile=ca_file)
        self.opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPCookieProcessor(CookieJar()),
                                  (LoopbackHTTPS if rehearsal else HTTPSHandler)(context=context))
        self.session = {}
        self.steps = []

    def step(self, name, route, check, *, status=200, form=None):
        start = time.monotonic()
        row = {'step': name, 'passed': False}
        headers = {'Accept': 'application/json', 'Cache-Control': 'no-cache'}
        body = None
        if form is not None:
            body = urlencode(form).encode()
            headers.update({'Content-Type': 'application/x-www-form-urlencoded',
                            'Origin': self.origin, 'Referer': self.origin + API + 'session/',
                            'X-CSRFToken': self.session['csrf_token']})
        if self.session.get('workspace_token'):
            headers['X-ADC-Workspace'] = self.session['workspace_token']
        request = Request(self.origin + API + route, data=body, headers=headers)
        data = None
        try:
            try:
                response = self.opener.open(request, timeout=4)
            except HTTPError as error:
                response = error
            with response:
                row['http_status'] = response.status
                raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ValueError('Probe response exceeds the bound.')
            payload = json.loads(raw)
            request_id = payload.get('request_id', '')
            if isinstance(request_id, str) and re.fullmatch(r'[0-9a-f]{32}', request_id):
                row['request_id'] = request_id
            expected_ok = status == 200
            if row['http_status'] == status and payload.get('ok') is expected_ok and check(payload):
                row['passed'] = True
                data = payload.get('data')
            else:
                row['failure'] = 'UNEXPECTED_RESPONSE'
        except (OSError, HTTPException):
            row['failure'] = 'TRANSPORT'
        except (ValueError, KeyError, AttributeError, TypeError):
            row['failure'] = 'INVALID_RESPONSE'
        row['elapsed_ms'] = round((time.monotonic() - start) * 1000)
        self.steps.append(row)
        return data

    def run(self):
        f = self.fixture
        catalogue = self.step('catalogue', 'discovery/index/', lambda p: any(
            c['id'] == f['clinic'] and c['synthetic'] is True and
            any(s['id'] == f['service'] for s in c['services'])
            for c in p['data']['clinics']))
        if catalogue is None:
            return
        self.step('guest_boundary', 'visits/', lambda p: p.get('code') == 'LOGIN_REQUIRED'
                  and 'data' not in p, status=401)
        guest = self.step('session', 'session/', lambda p: p['data']['authenticated'] is False
                          and bool(p['data']['csrf_token']))
        if guest is None:
            return
        self.session = guest
        actor = self.step('login', 'login/', lambda p: bool(p['data']['csrf_token']),
                          form={'username': f['username'], 'password': f['password']})
        if actor is None:
            return
        self.session = actor
        try:
            if not (actor.get('authenticated') is True and actor.get('subject_key') == 'self'
                    and actor.get('workspace_token') and not actor.get('delegated')):
                self.steps[-1].update(passed=False, failure='SELF_CONTEXT_REQUIRED')
                return
            try:
                tomorrow = (date.fromisoformat(actor['today']) + timedelta(days=1)).isoformat()
            except (ValueError, KeyError, TypeError):
                self.steps[-1].update(passed=False, failure='INVALID_BUSINESS_DATE')
                return
            query = urlencode({'clinic': f['clinic'], 'service': f['service'], 'day': tomorrow})
            self.step('availability', 'candidates/?' + query, lambda p: availability(p['data']))
            self.step('own_result', f'visits/{f["own_visit"]}/', lambda p:
                      p['data']['id'] == f['own_visit'] and p['data']['clinic_id'] == f['clinic']
                      and bool(p['data']['status']))
            self.step('other_patient_boundary', f'visits/{f["foreign_visit"]}/',
                      lambda p: p.get('code') == 'NOT_FOUND' and 'data' not in p, status=404)
        finally:
            self.step('logout', 'logout/', lambda p: p['data']['authenticated'] is False, form={})


def availability(data):
    rows, state = data['rows'], data['status']
    return isinstance(rows, list) and (
        (state == 'AVAILABLE' and bool(rows)) or (state in ('NO_COMBINATION', 'NO_SCHEDULE') and not rows))


def sample(fixture, **options):
    started = time.monotonic()
    journey = Journey(fixture, **options)
    journey.run()
    return {'steps': journey.steps, 'passed': len(journey.steps) == 8 and
            all(s['passed'] for s in journey.steps), 'elapsed_ms': round((time.monotonic() - started) * 1000)}


def good(row):
    return (row['passed'] and row['elapsed_ms'] <= LATENCY_MS
            and row['start_delay_ms'] <= MAX_START_DELAY_MS)


def timestamps_match_schedule(rows, interval, started_at):
    if not rows:
        return False
    try:
        times = [instant(row['at']) for row in rows]
        anchor = instant(started_at) if started_at else times[0] - timedelta(
            milliseconds=rows[0]['start_delay_ms'])
    except (KeyError, ValueError):
        return False
    for index, at in enumerate(times):
        wall_ms = (at - anchor).total_seconds() * 1000
        scheduled_ms = index * interval * 1000 + rows[index]['start_delay_ms']
        if abs(wall_ms - scheduled_ms) > CLOCK_TOLERANCE_MS:
            return False
        if index:
            gap_ms = (at - times[index - 1]).total_seconds() * 1000
            if not 0 < gap_ms <= interval * 1000 + MAX_START_DELAY_MS + CLOCK_TOLERANCE_MS:
                return False
    return True


def summarize(rows, expected, *, interval=60, started_at=None):
    good_count = sum(good(row) for row in rows)
    complete = len(rows) == expected
    on_time = all(0 <= row['start_delay_ms'] <= MAX_START_DELAY_MS for row in rows)
    wall_clock_verified = timestamps_match_schedule(rows, interval, started_at)
    incident_open = bool(len(rows) >= 2 and not good(rows[-1]) and not good(rows[-2]))
    passed = (complete and on_time and wall_clock_verified and good_count * 1000 >= expected * 999
              and not incident_open and good(rows[-1]))
    return {'state': 'PASS' if passed else 'FAIL' if complete else 'INCOMPLETE',
            'samples': len(rows), 'expected': expected, 'good_samples': good_count,
            'all_started_on_time': on_time, 'wall_clock_schedule_verified': wall_clock_verified,
            'incident_open': incident_open}


def observe(run_sample, path, *, count, interval, scope):
    rows = []
    incident_open = False
    start = time.monotonic()
    receipt = {'scope': scope, 'interval_seconds': interval, 'expected_samples': count,
               'started_at': datetime.now(timezone.utc).isoformat(), 'samples': rows,
               'summary': summarize(rows, count, interval=interval)}
    write_private(path, json.dumps(receipt) + '\n')
    for n in range(count):
        scheduled = start + n * interval
        time.sleep(max(0, scheduled - time.monotonic()))
        at = datetime.now(timezone.utc).isoformat()
        delay = round((time.monotonic() - scheduled) * 1000)
        row = run_sample() | {'at': at, 'start_delay_ms': delay}
        rows.append(row)
        summary = summarize(rows, count, interval=interval, started_at=receipt['started_at'])
        if incident_open != summary['incident_open']:
            incident_open = summary['incident_open']
            row['event'] = 'OPENED' if incident_open else 'RECOVERED'
        receipt['summary'] = summary
        atomic_text(path, json.dumps(receipt, indent=2) + '\n')
        if 'event' in row:
            print(json.dumps({'signal': 'PATIENT_JOURNEY', 'event': row['event'], 'at': at}), flush=True)
    return receipt['summary']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True)
    parser.add_argument('--receipt', required=True)
    parser.add_argument('--observe', action='store_true', help='Sample once a minute for 24 hours.')
    parser.add_argument('--rehearsal', action='store_true', help='Use only loopback with an explicit rehearsal CA.')
    parser.add_argument('--ca-file')
    parser.add_argument('--https-port', type=int, default=443)
    parser.add_argument('--rehearsal-rounds', type=int, default=1)
    args = parser.parse_args()
    if args.rehearsal:
        if args.observe or not args.ca_file or not 1024 <= args.https_port <= 65535 or not 1 <= args.rehearsal_rounds <= 30:
            parser.error('Use a loopback HTTPS port, rehearsal CA and 1–30 rounds.')
    elif args.ca_file or args.https_port != 443 or args.rehearsal_rounds != 1:
        parser.error('Target mode requires direct HTTPS on 443 with system certificate trust.')
    try:
        fixture = load_fixture(args.fixture)
        path = Path(args.receipt).absolute()
        private_directory(path.parent)
        scope = 'LOOPBACK_REHEARSAL' if args.rehearsal else 'DIRECT_HTTPS_SYNTHETIC_PATIENT'
        summary = observe(lambda: sample(fixture, rehearsal=args.rehearsal, https_port=args.https_port,
                                        ca_file=args.ca_file), path,
                          count=TARGET_ROUNDS if args.observe else args.rehearsal_rounds,
                          interval=5 if args.rehearsal else 60, scope=scope)
        print(json.dumps(summary))
        return 0 if summary['state'] == 'PASS' else 1
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print('Patient probe stopped. Check the private fixture, CA and fresh receipt path.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
