"""Check probe freshness from a scheduler independent of the journey process."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.g4_course import exclusive, private_directory, private_file
from scripts.g4_mac_demo import atomic_text
from scripts.g4_patient_probe import MAX_START_DELAY_MS
from scripts.recovery_receipts import instant, utc_now


def heartbeat(receipt, now):
    try:
        data = json.loads(private_file(receipt).read_text())
        interval, expected = data['interval_seconds'], data['expected_samples']
        rows, summary = data['samples'], data['summary']
        if (type(interval) is not int or not 1 <= interval <= 60 or type(expected) is not int
                or expected < 1 or not isinstance(rows, list) or len(rows) > expected
                or summary['samples'] != len(rows) or summary['expected'] != expected):
            raise ValueError('Invalid probe receipt.')
        started = instant(data['started_at'])
        last = instant(rows[-1]['at']) if rows else started
        elapsed = (now - last).total_seconds()
        grace = MAX_START_DELAY_MS / 1000
        if elapsed < -grace or (started - last).total_seconds() > grace:
            raise ValueError('Inconsistent probe clock.')
        if len(rows) == expected and summary['state'] in ('PASS', 'FAIL'):
            return {'state': 'FINISHED', 'observation': summary['state']}
        if summary['state'] != 'INCOMPLETE':
            raise ValueError('Invalid probe completion.')
        return {'state': 'STALE' if elapsed > 2 * interval + grace else 'FRESH'}
    except (OSError, KeyError, TypeError, ValueError):
        return {'state': 'UNAVAILABLE'}


def check(receipt, state, now=None):
    now = utc_now() if now is None else now
    if receipt.resolve() == state.resolve():
        raise ValueError('Use separate observation and heartbeat state files.')
    private_directory(state.parent)
    with exclusive(state.with_name(state.name + '.lock')):
        previous = False
        if state.exists() or state.is_symlink():
            previous = json.loads(private_file(state).read_text())['incident_open']
            if type(previous) is not bool:
                raise ValueError('Invalid heartbeat state.')
        result = heartbeat(receipt, now)
        incident = result['state'] in ('STALE', 'UNAVAILABLE')
        result.update(signal='PROBE_HEARTBEAT', incident_open=incident, at=now.isoformat())
        if previous != incident:
            result['event'] = 'OPENED' if incident else 'RECOVERED'
        atomic_text(state, json.dumps(result) + '\n')
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = check(args.receipt, args.state)
    except (OSError, KeyError, TypeError, ValueError):
        print('Heartbeat check stopped. Check the private state path.', file=sys.stderr)
        return 2
    print(json.dumps(result))
    return int(result['incident_open'])


if __name__ == '__main__':
    raise SystemExit(main())
