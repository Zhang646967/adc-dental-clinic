"""Read-only resource/DB/HTTPS observation of the explicit writable course target."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.g4_course import Course, run
from scripts.g4_mac_demo import atomic_text
from scripts.g4_observe import DATABASE_SAMPLE, memory_bytes


def sample(course):
    values = {}
    containers = {}
    for service in ('db', 'web', 'notification-worker', 'gateway'):
        cid = course.dc('ps', '-q', service).decode().strip()
        if not cid:
            raise ValueError('Missing course service during observation.')
        raw = json.loads(run(course.docker + ['inspect', cid], course.log))[0]
        expected = course.plan['images']['app' if service in ('web', 'notification-worker')
                                      else 'db' if service == 'db' else 'nginx']
        labels = raw['Config']['Labels']
        if (labels.get('com.docker.compose.project') != course.plan['project'] or
                labels.get('com.docker.compose.service') != service or raw['Config']['Image'] != expected):
            raise ValueError('Observed service identity differs.')
        state = raw['State']
        values[service] = {'running': state['Running'], 'oom_killed': state['OOMKilled'],
                           'restart_count': raw['RestartCount'], 'started_at': state['StartedAt'],
                           'health': state.get('Health', {}).get('Status')}
        containers[service] = cid
    stats = run(course.docker + ['stats', '--no-stream', '--format', '{{json .}}'] + list(containers.values()),
                course.log).decode()
    for line in stats.splitlines():
        row = json.loads(line)
        name = next(n for n, cid in containers.items() if cid.startswith(row['ID']))
        values[name] |= {'cpu_percent': float(row['CPUPerc'].rstrip('%')),
                        'memory_bytes': memory_bytes(row['MemUsage'].split('/')[0])}
    script = DATABASE_SAMPLE.replace("assert settings.ADC_READ_ONLY and connection.vendor=='postgresql'",
            "assert not settings.ADC_READ_ONLY and connection.vendor=='postgresql'\n"
            "assert os.environ.get('ADC_COURSE_PROJECT')==" + repr(course.plan['project']))
    db = json.loads(run(course.docker + ['exec', '-i', containers['web'], 'python', '-'], course.log,
                       input_file=script.encode()))
    return {'at': datetime.now(timezone.utc).isoformat(), 'services': values, 'database': db,
            'origin_https': course.status()['origin_trusted_https']}


def summarize(rows):
    if not rows or any('error' in row for row in rows):
        return {'passed': False, 'reason': 'Failed/missing observation retained'}
    services = {}
    for service in ('db', 'web', 'notification-worker', 'gateway'):
        values = [r['services'][service] for r in rows]
        services[service] = {
            'healthy': all(v['running'] and (service == 'notification-worker' or v['health'] == 'healthy') for v in values),
            'oom': any(v['oom_killed'] for v in values),
            'restart_unchanged': len({(v['restart_count'], v['started_at']) for v in values}) == 1,
            'peak_memory_mib': round(max(v['memory_bytes'] for v in values) / 1024**2, 3)}
    memories = [r['services']['web']['memory_bytes'] for r in rows]
    window = max(1, len(rows) // 4)
    growth = (statistics.median(memories[-window:]) - statistics.median(memories[:window])) / 1024**2
    database = [r['database'] for r in rows]
    passed = (all(v['healthy'] and not v['oom'] and v['restart_unchanged'] for v in services.values())
              and all(r['origin_https'] for r in rows) and growth <= 64
              and all(v['idle_in_transaction'] == 0 and v['waiting_locks'] == 0 and
                      v['app_connections'] <= min(20, v['max_connections']) for v in database))
    return {'passed': passed, 'samples': len(rows), 'services': services,
            'web_median_growth_mib': round(growth, 3), 'max_growth_mib': 64,
            'peak_app_connections': max(v['app_connections'] for v in database),
            'idle_transaction_observed': any(v['idle_in_transaction'] for v in database),
            'waiting_lock_observed': any(v['waiting_locks'] for v in database),
            'memory_leak_absence_proven': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--docker', default='docker')
    parser.add_argument('--context', required=True)
    parser.add_argument('--rehearsal', action='store_true')
    parser.add_argument('--architecture', choices=('amd64', 'arm64'), default='amd64')
    parser.add_argument('--ca-file')
    parser.add_argument('--duration', type=int, default=86400)
    parser.add_argument('--interval', type=int, default=60)
    args = parser.parse_args()
    if not (30 <= args.duration <= 86400 and 10 <= args.interval <= 60):
        raise ValueError('Use a bounded observation up to 24 hours.')
    course = Course(args.output, args.docker, args.context, rehearsal=args.rehearsal,
                    architecture=args.architecture, ca_file=args.ca_file)
    rows, start = [], time.monotonic()
    while True:
        try:
            rows.append(sample(course))
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
            rows.append({'at': datetime.now(timezone.utc).isoformat(), 'error': type(error).__name__})
        result = {'scope': 'origin observation; external reachability measured separately',
                  'elapsed_seconds': round(time.monotonic() - start, 3), 'project': course.plan['project'],
                  'rehearsal': course.rehearsal, 'rows': rows, 'summary': summarize(rows),
                  'public_acceptance_executed': False, 'course_online_readiness': 'NOT_GRANTED_BY_OBSERVATION_ALONE'}
        atomic_text(course.bundle / 'private/course-observation.json', json.dumps(result, indent=2) + '\n')
        if time.monotonic() - start >= args.duration:
            break
        time.sleep(min(args.interval, args.duration - (time.monotonic() - start)))
    print(json.dumps(result['summary']))
    return 0 if result['summary']['passed'] else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
        raise SystemExit('Course observation stopped; no target acceptance granted.') from None
