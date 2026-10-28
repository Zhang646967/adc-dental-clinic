"""Private condition reporting, distinct from business authority and audit.

Only finite technical codes and aggregate values belong in these files. Acknowledging
an incident records responsibility; only two new good samples recover a condition.
"""
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import re
import time
from uuid import uuid4
from adc_core.operations_store import PrivateStore

STATES = {'HEALTHY': 0, 'WARNING': 1, 'CRITICAL': 2, 'UNKNOWN': 3}
CONDITIONS = ('database', 'web', 'worker', 'backlog', 'failed_delivery', 'storage')
MAX_INCIDENTS = 128
MAX_HISTORY = 16
REASONS = frozenset(('NOT_REQUIRED','WORKER_STOPPED','WORKER_FAILED','WORKER_STALE',
    'NO_SUCCESSFUL_LOOP','WORKER_NO_DB_PROGRESS','CURRENT_DB_LOOP','WORKER_OBSERVATION_INVALID',
    'DATABASE_UNAVAILABLE','DATABASE_READY','DUE_BACKLOG_OLD','NO_OVERDUE_WORK',
    'FAILED_DELIVERY_REVIEW','NO_FAILED_DELIVERY','WEB_READY','WEB_UNAVAILABLE',
    'STORAGE_CRITICAL','STORAGE_LOW','STORAGE_READY','SOURCE_UNIDENTIFIED',
    'AWAITING_SAMPLE','AWAITING_SECOND_FAILURE','AWAITING_SECOND_SUCCESS'))


def clock():
    return {'utc': datetime.now(timezone.utc).timestamp(), 'mono': time.monotonic(),
            'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def identity():
    instance = os.environ.get('ADC_OPERATIONS_INSTANCE', '')
    source = os.environ.get('ADC_SOURCE_COMMIT', 'unknown')
    if not re.fullmatch(r'adc_[a-z0-9_]{1,80}', instance):
        raise ValueError('Explicit operational instance is required.')
    if source != 'unknown' and not re.fullmatch(r'[a-f0-9]{40}', source):
        raise ValueError('Invalid application source identity.')
    return {'instance': instance, 'source': source, 'read_only': os.environ.get('ADC_READ_ONLY', '1') != '0'}


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def valid_clock(value):
    return (isinstance(value, dict) and set(value) == {'utc', 'mono', 'boot'} and
            number(value['utc']) and number(value['mono']) and
            isinstance(value['boot'], str) and re.fullmatch(r'[a-f0-9-]{36}', value['boot']) is not None)


def age(value, now):
    if not valid_clock(value) or not valid_clock(now) or value['boot'] != now['boot']:
        raise ValueError('Invalid clock or different boot.')
    wall, monotonic = now['utc'] - value['utc'], now['mono'] - value['mono']
    if wall < 0 or monotonic < 0 or abs(wall - monotonic) > 300:
        raise ValueError('Clock inconsistency.')
    return max(wall, monotonic)


def verify_record(value, expected, kind):
    if (not isinstance(value, dict) or type(value.get('v')) is not int or value.get('v') != 1 or
            value.get('kind') != kind or not isinstance(value.get('identity'),dict) or
            set(value['identity']) != {'instance','source','read_only'} or
            type(value['identity']['read_only']) is not bool or
            value['identity'] != expected or not valid_clock(value.get('at'))):
        raise ValueError('Operational record identity/schema differs.')


class Heartbeat:
    def __init__(self, directory, target):
        self.store = PrivateStore(directory)
        self.target = target
        self.run = uuid4().hex
        self.sequence = 0
        self.last_success = None
        self.last_delivery = None

    def write(self, phase, *, delivered=False):
        if phase not in ('starting', 'polling', 'success', 'failed', 'stopped'):
            raise ValueError('Invalid worker phase.')
        now = clock()
        if phase == 'success':
            self.last_success = now
            if delivered:
                self.last_delivery = now
        self.sequence += 1
        self.store.write('heartbeat.json', {'v': 1, 'kind': 'worker', 'identity': self.target,
            'at': now, 'run': self.run, 'sequence': self.sequence, 'phase': phase,
            'last_success': self.last_success, 'last_delivery': self.last_delivery})


def worker_condition(record, target, now):
    if target['read_only']:
        return 'HEALTHY', 'NOT_REQUIRED'
    try:
        verify_record(record, target, 'worker')
        if set(record) != {'v', 'kind', 'identity', 'at', 'run', 'sequence', 'phase', 'last_success', 'last_delivery'}:
            raise ValueError('Invalid heartbeat fields.')
        if not re.fullmatch(r'[a-f0-9]{32}', record['run']) or type(record['sequence']) is not int or record['sequence'] < 1:
            raise ValueError('Invalid heartbeat sequence.')
        observed_age = age(record['at'], now)
        phase = record['phase']
        if phase not in ('starting', 'polling', 'success', 'failed', 'stopped'):
            raise ValueError('Invalid worker phase.')
        if record['last_delivery'] is not None:
            age(record['last_delivery'], record['at'])
        success = record['last_success']
        if success is not None and age(success, record['at']) < 0:
            raise ValueError('Invalid success time.')
        if phase in ('stopped', 'failed'):
            return 'CRITICAL', 'WORKER_STOPPED' if phase == 'stopped' else 'WORKER_FAILED'
        if observed_age > 90:
            return 'CRITICAL', 'WORKER_STALE'
        if success is None:
            return 'UNKNOWN', 'NO_SUCCESSFUL_LOOP'
        if age(success, now) > 90:
            return 'CRITICAL', 'WORKER_NO_DB_PROGRESS'
        return 'HEALTHY', 'CURRENT_DB_LOOP'
    except (ValueError, TypeError, KeyError):
        return 'UNKNOWN', 'WORKER_OBSERVATION_INVALID'


def conditions(sample, target, now):
    verify_record(sample, target, 'sample')
    if set(sample) != {'v','kind','identity','at','database','worker','web','storage'} or age(sample['at'], now) > 90:
        raise ValueError('Stale collector sample.')
    result = {}
    database = sample['database']
    if database is None:
        result.update(database=('CRITICAL', 'DATABASE_UNAVAILABLE'),
                      backlog=('UNKNOWN', 'DATABASE_UNAVAILABLE'),
                      failed_delivery=('UNKNOWN', 'DATABASE_UNAVAILABLE'))
    else:
        if set(database) != {'due', 'oldest_due_seconds', 'pending', 'failed', 'delivered', 'no_recipients'}:
            raise ValueError('Invalid aggregate fields.')
        if any(type(database[k]) is not int or database[k] < 0 for k in ('due', 'pending', 'failed', 'delivered', 'no_recipients')):
            raise ValueError('Invalid aggregate count.')
        if not number(database['oldest_due_seconds']) or database['due'] > database['pending']:
            raise ValueError('Invalid due age/count.')
        result['database'] = ('HEALTHY', 'DATABASE_READY')
        due_age = database['oldest_due_seconds'] + (age(sample['at'], now) if database['due'] else 0)
        result['backlog'] = ('WARNING', 'DUE_BACKLOG_OLD') if due_age > 120 else ('HEALTHY', 'NO_OVERDUE_WORK')
        result['failed_delivery'] = ('WARNING', 'FAILED_DELIVERY_REVIEW') if database['failed'] else ('HEALTHY', 'NO_FAILED_DELIVERY')
    web = sample['web']
    if type(web) is not bool:
        raise ValueError('Invalid readiness.')
    result['web'] = ('HEALTHY', 'WEB_READY') if web else ('CRITICAL', 'WEB_UNAVAILABLE')
    result['worker'] = worker_condition(sample['worker'], target, now)
    disk = sample['storage']
    if (not isinstance(disk, dict) or set(disk) != {'total', 'free'} or
            type(disk['total']) is not int or type(disk['free']) is not int or
            not 0 <= disk['free'] <= disk['total'] or disk['total'] <= 0):
        raise ValueError('Invalid storage sample.')
    fraction = disk['free'] / disk['total']
    result['storage'] = (('CRITICAL', 'STORAGE_CRITICAL') if fraction < .10 or disk['free'] < 1024**3 else
                         ('WARNING', 'STORAGE_LOW') if fraction < .20 else ('HEALTHY', 'STORAGE_READY'))
    if target['source'] == 'unknown':
        result['worker'] = ('UNKNOWN', 'SOURCE_UNIDENTIFIED')
    return result


def fresh_state(target, now):
    return {'v': 1, 'kind': 'monitor', 'identity': target, 'at': now, 'run': uuid4().hex,
            'sequence': 0, 'sample': None, 'conditions': {}, 'incidents': [], 'pruned_incidents': 0}


def clock_discontinuity(state, target, now):
    """Identify only a forward wall/monotonic gap in an otherwise valid state.

    A collector may archive this observation and start UNKNOWN. A foreign,
    malformed, backwards or different-boot record is not a repair candidate.
    """
    verify_state(state, target)
    old = (state.get('sample') or {}).get('at', state['at'])
    if not valid_clock(old) or not valid_clock(now) or old['boot'] != now['boot']:
        return False
    wall, mono = now['utc'] - old['utc'], now['mono'] - old['mono']
    return wall > 0 and mono > 0 and abs(wall - mono) > 300


def verify_state(state, target):
    verify_record(state, target, 'monitor')
    if (set(state) != {'v','kind','identity','at','run','sequence','sample','conditions','incidents','pruned_incidents'} or
            not isinstance(state['incidents'], list) or len(state['incidents']) > MAX_INCIDENTS or
            type(state['sequence']) is not int or state['sequence'] < 0 or
            not re.fullmatch(r'[a-f0-9]{32}', state['run']) or
            type(state['pruned_incidents']) is not int or state['pruned_incidents'] < 0 or
            not isinstance(state['conditions'], dict) or set(state['conditions']) - set(CONDITIONS)):
        raise ValueError('Invalid incident state.')
    for key, value in state['conditions'].items():
        if (set(value) != {'state', 'reason', 'good', 'bad', 'incident'} or
                value['state'] not in STATES or type(value['good']) is not int or
                value['reason'] not in REASONS or type(value['bad']) is not int or
                not 0 <= value['good'] <= 2 or not 0 <= value['bad'] <= 2):
            raise ValueError('Invalid condition state.')
    ids = set()
    for incident in state['incidents']:
        if (set(incident) != {'id','condition','opened','recovered','acknowledged_by','history','pruned_history'} or
                not re.fullmatch(r'[a-f0-9]{32}', incident['id']) or incident['id'] in ids or
                incident['condition'] not in CONDITIONS or not valid_clock(incident['opened']) or
                (incident['recovered'] is not None and not valid_clock(incident['recovered'])) or
                not re.fullmatch(r'[A-Za-z0-9_.-]{0,40}', incident['acknowledged_by']) or
                type(incident['pruned_history']) is not int or incident['pruned_history'] < 0 or
                not isinstance(incident['history'], list) or not 1 <= len(incident['history']) <= MAX_HISTORY):
            raise ValueError('Invalid incident history.')
        ids.add(incident['id'])
        for event in incident['history']:
            if (set(event) != {'event','at','state'} or event['event'] not in ('opened','changed','acknowledged','recovered') or
                    event['state'] not in STATES or not valid_clock(event['at'])):
                raise ValueError('Invalid lifecycle event.')
    for key, value in state['conditions'].items():
        active = [i for i in state['incidents'] if i['condition'] == key and i['recovered'] is None]
        if len(active) > 1 or (value['incident'] != (active[0]['id'] if active else None)):
            raise ValueError('Incident/condition mismatch.')


def history(incident, event, now, state):
    incident['history'].append({'event': event, 'at': now, 'state': state})
    if len(incident['history']) > MAX_HISTORY:
        del incident['history'][1]
        incident['pruned_history'] += 1


def advance(state, sample, target, now):
    verify_state(state, target)
    observed = conditions(sample, target, now)
    if state['sequence']:
        old_worker, new_worker = state['sample']['worker'], sample['worker']
        if (isinstance(old_worker, dict) and isinstance(new_worker, dict) and
                old_worker.get('run') == new_worker.get('run') and
                (new_worker.get('sequence',0) < old_worker.get('sequence',0) or
                 (new_worker.get('sequence') == old_worker.get('sequence') and
                  new_worker.get('at') != old_worker.get('at')))):
            observed['worker'] = ('UNKNOWN','WORKER_OBSERVATION_INVALID')
        previous_at = state['sample']['at']
        current = sample['at']
        if current['utc'] <= previous_at['utc']:
            raise ValueError('A repeated sample cannot count toward recovery.')
        if previous_at['boot'] == current['boot']:
            if current['mono'] <= previous_at['mono']:
                raise ValueError('Observation regressed.')
            age(previous_at, current)
        else:
            for row in state['conditions'].values():
                row.update(good=0, bad=0)
    for key in CONDITIONS:
        status, reason = observed[key]
        old = state['conditions'].get(key, {'state': 'UNKNOWN', 'reason': 'AWAITING_SAMPLE', 'good': 0, 'bad': 0, 'incident': None})
        if key == 'storage' and old['state'] in ('WARNING','CRITICAL'):
            disk = sample['storage']
            fraction = disk['free'] / disk['total']
            if old['state'] == 'CRITICAL' and (fraction <= .15 or disk['free'] < 1280 * 1024**2):
                status, reason = 'CRITICAL', 'STORAGE_CRITICAL'
            elif fraction <= .25 and status == 'HEALTHY':
                status, reason = 'WARNING', 'STORAGE_LOW'
        old['good'] = min(2, old['good'] + 1) if status == 'HEALTHY' else 0
        old['bad'] = min(2, old['bad'] + 1) if status != 'HEALTHY' else 0
        # Database/readiness require two failures; never report the first failure healthy.
        if key in ('database','web') and status == 'CRITICAL' and old['bad'] < 2:
            status, reason = 'UNKNOWN', 'AWAITING_SECOND_FAILURE'
        elif status == 'HEALTHY' and old['state'] != 'HEALTHY' and old['good'] < 2:
            status, reason = 'UNKNOWN', 'AWAITING_SECOND_SUCCESS'
        incident = next((i for i in state['incidents'] if i['id'] == old['incident']), None)
        if status != 'HEALTHY' and incident is None and reason != 'AWAITING_SECOND_SUCCESS':
            incident = {'id': uuid4().hex, 'condition': key, 'opened': now, 'recovered': None,
                        'acknowledged_by': '', 'history': [], 'pruned_history': 0}
            state['incidents'].append(incident)
            old['incident'] = incident['id']
            history(incident, 'opened', now, status)
        elif incident and status == 'HEALTHY':
            incident['recovered'] = now
            history(incident, 'recovered', now, status)
            old['incident'] = None
        elif incident and status != old['state']:
            history(incident, 'changed', now, status)
        old.update(state=status, reason=reason)
        state['conditions'][key] = old
    while len(state['incidents']) > MAX_INCIDENTS:
        index = next(i for i, row in enumerate(state['incidents']) if row['recovered'] is not None)
        del state['incidents'][index]
        state['pruned_incidents'] += 1
    state.update(at=now, sample=sample, sequence=state['sequence'] + 1)
    verify_state(state, target)
    return state


def acknowledge(state, target, incident_id, operator, now):
    verify_state(state, target)
    age(state['at'], now)
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,40}', operator):
        raise ValueError('Use a private operator code, not personal/contact text.')
    incident = next((i for i in state['incidents'] if i['id'] == incident_id and i['recovered'] is None), None)
    if incident is None:
        raise ValueError('Active incident not found.')
    if not incident['acknowledged_by']:
        incident['acknowledged_by'] = operator
        history(incident, 'acknowledged', now, state['conditions'][incident['condition']]['state'])
    elif incident['acknowledged_by'] != operator:
        raise ValueError('Responsibility was already acknowledged.')
    return state


def status(state, target, now):
    try:
        verify_state(state, target)
        if state['sequence'] < 1 or age(state['at'], now) > 90:
            raise ValueError('Observer stale.')
        current = conditions(state['sample'], target, now)
        if set(state['conditions']) != set(CONDITIONS):
            raise ValueError('Incomplete conditions.')
        states = {k: dict(v) for k,v in state['conditions'].items()}
        # Reading cannot advance hysteresis, but an aged heartbeat/backlog must
        # not inherit a cached healthy result when the collector has just stopped.
        for key in ('worker','backlog'):
            observed, reason = current[key]
            if STATES[observed] > STATES[states[key]['state']]:
                states[key].update(state=observed, reason=reason)
        overall = max((v['state'] for v in states.values()), key=STATES.__getitem__)
        return {'v': 1, 'state': overall, 'code': STATES[overall], 'reason': 'OBSERVED',
                'instance': target['instance'], 'source': target['source'], 'observed_at': state['at']['utc'],
                'conditions': states, 'aggregates': state['sample']['database'],
                'active_incidents': [i for i in state['incidents'] if i['recovered'] is None],
                'retained_incidents': len(state['incidents']), 'pruned_incidents': state['pruned_incidents']}
    except (ValueError, TypeError, KeyError):
        return {'v': 1, 'state': 'UNKNOWN', 'code': 3, 'reason': 'OBSERVER_UNAVAILABLE'}
