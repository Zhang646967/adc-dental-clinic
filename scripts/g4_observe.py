"""Bounded Mac G4 resource/health sampling; explicit local Docker target only.

No container restart, schema/business write, credentials or raw query/log export.
Worker PID changes are observed independently of container restart counts.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.g4_mac_demo import DOCKER, atomic_text, checked_bundle, check_origin, compose_command
from scripts.g4_load import private_path

DATABASE_SAMPLE = '''
import json,os
import django
django.setup()
from django.conf import settings
from django.db import connection,transaction
assert settings.ADC_READ_ONLY and connection.vendor=='postgresql'
assert connection.settings_dict['NAME']=='adc_rc_demo'
assert connection.settings_dict['USER']=='adc_g4_runtime'
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
        cursor.execute("SELECT count(*), count(*) FILTER (WHERE state='idle in transaction') FROM pg_stat_activity WHERE datname=current_database() AND usename=current_user")
        total,idle=cursor.fetchone()
        cursor.execute("SELECT count(*) FROM pg_locks WHERE NOT granted AND database=(SELECT oid FROM pg_database WHERE datname=current_database())")
        waiting=cursor.fetchone()[0]
        cursor.execute('SHOW max_connections')
        maximum=int(cursor.fetchone()[0])
processes={}
for name in os.listdir('/proc'):
    if name.isdigit():
        try:
            text=open('/proc/'+name+'/cmdline','rb').read()
            stat=open('/proc/'+name+'/stat').read().rsplit(')',1)[1].split()
            if b'gunicorn' in text:
                processes[int(name)]=int(stat[1])
        except (OSError,IndexError,ValueError):
            pass
# docker-init also contains the launch command; only leaf Gunicorn children
# are workers. The master has worker children and must not count as recycling.
workers=sorted(pid for pid,parent in processes.items() if parent in processes and pid not in processes.values())
print(json.dumps({'app_connections':total,'idle_in_transaction':idle,
                  'waiting_locks':waiting,'max_connections':maximum,'worker_pids':workers}))
connection.close()
'''


def memory_bytes(text):
    match = re.fullmatch(r'([0-9.]+)\s*(B|kB|MB|GB|KiB|MiB|GiB)', text.strip())
    units = {'B': 1, 'kB': 1000, 'MB': 1000**2, 'GB': 1000**3,
             'KiB': 1024, 'MiB': 1024**2, 'GiB': 1024**3}
    if not match:
        raise ValueError('Unknown Docker memory unit.')
    return round(float(match[1]) * units[match[2]])


def docker(*args, **kwargs):
    result = subprocess.run([DOCKER, '--context', 'desktop-linux', *args],
                            capture_output=True, text=True, check=True, timeout=20, **kwargs)
    return result.stdout


def targets(bundle, plan):
    command = compose_command(bundle, plan)
    selected = {}
    for service in ('db', 'web', 'gateway'):
        result = subprocess.run(command + ['ps', '-q', service], capture_output=True,
                                text=True, check=True, timeout=20)
        cid = result.stdout.strip()
        if not re.fullmatch('[a-f0-9]{64}', cid):
            raise ValueError('Exactly one existing container per reviewed service is required.')
        item = json.loads(docker('inspect', cid))[0]
        labels = item['Config']['Labels']
        image = plan['images']['app' if service == 'web' else ('nginx' if service == 'gateway' else 'db')]
        if (labels.get('com.docker.compose.project') != plan['project'] or
                labels.get('com.docker.compose.service') != service or item['Config']['Image'] != image):
            raise ValueError('Actual service identity/image differs from the explicit bundle.')
        selected[service] = cid
    return selected


def sample(plan, selected):
    result = {'recorded_at_utc': datetime.now(timezone.utc).isoformat(), 'services': {}}
    for service, cid in selected.items():
        # Filter before returning: never export container environment/inspect data.
        raw = json.loads(docker('inspect', cid))[0]
        labels = raw['Config']['Labels']
        if labels.get('com.docker.compose.project') != plan['project']:
            raise ValueError('Container ownership changed during observation.')
        state = raw['State']
        result['services'][service] = {'running': state['Running'], 'oom_killed': state['OOMKilled'],
                                      'restart_count': raw['RestartCount'],
                                      'started_at': state['StartedAt'],
                                      'health': state.get('Health', {}).get('Status')}
    stats = docker('stats', '--no-stream', '--format', '{{json .}}', *selected.values())
    for line in stats.splitlines():
        row = json.loads(line)
        service = next(name for name, cid in selected.items() if cid.startswith(row['ID']))
        result['services'][service] |= {'cpu_percent': float(row['CPUPerc'].rstrip('%')),
                                       'memory_bytes': memory_bytes(row['MemUsage'].split('/')[0])}
    result['database'] = json.loads(docker('exec', '-i', selected['web'], 'python', '-', input=DATABASE_SAMPLE))
    check_origin(plan['host'], plan['ports'][0])
    result['origin_health'] = 'PASS'
    return result


def summarize(samples):
    if not samples or any(row.get('sampling_error') for row in samples):
        return {'passed': False, 'reason': 'Missing/failed observation retained'}
    service_results = {}
    for service in ('db', 'web', 'gateway'):
        rows = [sample['services'][service] for sample in samples]
        service_results[service] = {'health_always_ready': all(r['running'] and r['health'] == 'healthy' for r in rows),
                                   'oom_observed': any(r['oom_killed'] for r in rows),
                                   'restart_count_unchanged': len({r['restart_count'] for r in rows}) == 1,
                                   'container_start_unchanged': len({r['started_at'] for r in rows}) == 1,
                                   'peak_cpu_percent': max(r['cpu_percent'] for r in rows),
                                   'peak_memory_mib': round(max(r['memory_bytes'] for r in rows) / 1024**2, 3)}
    memories = [row['services']['web']['memory_bytes'] for row in samples]
    window = max(1, len(memories) // 4)
    growth = (statistics.median(memories[-window:]) - statistics.median(memories[:window])) / 1024**2
    db = [row['database'] for row in samples]
    worker_pids = {pid for row in db for pid in row['worker_pids']}
    passed = (all(r['health_always_ready'] and not r['oom_observed'] and r['restart_count_unchanged']
                  and r['container_start_unchanged'] for r in service_results.values()) and
              all(row['origin_health'] == 'PASS' for row in samples) and growth <= 64 and
              all(row['idle_in_transaction'] == 0 and row['waiting_locks'] == 0 and
                  row['app_connections'] <= min(20, row['max_connections']) for row in db))
    return {'passed': passed, 'services': service_results, 'samples': len(samples),
            'web_first_to_last_quarter_median_growth_mib': round(growth, 3),
            'max_allowed_growth_mib': 64, 'peak_app_connections': max(row['app_connections'] for row in db),
            'idle_in_transaction_observed': any(row['idle_in_transaction'] for row in db),
            'waiting_lock_observed': any(row['waiting_locks'] for row in db),
            'distinct_worker_pids_observed': len(worker_pids),
            'worker_recycling_observed': len(worker_pids) > 2,
            'memory_leak_absence_proven': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / '.g4'))
    parser.add_argument('--report', default='stability-observation.json')
    parser.add_argument('--duration', type=int, default=630)
    parser.add_argument('--interval', type=int, default=15)
    args = parser.parse_args()
    bundle = Path(args.output).resolve()
    try:
        if not (30 <= args.duration <= 1800 and 10 <= args.interval <= 60):
            raise ValueError('Use bounded observation duration/interval.')
        plan = checked_bundle(bundle)
        path = private_path(bundle, args.report)
        selected = targets(bundle, plan)
        rows = []
        start = time.monotonic()
        while True:
            try:
                rows.append(sample(plan, selected))
            except Exception as error:
                rows.append({'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
                             'sampling_error': type(error).__name__})
            report = {'scope': 'Bounded observation of selected existing synthetic G4 containers',
                      'project': plan['project'], 'elapsed_seconds': round(time.monotonic() - start, 3),
                      'samples': rows, 'summary': summarize(rows), 'full_G4_accepted': False}
            atomic_text(path, json.dumps(report, indent=2) + '\n')
            if time.monotonic() - start >= args.duration:
                break
            time.sleep(min(args.interval, args.duration - (time.monotonic() - start)))
        print(json.dumps(report['summary']))
        return 0 if report['summary']['passed'] else 1
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print('Observation stopped. Preserve private evidence; no services/data were changed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
