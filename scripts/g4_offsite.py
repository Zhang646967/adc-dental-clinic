"""Encrypted COS backup copies; credentials and decryption keys stay private."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.g4_course import BACKUP_NAME, backup_inventory, decrypt_backup, digest, private_directory, private_file
from scripts.g4_mac_demo import atomic_text
from scripts.recovery_receipts import MAX_ARCHIVE, ReceiptBook, age, artifact, file_digest, instant


def validate_row(row, project):
    if (not BACKUP_NAME.fullmatch(row['name']) or row['project'] != project
            or not row['name'].endswith('-' + project + '.tar.age')
            or type(row['size']) is not int or not 0 < row['size'] < MAX_ARCHIVE
            or not re.fullmatch('[0-9a-f]{64}', row['sha256'])
            or not re.fullmatch('[0-9a-f]{40}', row['source_commit'])):
        raise ValueError('Object backup metadata differs from this project.')
    from scripts.g4_prepare import pinned_image
    if not pinned_image(row['app_image']):
        raise ValueError('Object backup must identify its retained application image.')
    age(row['created_at'], datetime.now(timezone.utc))
    return row


def read_config(config):
    c = json.loads(private_file(config).read_text())
    if (not re.fullmatch('ap-[a-z]+(?:-[a-z]+)?', c['region'])
            or not re.fullmatch('[a-z0-9][a-z0-9-]{1,49}-[0-9]{5,20}', c['bucket'])
            or not re.fullmatch('adc_g4_[0-9a-f]{12}', c['project'])
            or not re.fullmatch('[a-zA-Z0-9_-]{1,64}', c['prefix'])
            or not c['secret_id'] or not c['secret_key']):
        raise ValueError('Use the private COS region, bucket, project prefix and scoped credentials.')
    return c


class ObjectBackups:
    def __init__(self, config, client=None):
        self.config = c = read_config(config)
        self.prefix = c['prefix'] + '/' + c['project'] + '/'
        if client is None:
            from qcloud_cos import CosConfig, CosS3Client
            client = CosS3Client(CosConfig(Region=c['region'], SecretId=c['secret_id'],
                SecretKey=c['secret_key'], Token=c.get('token'), Scheme='https'))
        self.client = client

    def get(self, key):
        return self.client.get_object(Bucket=self.config['bucket'], Key=key)['Body'].get_raw_stream()

    def rows(self):
        rows, marker = [], ''
        for _ in range(10):
            page = self.client.list_objects(Bucket=self.config['bucket'], Prefix=self.prefix,
                                            Marker=marker, MaxKeys=1000)
            for obj in page.get('Contents', []):
                key = obj['Key']
                name = key[len(self.prefix):] if key.startswith(self.prefix) else ''
                if name.endswith('.tar.age.json') and '/' not in name:
                    with closing(self.get(key)) as stream:
                        raw = stream.read(32769)
                    if len(raw) > 32768:
                        raise ValueError('Object metadata exceeds its bound.')
                    row = validate_row(json.loads(raw), self.config['project'])
                    if name != row['name'] + '.json':
                        raise ValueError('Object metadata filename differs.')
                    rows.append(row)
            if str(page.get('IsTruncated', 'false')).lower() != 'true':
                return sorted(rows, key=lambda row: row['name'])
            next_marker = page['NextMarker']
            if next_marker <= marker:
                raise ValueError('Object pagination did not advance.')
            marker = next_marker
        raise ValueError('Object listing exceeds the course retention envelope.')

    def verify_bytes(self, key, row, output=None):
        h, total = hashlib.sha256(), 0
        with closing(self.get(key)) as stream:
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                if total > row['size']:
                    raise ValueError('Object is larger than its accepted encrypted archive.')
                h.update(chunk)
                if output:
                    output.write(chunk)
        if total != row['size'] or h.hexdigest() != row['sha256']:
            raise ValueError('Object read-back checksum differs.')

    def upload(self, bundle, name):
        bundle = Path(bundle)
        plan = json.loads(private_file(bundle / 'plan.json').read_text())
        if plan['project'] != self.config['project']:
            raise ValueError('COS configuration belongs to a different deployment.')
        state_file = bundle / 'private/offsite-status.json'
        previous = json.loads(private_file(state_file).read_text()) if state_file.exists() else {}
        try:
            rows = backup_inventory(bundle / 'backups', plan['project'])
            row = next((r for r in rows if r['name'] == name), None)
            if row is None:
                raise ValueError('Select an existing verified encrypted server backup.')
            validate_row(row, plan['project'])
            key = self.prefix + name
            with private_file(bundle / 'backups' / name).open('rb') as stream:
                self.client.put_object(Bucket=self.config['bucket'], Key=key, Body=stream)
            self.verify_bytes(key, row)
            # Only publish the inventory sidecar AFTER reading the complete
            # encrypted object back. A failed upload never advances the RPO.
            self.client.put_object(Bucket=self.config['bucket'], Key=key + '.json',
                                   Body=(json.dumps(row) + '\n').encode())
            current = self.rows()
            accepted = next((r for r in current if r['name'] == name), None)
            if accepted != row:
                raise ValueError('Published object inventory differs after upload.')
            latest = max(current, key=lambda item: instant(item['created_at']))
            if latest != row:
                self.verify_bytes(self.prefix + latest['name'], latest)
            daily = {}
            for item in current:
                daily[item['name'][7:15]] = item
            keep = {r['name'] for r in list(daily.values())[-30:]}
            for item in current:
                if item['name'] not in keep:
                    for suffix in ('.json', ''):
                        self.client.delete_object(Bucket=self.config['bucket'],
                                                  Key=self.prefix + item['name'] + suffix)
            state = {'project': plan['project'], 'state': 'HEALTHY', 'last_verified': latest,
                     'verified_at': datetime.now(timezone.utc).isoformat(), 'retention_daily': 30,
                     'verification': 'COMPLETE_CIPHERTEXT_READBACK_SHA256',
                     'decryption': 'NOT_PERFORMED_ON_SERVER'}
        except Exception:
            atomic_text(state_file, json.dumps({**previous, 'project': plan['project'],
                'state': 'FAILED', 'last_attempt_at': datetime.now(timezone.utc).isoformat(),
                'reason': 'OBJECT_BACKUP_NOT_VERIFIED'}) + '\n')
            raise RuntimeError('Object backup not verified; local encrypted backup and last verified point retained.') from None
        atomic_text(state_file, json.dumps(state, indent=2) + '\n')
        return {'state': 'VERIFIED', 'recovery_point': latest['created_at'], 'sha256': latest['sha256']}

    def download(self, name, destination, identity_file, age_binary='age'):
        destination = private_directory(destination)
        row = next((r for r in self.rows() if r['name'] == name), None)
        if row is None:
            raise ValueError('No accepted object backup with that name.')
        target = destination / name
        with tempfile.TemporaryDirectory(dir=destination) as temporary:
            temporary = Path(temporary)
            encrypted = temporary / name
            with encrypted.open('xb') as stream:
                import os
                os.fchmod(stream.fileno(), 0o600)
                self.verify_bytes(self.prefix + name, row, stream)
            meta = decrypt_backup(encrypted, private_file(identity_file), temporary,
                                  destination / 'offsite-download.log', age_binary)
            fact = artifact(meta, row)
            if (fact['source_commit'], fact['app_image']) != (row['source_commit'], row['app_image']):
                raise ValueError('Decrypted object release differs from its inventory.')
            if target.exists():
                if digest(private_file(target)) != row['sha256']:
                    raise ValueError('Existing downloaded backup differs; it was preserved.')
            else:
                encrypted.replace(target)
            atomic_text(destination / (name + '.json'), json.dumps(row) + '\n')
            book = ReceiptBook(destination / 'recovery', row['project'])
            book.record('created', fact)
            book.record('downloaded', fact, key_sha256=file_digest(identity_file))
        return {'status': 'OBJECT_BACKUP_DECRYPTED_AND_VERIFIED', 'name': name,
                'recovery_point': row['created_at'], 'restoration': 'NOT_RUN'}


def offsite_status(bundle):
    bundle = Path(bundle)
    if not (bundle / 'private/offsite.json').exists():
        return {'state': 'NOT_CONFIGURED', 'verified_recovery_point': None}
    try:
        plan = json.loads(private_file(bundle / 'plan.json').read_text())
        result = json.loads(private_file(bundle / 'private/offsite-status.json').read_text())
        if result['project'] != plan['project']:
            raise ValueError('Foreign observation.')
        row = result.get('last_verified')
        if row:
            validate_row(row, plan['project'])
            elapsed = age(row['created_at'], datetime.now(timezone.utc))
            state = result['state'] if elapsed <= 86400 else 'STALE'
            return {'state': state, 'verified_recovery_point': row['created_at'],
                    'age_seconds': round(elapsed), 'verification': result['verification']}
        return {'state': result.get('state', 'UNKNOWN'), 'verified_recovery_point': None}
    except (OSError, ValueError, KeyError, TypeError):
        return {'state': 'UNKNOWN', 'verified_recovery_point': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    commands = parser.add_subparsers(dest='action', required=True)
    upload = commands.add_parser('upload')
    upload.add_argument('--bundle', required=True)
    upload.add_argument('--backup-name', required=True)
    download = commands.add_parser('download')
    download.add_argument('--backup-name', required=True)
    download.add_argument('--destination', required=True)
    download.add_argument('--identity-file', required=True)
    download.add_argument('--age', default='age')
    args = parser.parse_args()
    objects = ObjectBackups(args.config)
    result = objects.upload(args.bundle, args.backup_name) if args.action == 'upload' else objects.download(
        args.backup_name, args.destination, args.identity_file, args.age)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Object backup operation stopped; inspect private configuration and retained recovery evidence.') from None
