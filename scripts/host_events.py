#!/usr/bin/env python3
"""Private host observations and human incident handling. No automatic repair."""
import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from adc_core.operations_store import PrivateStore

SERVICES = ('db', 'web', 'gateway', 'notification-worker', 'operations')
APP_SERVICES = ('web', 'notification-worker', 'operations')
SEVERITY = {'HEALTHY': 0, 'WARNING': 1, 'CRITICAL': 2, 'UNKNOWN': 3}
ACTIONS = ('inspect_dependencies', 'restart_service', 'review_resource_limit',
           'repair_collector', 'retry_backup', 'verify_business_facts',
           'verify_health', 'accept_observation_gap')
EVENTS = {'stop': 'CONTAINER_STOPPED', 'die': 'CONTAINER_EXITED',
          'restart': 'CONTAINER_RESTARTED', 'start': 'CONTAINER_STARTED',
          'oom': 'CONTAINER_OOM', 'destroy': 'CONTAINER_REMOVED',
          'pause': 'CONTAINER_PAUSED', 'unpause': 'CONTAINER_UNPAUSED'}
LABEL = 'com.docker.compose.'
SOURCE = '{{range .Config.Env}}{{if eq (index (split . "=") 0) "ADC_SOURCE_COMMIT"}}{{index (split . "=") 1}}{{end}}{{end}}'
INSPECT = ('{{.Id}}|{{index .Config.Labels "' + LABEL + 'project"}}|'
           '{{index .Config.Labels "' + LABEL + 'service"}}|{{.Image}}|'
           '{{.State.Status}}|{{.State.ExitCode}}|{{.State.OOMKilled}}|'
           '{{.RestartCount}}|{{.State.StartedAt}}|'
           '{{if index .State "Health"}}{{index (index .State "Health") "Status"}}{{else}}none{{end}}|' + SOURCE)
EVENT_FORMAT = ('{{.TimeNano}}|{{.Action}}|{{.Actor.ID}}|'
                '{{index .Actor.Attributes "' + LABEL + 'service"}}')


def clock():
    return {'utc': time.time(), 'mono': time.monotonic()}


def elapsed(old, now):
    wall, mono = now['utc'] - old['utc'], now['mono'] - old['mono']
    if min(wall, mono) < 0 or abs(wall - mono) > 300:
        raise ValueError('Host clock changed; observations are not continuous.')
    return max(wall, mono)


def run(target, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('DOCKER_', 'COMPOSE_'))}
    completed = subprocess.run([target['docker'], '--context', target['context'], *args],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        check=True, timeout=15)
    if len(completed.stdout) > 256 * 1024:
        raise ValueError('Host projection exceeds its bound.')
    return completed.stdout.strip()


def docker_sample(target, since, until):
    endpoint = run(target, 'context', 'inspect', target['context'], '--format', '{{.Endpoints.docker.Host}}')
    if not endpoint.startswith('unix://'):
        raise ValueError('Only the explicit local Docker endpoint is supported.')
    ids = run(target, 'ps', '-aq', '--no-trunc', '--filter', 'label=' + LABEL + 'project=' + target['project'],
              '--filter', 'label=' + LABEL + 'oneoff=False').splitlines()
    if len(ids) > 32 or any(not re.fullmatch('[a-f0-9]{64}', x) for x in ids):
        raise ValueError('Unexpected instance containers.')
    rows = []
    if ids:
        for line in run(target, 'inspect', '--format', INSPECT, *ids).splitlines():
            cid, project, service, image, phase, exit_code, oom, restarts, started, health, source = line.split('|')
            if project != target['project'] or service not in SERVICES:
                continue  # Maintenance/one-off services never establish runtime health.
            if service in APP_SERVICES and source != target['source']:
                raise ValueError('Application source differs from the registered host target.')
            rows.append(dict(id=cid, service=service, image=image, phase=phase,
                exit_code=int(exit_code), oom=oom == 'true', restarts=int(restarts),
                started=started, health=health))
    raw = run(target, 'events', '--since', str(since), '--until', str(until),
        '--filter', 'type=container', '--filter', 'label=' + LABEL + 'project=' + target['project'],
        '--format', EVENT_FORMAT).splitlines()
    events = []
    for line in raw:
        ns, action, cid, service = line.split('|')
        if action in EVENTS and service in SERVICES:
            events.append(dict(ns=int(ns), code=EVENTS[action], id=cid, service=service))
    return rows, events, len(raw) >= 256


class Journal:
    def __init__(self, directory):
        self.store = PrivateStore(directory)
        self.target = self.store.read('target.json')
        if (self.target.get('v') != 1 or not re.fullmatch(r'adc_[a-z0-9_]{1,80}', self.target['project'])
                or not re.fullmatch('[a-f0-9]{40}', self.target['source'])):
            raise ValueError('An identified host target is required.')

    def load(self):
        try:
            state = self.store.read('host.json')
        except FileNotFoundError:
            state = dict(v=1, target=self.target, sampled=None, cursor=None, containers=[],
                conditions={}, events=[], incidents=[], pruned_events=0, pruned_incidents=0)
        if state.get('v') != 1 or state.get('target') != self.target:
            raise ValueError('Host journal belongs to another target.')
        return state

    @staticmethod
    def event(state, code, service, now, **metadata):
        row = dict(code=code, service=service, at=now, **metadata)
        if row in state['events']:
            return
        state['events'].append(row)
        if len(state['events']) > 192:
            state['events'].pop(0)
            state['pruned_events'] += 1

    def condition(self, state, service, severity, code, now, *, incident=True):
        old = state['conditions'].get(service, {})
        good = min(2, old.get('good', 0) + 1) if severity == 'HEALTHY' else 0
        state['conditions'][service] = dict(state=severity, reason=code, good=good)
        if not incident or severity == 'HEALTHY':
            return
        active = next((i for i in state['incidents'] if i['service'] == service and i['closed'] is None), None)
        if active is None:
            active = dict(id=uuid4().hex, service=service, opened=now, code=code,
                severity=severity, acknowledged_by='', acknowledged_at=None, actions=[], closed=None)
            state['incidents'].append(active)
        elif SEVERITY[severity] > SEVERITY[active['severity']] or code == 'CONTAINER_OOM':
            active.update(code=code, severity=severity)
        if len(state['incidents']) > 64:
            index = next(i for i, row in enumerate(state['incidents']) if row['closed'] is not None)
            del state['incidents'][index]
            state['pruned_incidents'] += 1

    def collect(self, *, sample=docker_sample, now=None, locked=False):
        now = now or clock()
        with (nullcontext() if locked else self.store.lock('collector.lock')):
            with self.store.lock('state.lock'):
                state = self.load()
                gap = False
                if state['sampled']:
                    try:
                        duration = elapsed(state['sampled'], now)
                        if duration == 0:
                            raise RuntimeError('A repeated sample cannot establish recovery.')
                        gap = duration > 90
                    except ValueError:
                        gap = True
                until = int(now['utc']) - 1
                since = max(until - 90, (state['cursor'] or until) - 1)
                try:
                    containers, events, saturated = sample(self.target, since, until)
                    gap = gap or saturated
                except (OSError, ValueError, subprocess.SubprocessError):
                    self.condition(state, 'collector', 'UNKNOWN', 'COLLECTOR_UNAVAILABLE', now)
                    previous = state['events'][-1:]  # Avoid appending unchanged polling failures.
                    if not previous or previous[0]['code'] != 'COLLECTOR_UNAVAILABLE':
                        self.event(state, 'COLLECTOR_UNAVAILABLE', 'collector', now)
                    self.store.write('host.json', state)
                    return self.status(state=state, now=now)
                if gap:
                    self.condition(state, 'collector', 'UNKNOWN', 'COLLECTION_GAP', now)
                    self.event(state, 'COLLECTION_GAP', 'collector', now)
                else:
                    self.condition(state, 'collector', 'HEALTHY', 'COLLECTOR_READY', now)
                for service in SERVICES:
                    found = [c for c in containers if c['service'] == service]
                    if len(found) != 1:
                        self.condition(state, service, 'UNKNOWN', 'CONTAINER_MISSING_OR_AMBIGUOUS', now)
                        continue
                    row = found[0]
                    good = row['phase'] == 'running' and row['health'] in ('none', 'healthy')
                    self.condition(state, service, 'HEALTHY' if good else 'CRITICAL',
                        'CONTAINER_READY' if good else 'CONTAINER_NOT_READY', now)
                    old = next((c for c in state['containers'] if c['service'] == service), None)
                    code = ('CONTAINER_OOM' if row['oom'] else
                        'CONTAINER_RECREATED' if old and old['id'] != row['id'] else
                        'CONTAINER_RESTARTED' if old and (old['restarts'] < row['restarts'] or
                            old['started'] != row['started']) else None)
                    if code and (not old or row != old):
                        self.event(state, code, service, now, container=row['id'])
                        self.condition(state, service, 'CRITICAL' if code == 'CONTAINER_OOM' else 'WARNING', code, now)
                for event in events:
                    # Stable daemon timestamp and ID deduplicate the overlapping query.
                    known = any(e.get('daemon_ns') == event['ns'] and e.get('container') == event['id']
                                and e['code'] == event['code'] for e in state['events'])
                    if known:
                        continue
                    self.event(state, event['code'], event['service'], now,
                               container=event['id'], daemon_ns=event['ns'])
                    severity = 'CRITICAL' if event['code'] == 'CONTAINER_OOM' else 'WARNING'
                    previous = dict(state['conditions'][event['service']])
                    self.condition(state, event['service'], severity, event['code'], now)
                    if SEVERITY[previous['state']] > SEVERITY[severity]:
                        state['conditions'][event['service']] = previous
                state.update(sampled=now, cursor=until, containers=containers)
                self.store.write('host.json', state)
                return self.status(state=state, now=now)

    def status(self, *, state=None, now=None):
        now, state = now or clock(), state if state is not None else self.load()
        conditions = dict(state['conditions'])
        try:
            if state['sampled'] is None or elapsed(state['sampled'], now) > 90:
                raise ValueError('No fresh host sample.')
        except ValueError:
            conditions['collector'] = dict(state='UNKNOWN', reason='COLLECTOR_STALE_OR_CLOCK', good=0)
        active = [i for i in state['incidents'] if i['closed'] is None]
        severity = max([v['state'] for v in conditions.values()] + [i['severity'] for i in active],
                       key=SEVERITY.__getitem__, default='UNKNOWN')
        return dict(v=1, state=severity, code=SEVERITY[severity], project=self.target['project'],
            source=self.target['source'], sampled=state['sampled'], conditions=conditions,
            active_incidents=active, retained_incidents=len(state['incidents']),
            retained_events=len(state['events']), pruned_events=state['pruned_events'])

    def handle(self, incident_id, operator, action=None, close=False, now=None):
        if not re.fullmatch('[A-Za-z0-9_.-]{1,40}', operator):
            raise ValueError('Use a private operator code.')
        now = now or clock()
        with self.store.lock('state.lock'):
            state = self.load()
            incident = next((i for i in state['incidents'] if i['id'] == incident_id and i['closed'] is None), None)
            if incident is None or incident['acknowledged_by'] not in ('', operator):
                raise ValueError('Active incident or assigned responsibility differs.')
            if action and action not in ACTIONS:
                raise ValueError('Unknown incident action.')
            if close:
                condition = self.status(state=state, now=now)['conditions'].get(incident['service'], {})
                if (not incident['acknowledged_by'] or not incident['actions'] or
                        condition.get('state') != 'HEALTHY' or condition.get('good', 0) < 2 or
                        self.status(state=state, now=now)['conditions']['collector']['state'] != 'HEALTHY'):
                    raise ValueError('Acknowledge, record action and verify fresh recovery before closure.')
                incident['closed'] = now
            if not incident['acknowledged_by']:
                incident['acknowledged_by'], incident['acknowledged_at'] = operator, now
            if action and action not in [r['code'] for r in incident['actions']]:
                incident['actions'].append(dict(code=action, at=now))
            self.store.write('host.json', state)
        return dict(event='INCIDENT_CLOSED' if close else 'INCIDENT_ACTION_RECORDED', incident=incident_id)

    def backup(self, success, now=None):
        now = now or clock()
        with self.store.lock('state.lock'):
            state = self.load()
            code = 'BACKUP_COMPLETED' if success else 'BACKUP_FAILED'
            self.event(state, code, 'backup', now)
            self.condition(state, 'backup', 'HEALTHY' if success else 'CRITICAL', code, now)
            if success:
                state['conditions']['backup']['good'] = 2  # One completed encrypted backup is the recovery fact.
            self.store.write('host.json', state)


def backup_event(bundle, project, source, success):
    """Optional host diagnostic; failure here cannot discard a completed backup."""
    directory = Path(bundle) / 'private/host-events'
    if not (directory / 'target.json').exists():
        return 'NOT_CONFIGURED'
    try:
        journal = Journal(directory)
        if (journal.target['project'], journal.target['source']) != (project, source):
            raise ValueError('Backup source differs from host target.')
        journal.backup(success)
        return 'RECORDED'
    except (OSError, ValueError):
        return 'UNAVAILABLE'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    init.add_argument('--project', required=True)
    init.add_argument('--source', required=True)
    init.add_argument('--context', required=True)
    init.add_argument('--docker', default='docker')
    for name in ('collect', 'watch', 'status', 'history'):
        sub.add_parser(name)
    for name in ('ack', 'action', 'close'):
        command = sub.add_parser(name)
        command.add_argument('incident')
        command.add_argument('--operator-code', required=True)
        if name == 'action':
            command.add_argument('--action', choices=ACTIONS, required=True)
    args = parser.parse_args()
    if args.command == 'init':
        store = PrivateStore(args.directory)
        if (store.directory / 'target.json').exists():
            raise ValueError('This host journal is already registered; retain its history.')
        if not re.fullmatch(r'adc_[a-z0-9_]{1,80}', args.project) or not re.fullmatch('[a-f0-9]{40}', args.source):
            raise ValueError('Explicit instance and source commit are required.')
        target = dict(v=1, project=args.project, source=args.source, context=args.context, docker=args.docker)
        store.write('target.json', target)
        print(json.dumps(dict(event='HOST_TARGET_REGISTERED', project=args.project)))
        return
    if args.command == 'status':
        try:
            result = Journal(args.directory).status()
        except (OSError, ValueError, KeyError):
            result = dict(v=1, state='UNKNOWN', code=3, reason='HOST_JOURNAL_UNAVAILABLE')
        print(json.dumps(result, indent=2))
        raise SystemExit(result['code'])
    journal = Journal(args.directory)
    if args.command == 'watch':
        with journal.store.lock('collector.lock'):
            while True:
                journal.collect(locked=True)
                time.sleep(30)
    if args.command == 'collect':
        result = journal.collect()
    elif args.command == 'status':
        result = journal.status()
    elif args.command == 'history':
        result = journal.load()
    else:
        result = journal.handle(args.incident, args.operator_code, getattr(args, 'action', None), args.command == 'close')
    print(json.dumps(result, indent=2))
    if args.command in ('collect', 'status'):
        raise SystemExit(result['code'])


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
        raise SystemExit('Host operation unavailable/refused. Retain private history and inspect the runbook.') from None
