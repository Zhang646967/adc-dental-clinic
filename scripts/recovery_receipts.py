"""Private recovery observations. A receipt checksum is not publisher authentication.

No write/import CLI: only the backup/sync operations may record verified facts.
Independent restore remains UNKNOWN until a separate comparison is integrated.
Recovery-point time is immutable; checking/downloading a copy never refreshes it.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from adc_core.operations_store import PrivateStore

KINDS = ('created', 'downloaded', 'restored')
CODES = {'HEALTHY': 0, 'WARNING': 1, 'CRITICAL': 2, 'UNKNOWN': 3}
PROJECT = re.compile(r'adc_(?:g4|rc1)_[0-9a-f]{12}')
BACKUP = re.compile(r'backup-([0-9]{8}T[0-9]{12}Z)-(adc_(?:g4|rc1)_[0-9a-f]{12})\.tar\.age')
HEX = re.compile(r'[0-9a-f]{64}')
MAX_ARCHIVE = 514 * 1024 * 1024


def utc_now():
    return datetime.now(timezone.utc)


def instant(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('Invalid recovery time.')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, OverflowError):
        raise ValueError('Invalid recovery time.') from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('A timezone is required.')
    return result.astimezone(timezone.utc)


def age(value, now):
    seconds = (now - instant(value)).total_seconds()
    if seconds < -300:
        raise ValueError('Recovery clock is in the future.')
    return max(0, seconds)


def file_digest(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Recovery files cannot be symbolic links.')
    # Validate the opened file, including ownership, type, mode and hard links.
    import os
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        PrivateStore.check_file(info)
        if info.st_size > MAX_ARCHIVE:
            raise ValueError('Recovery file exceeds the course size bound.')
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def artifact(meta, row):
    """Use only after digest AND authenticated decryption/internal checks on Mac.

    On the server this establishes creation only, after successful encryption.
    Sidecar timestamps are untrusted until bound to the encrypted manifest.
    """
    result = {key: row[key] for key in ('name', 'project', 'created_at', 'size', 'sha256')}
    result.update(source_commit=meta['source_commit'], app_image=meta['images']['app'],
                  point_basis=meta.get('recovery_point_basis', 'LEGACY_ARCHIVE_CREATION'))
    validate_artifact(result)
    if (meta['project'] != result['project'] or
            instant(meta['created_at']) != instant(result['created_at'])):
        raise ValueError('Backup recovery point/provenance differs from its manifest.')
    return result


def validate_artifact(value):
    if not isinstance(value, dict) or set(value) != {
            'name', 'project', 'created_at', 'size', 'sha256', 'source_commit', 'app_image', 'point_basis'}:
        raise ValueError('Invalid recovery artifact fields.')
    match = BACKUP.fullmatch(value['name']) if isinstance(value['name'], str) else None
    if (not match or match[2] != value['project'] or
            not re.fullmatch(r'[0-9a-f]{40}', value['source_commit']) or
            not re.fullmatch(r'sha256:[0-9a-f]{64}', value['app_image']) or
            not HEX.fullmatch(value['sha256']) or type(value['size']) is not int or
            not 0 < value['size'] < MAX_ARCHIVE or
            value['point_basis'] not in ('BACKUP_START_CONSERVATIVE', 'LEGACY_ARCHIVE_CREATION')):
        raise ValueError('Invalid recovery artifact identity.')
    point = instant(value['created_at'])
    # Filenames retain the original UTC-day retention policy. Older archives
    # crossing midnight remain readable but cannot silently assert a new point.
    datetime.strptime(match[1], '%Y%m%dT%H%M%S%fZ')
    if point.strftime('%Y%m%d') != match[1][:8]:
        raise ValueError('Backup name and recovery-point UTC day differ.')


def validate_receipt(value, instance):
    if not isinstance(value, dict) or set(value) != {'kind', 'artifact', 'verified_at', 'key_sha256'}:
        raise ValueError('Invalid recovery receipt fields.')
    if value['kind'] not in ('created', 'downloaded'):
        raise ValueError('No independently compared restore receipt is implemented yet.')
    validate_artifact(value['artifact'])
    if value['artifact']['project'] != instance:
        raise ValueError('Foreign recovery instance.')
    instant(value['verified_at'])
    if instant(value['verified_at']) < instant(value['artifact']['created_at']):
        raise ValueError('Verification precedes the recovery point.')
    key = value['key_sha256']
    if (value['kind'] == 'created' and key is not None or
            value['kind'] == 'downloaded' and (not isinstance(key, str) or not HEX.fullmatch(key))):
        raise ValueError('Invalid recovery key evidence.')


class ReceiptBook:
    def __init__(self, directory, instance):
        if not isinstance(instance, str) or not PROJECT.fullmatch(instance):
            raise ValueError('An explicit recovery instance is required.')
        self.store = PrivateStore(directory)
        self.instance = instance

    def load(self):
        try:
            state = self.store.read('receipts.json')
        except FileNotFoundError:
            return {'v': 1, 'kind': 'recovery', 'instance': self.instance,
                    'latest': dict.fromkeys(KINDS), 'history': [], 'pruned_history': 0}
        if (not isinstance(state, dict) or set(state) != {
                'v', 'kind', 'instance', 'latest', 'history', 'pruned_history'} or
                type(state['v']) is not int or state['v'] != 1 or state['kind'] != 'recovery' or
                state['instance'] != self.instance or not isinstance(state['latest'], dict) or
                set(state['latest']) != set(KINDS) or not isinstance(state['history'], list) or
                len(state['history']) > 96 or type(state['pruned_history']) is not int or
                state['pruned_history'] < 0):
            raise ValueError('Recovery receipt schema/identity differs.')
        for kind, receipt in state['latest'].items():
            if receipt is not None:
                validate_receipt(receipt, self.instance)
                if receipt['kind'] != kind:
                    raise ValueError('Recovery receipt kind differs.')
        for receipt in state['history']:
            validate_receipt(receipt, self.instance)
        return state

    def record(self, kind, fact, *, key_sha256=None, now=None):
        now = now or utc_now()
        receipt = {'kind': kind, 'artifact': fact, 'verified_at': now.isoformat(),
                   'key_sha256': key_sha256}
        validate_receipt(receipt, self.instance)
        age(fact['created_at'], now)
        with self.store.lock('receipts.lock'):
            state = self.load()
            previous = state['latest'][kind]
            if previous is not None:
                old = previous['artifact']
                age(previous['verified_at'], now)
                if instant(fact['created_at']) < instant(old['created_at']):
                    return False  # An old download never moves the recovery point backwards.
                if instant(fact['created_at']) == instant(old['created_at']) and fact != old:
                    raise ValueError('Conflicting archive at the same recovery point.')
                if receipt == previous:
                    return False
            state['latest'][kind] = receipt
            state['history'].append(receipt)
            if len(state['history']) > 96:
                state['pruned_history'] += len(state['history']) - 96
                state['history'] = state['history'][-96:]
            self.store.write('receipts.json', state)
        return True

    def status(self, source, image, archive_directory, *, mode, identity_file=None, now=None):
        """No database, SSH, decryption, permission or business change here."""
        now = now or utc_now()
        result = {'v': 1, 'instance': self.instance, 'scope': 'PRIVATE_RECOVERY_OBSERVATIONS',
                  'conditions': {}, 'restore_acceptance': 'PENDING_R23_SECOND_INCREMENT',
                  'off_host_protection': 'last_verified_download; a sleeping Mac cannot guarantee daily copies'}
        if mode not in ('server', 'mac') or not re.fullmatch(r'[0-9a-f]{40}', source) or not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
            raise ValueError('Specify the reviewed application and observation location.')
        try:
            state = self.load()
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            state = None
        for kind in KINDS:
            condition = {'state': 'UNKNOWN', 'reason': 'NO_VERIFIED_RECEIPT'}
            receipt = state['latest'][kind] if state else None
            if receipt is not None:
                try:
                    fact = receipt['artifact']
                    seconds = age(fact['created_at'], now)
                    verification_age = age(receipt['verified_at'], now)
                    condition.update(recovery_point=fact['created_at'], age_seconds=round(seconds, 3),
                                     verified_at=receipt['verified_at'], sha256=fact['sha256'])
                    if fact['source_commit'] != source or fact['app_image'] != image:
                        raise ValueError('Receipt belongs to a different application.')
                    if fact['point_basis'] != 'BACKUP_START_CONSERVATIVE':
                        raise ValueError('Legacy archive time is not a verified data-capture point.')
                    path = Path(archive_directory) / fact['name']
                    if file_digest(path) != fact['sha256'] or path.stat().st_size != fact['size']:
                        raise ValueError('Recovery archive differs.')
                    if kind == 'downloaded' and (identity_file is None or file_digest(identity_file) != receipt['key_sha256']):
                        raise ValueError('Current decryption key differs or was not checked.')
                    condition.update(state='WARNING' if seconds > 26 * 3600 else 'HEALTHY',
                                     reason='RECOVERY_POINT_OLD' if seconds > 26 * 3600 else 'RECOVERY_POINT_CURRENT')
                    if kind == 'created' and mode == 'mac' and verification_age > 90:
                        condition.update(state='UNKNOWN', reason='SERVER_OBSERVATION_STALE')
                except (OSError, ValueError, TypeError, KeyError, OverflowError):
                    condition.update(state='UNKNOWN', reason='RECOVERY_EVIDENCE_INVALID')
            elif state is None:
                condition['reason'] = 'RECEIPTS_INVALID'
            result['conditions'][kind] = condition
        result['code'] = max(CODES[c['state']] for c in result['conditions'].values())
        result['state'] = next(k for k, v in CODES.items() if v == result['code'])
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--instance', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--archives', required=True)
    parser.add_argument('--mode', choices=('server', 'mac'), required=True)
    parser.add_argument('--identity-file')
    args = parser.parse_args()
    try:
        book = ReceiptBook(args.directory, args.instance)
        result = book.status(args.source, args.image, args.archives, mode=args.mode,
                             identity_file=args.identity_file)
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        result = {'v': 1, 'state': 'UNKNOWN', 'code': 3, 'reason': 'RECOVERY_OBSERVATION_INVALID'}
    print(json.dumps(result, indent=2))
    return result['code']


if __name__ == '__main__':
    raise SystemExit(main())
