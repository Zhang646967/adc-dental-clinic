"""Pinned SSH deployment and verified Mac backup synchronization.

Private SSH JSON: host (public IPv4), user, identity_file, known_hosts_file,
fingerprint (SHA256), sudo (optional bool). Keys are never sent to the server.
The .g4 bundle pins the project; the remote path is derived from that identity.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.g4_course import (BACKUP_NAME, MAX_BACKUP_BYTES, RECIPIENT, backup_inventory,
                              decrypt_backup, digest, exclusive, private_directory,
                              private_file, prune_backups, run)
from scripts.g4_prepare import inspect_bundle
from scripts.g4_mac_demo import atomic_text
from scripts.recovery_receipts import ReceiptBook, artifact, file_digest, instant, age as recovery_age, utc_now, validate_restore, MAX_ARCHIVE


class Remote:
    def __init__(self, config, bundle):
        self.config_path = private_file(config)
        self.bundle = Path(bundle).absolute()
        inspect_bundle(self.bundle)
        self.plan = json.loads((self.bundle / 'plan.json').read_text())
        if (self.plan.get('access_mode') != 'course-writable' or self.plan.get('mode') != 'direct_tls'
                or self.plan['bind_ip'] != '0.0.0.0' or self.plan['ports'] != [80, 443]):
            raise ValueError('Remote operations require the separate public course bundle.')
        self.config = json.loads(self.config_path.read_text())
        c = self.config
        if (not ipaddress.IPv4Address(c['host']).is_global or
                not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', c['user']) or
                not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}', c['fingerprint']) or
                type(c.get('sudo', False)) is not bool):
            raise ValueError('Use an explicit IPv4 SSH target, user and SHA256 host-key fingerprint.')
        key, hosts = private_file(c['identity_file']), private_file(c['known_hosts_file'])
        entries = [line.split() for line in hosts.read_text().splitlines() if line and not line.startswith('#')]
        if len(entries) != 1 or len(entries[0]) != 3 or entries[0][0] != c['host']:
            raise ValueError('Use exactly one known-host key for this IPv4 target on port 22.')
        self.log = self.bundle / 'private/operations.log'
        checked = run(['ssh-keygen', '-E', 'sha256', '-lf', str(hosts)], self.log).decode().split()
        if len(checked) < 2 or checked[1] != c['fingerprint']:
            raise ValueError('Pinned SSH host-key fingerprint differs.')
        self.options = ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                        '-o', 'IdentitiesOnly=yes', '-o', 'ConnectTimeout=10',
                        '-o', 'UserKnownHostsFile=' + str(hosts), '-i', str(key)]
        self.target = c['user'] + '@' + c['host']
        initial = self.plan.get('initial_source_commit', self.plan['requested_source_commit'])
        if not re.fullmatch('[0-9a-f]{40}', initial):
            raise ValueError('Invalid initial deployment source.')
        self.folder = '/srv/adc-course/releases/' + initial + '-' + self.plan['project']
        self.remote_bundle = self.folder + '/.g4'

    def ssh(self, args, *, timeout=180):
        command = (['sudo', '-n'] if self.config.get('sudo') else []) + args
        return run(['ssh'] + self.options + [self.target, shlex.join(command)],
                   self.log, timeout=timeout)

    def copy(self, source, target, *, download=False):
        if (not re.fullmatch(r'/srv/adc-course/releases/[a-zA-Z0-9_./-]+', target)
                or '..' in Path(target).parts or not target.startswith(self.folder + '/')):
            raise ValueError('SCP paths must stay in the explicitly owned course release.')
        remote = self.target + ':' + target
        if download:
            # A non-root SSH account may need sudo to read the root-owned
            # backup. Stream through the same pinned SSH connection.
            command = (['sudo', '-n'] if self.config.get('sudo') else []) + ['cat', '--', target]
            with Path(source).open('xb') as stream:
                os.fchmod(stream.fileno(), 0o600)
                run(['ssh'] + self.options + [self.target, shlex.join(command)], self.log,
                    output_file=stream, timeout=600)
        else:
            run(['scp'] + self.options + [str(source), remote], self.log, timeout=600)

    def operation(self, action, extra=(), *, timeout=600):
        return json.loads(self.ssh(['python3', self.folder + '/scripts/g4_course.py',
            '--output', self.remote_bundle, '--docker', '/usr/bin/docker', '--context', 'default',
            action] + list(extra), timeout=timeout))

    def publish(self, artifacts, recipient_file, restore_backup=None, identity_file=None, age='age', offsite_config=None):
        artifacts = private_directory(artifacts)
        metadata = json.loads(private_file(artifacts / 'build.json').read_text())
        recipient = private_file(recipient_file).read_text().strip()
        if metadata['source_commit'] != self.plan['requested_source_commit'] or metadata['architecture'] != 'amd64':
            raise ValueError('Publish requires this source commit built for amd64.')
        if metadata['app_image'] != self.plan['images']['app'] or not RECIPIENT.fullmatch(recipient):
            raise ValueError('Reviewed application image or recipient differs.')
        for name, field in (('source.tar', 'source_sha256'), ('application.tar', 'image_archive_sha256')):
            if digest(private_file(artifacts / name)) != metadata[field]:
                raise ValueError('Build archive checksum differs.')
        if restore_backup:
            if not identity_file:
                raise ValueError('Recovery requires the Mac key.')
            cipher_sha, key_sha = file_digest(restore_backup), file_digest(identity_file)
            with tempfile.TemporaryDirectory(dir=self.bundle / 'private') as folder:
                meta = decrypt_backup(private_file(restore_backup), private_file(identity_file),
                                      Path(folder), self.log, age)
                if (meta['project'] == self.plan['project'] or
                        meta['source_commit'] != self.plan['requested_source_commit'] or
                        meta['images']['app'] != self.plan['images']['app']):
                    raise ValueError('Recovery backup must match the image/source and use a new project.')
                if meta.get('format') == 2:
                    restore_fact = artifact(meta, dict(name=Path(restore_backup).name, project=meta['project'],
                        created_at=meta['created_at'], size=Path(restore_backup).stat().st_size, sha256=cipher_sha))
                    restore_book = ReceiptBook(Path(restore_backup).parent / 'recovery', meta['project'])
                    restore_book.load()
            if file_digest(restore_backup) != cipher_sha or file_digest(identity_file) != key_sha:
                raise ValueError('Recovery archive or key changed during authentication.')
        # An existing directory is never overwritten: status and sync are the
        # recovery operations after an interrupted publish.
        setup = ("from pathlib import Path; import os,pwd; "
                 "p=Path(" + repr(self.folder) + "); "
                 "p.mkdir(mode=0o700,parents=True,exist_ok=False); "
                 "u=pwd.getpwnam(" + repr(self.config['user']) + "); os.chown(p,u.pw_uid,u.pw_gid)")
        self.ssh(['python3', '-c', setup])
        with tempfile.TemporaryDirectory(dir=self.bundle / 'private') as folder:
            tarpath = Path(folder) / 'bundle.tar'
            allowed = ['plan.json', 'compose.env', 'compose.yaml', 'nginx.conf', 'init-db.sh',
                       'private/runtime.env', 'private/maintenance.env', 'private/database.env']
            with tarfile.open(tarpath, 'w') as archive:
                for name in allowed:
                    path = self.bundle / name
                    if path.is_symlink():
                        raise ValueError('Bundle transfer refuses symbolic links.')
                    archive.add(path, arcname='.g4/' + name, recursive=False)
            os.chmod(tarpath, 0o600)
            hashes = {'bundle.tar': digest(tarpath), 'source.tar': metadata['source_sha256'],
                      'application.tar': metadata['image_archive_sha256']}
            self.copy(tarpath, self.folder + '/bundle.tar')
        for name in ('source.tar', 'application.tar'):
            self.copy(artifacts / name, self.folder + '/' + name)
        unpack = ("from pathlib import Path; import hashlib,tarfile,os; "
                  "p=Path(" + repr(self.folder) + "); expected=" + repr(hashes) + "; "
                  "assert all(hashlib.file_digest((p/n).open('rb'),'sha256').hexdigest()==v for n,v in expected.items()); "
                  "[tarfile.open(p/n).extractall(p,filter='data') for n in ('source.tar','bundle.tar')]; "
                  "os.chmod(p/'.g4',0o700); os.chmod(p/'.g4/private',0o700); "
                  "[(p/'.g4'/n).mkdir(mode=0o700,exist_ok=True) for n in ('tls','backups')]; "
                  "(p/'.g4/acme/.well-known/acme-challenge').mkdir(mode=0o755,parents=True,exist_ok=True); "
                  "(p/'.g4/private/backup-recipient.txt').write_text(" + repr(recipient + '\n') + "); "
                  "os.chmod(p/'.g4/private/backup-recipient.txt',0o600)")
        self.ssh(['python3', '-c', unpack])
        self.ssh(['sh', self.folder + '/scripts/g4_host_bootstrap.sh', '--new-course-server'], timeout=1800)
        # stdout may include image names; diagnostics remain private, never print envs.
        self.ssh(['/usr/bin/docker', '--context', 'default', 'load', '-i', self.folder + '/application.tar'], timeout=600)
        for name in ('db', 'nginx'):
            self.ssh(['/usr/bin/docker', '--context', 'default', 'pull', '--platform', 'linux/amd64',
                      self.plan['images'][name]], timeout=600)
        self.operation('issue-tls', ['--public-ip', self.config['host']])
        if restore_backup:
            if not identity_file:
                raise ValueError('Recovery requires the Mac private key; it is never uploaded.')
            with tempfile.TemporaryDirectory(dir=self.bundle / 'private') as folder:
                folder = Path(folder)
                meta = decrypt_backup(private_file(restore_backup), private_file(identity_file), folder, self.log, age)
                if file_digest(restore_backup) != cipher_sha or file_digest(identity_file) != key_sha:
                    raise ValueError('Recovery archive or key changed before verified transfer.')
                if (meta['project'] == self.plan['project'] or
                        meta['source_commit'] != self.plan['requested_source_commit'] or
                        meta['images']['app'] != self.plan['images']['app']):
                    raise ValueError('Recovery requires an independent project and the matching application.')
                # Transfer the verified data through SSH; keep the key on Mac.
                recovery_files = ['database.dump', 'archive.json']
                if meta.get('format') == 2:
                    recovery_files += ['facts.json', 'observations.json']
                for name in recovery_files:
                    self.copy(folder / name, self.folder + '/recovery-' + name)
                    move = ("from pathlib import Path; import os; p=Path(" + repr(self.folder) + "); "
                            "(p/" + repr('recovery-' + name) + ").replace(p/'.g4/private'/" + repr(name) + "); "
                            "os.chmod(p/'.g4/private'/" + repr(name) + ",0o600)")
                    self.ssh(['python3', '-c', move])
                original = folder / 'demo-credentials.txt'
                if original.exists():
                    local = self.bundle / 'private/demo-credentials.txt'
                    if local.exists():
                        raise ValueError('Existing private credential record is preserved.')
                    os.replace(original, local)
            result = self.operation('restore-verified-dump', [
                '--dump-file', self.remote_bundle + '/private/database.dump',
                '--manifest-file', self.remote_bundle + '/private/archive.json',
                '--trusted-synthetic-copy', '--schema-mode',
                'migration-built' if meta.get('format') == 2 else 'pg-dump'])
            if meta.get('format') == 2:
                proof = result.get('restore')
                validate_restore(proof, meta['project'])
                if (result.get('business_comparison') != 'PASSED' or
                        proof['target']['project'] != self.plan['project'] or
                        proof['comparison']['facts_sha256'] != meta['facts_sha256'] or
                        file_digest(restore_backup) != cipher_sha or file_digest(identity_file) != key_sha):
                    raise ValueError('Remote restoration does not bind the authenticated Mac archive.')
                restore_book.record('restored', restore_fact, key_sha256=key_sha, restore=proof)
            self.ssh(['python3', '-c', 'from pathlib import Path; p=Path(' + repr(self.remote_bundle) + '); '
                      '[ (p/"private"/n).unlink() for n in ' + repr(recovery_files) + ']'])
        else:
            result = self.operation('deploy')
            self.copy(self.bundle / 'private/demo-credentials.txt',
                      self.remote_bundle + '/private/demo-credentials.txt', download=True)
        self.copy(self.bundle / 'private/COURSE_ACCESS.md',
                  self.remote_bundle + '/private/COURSE_ACCESS.md', download=True)
        if offsite_config:
            self.install_offsite(offsite_config)
        self.operation('install-server-jobs', ['--recipient-file', self.remote_bundle + '/private/backup-recipient.txt'])
        self.operation('backup', ['--recipient-file', self.remote_bundle + '/private/backup-recipient.txt'])
        return {'status': result['status'], 'hostname': self.plan['host'],
                'source_commit': metadata['source_commit'], 'public_acceptance_executed': False}

    def check_backup_recipient(self, recipient_file):
        recipient = private_file(recipient_file).read_text().strip()
        if not RECIPIENT.fullmatch(recipient):
            raise ValueError('Use the existing public recovery recipient.')
        retained = self.ssh(['cat', '--', self.remote_bundle + '/private/backup-recipient.txt']).decode().strip()
        if retained != recipient:
            raise ValueError('Recovery recipient differs from the server; verify the recovery key before maintenance.')

    def upgrade(self, artifacts, recipient_file, expected_current, age='age'):
        artifacts = private_directory(artifacts)
        meta = json.loads(private_file(artifacts / 'build.json').read_text())
        if meta['architecture'] != 'amd64' or not re.fullmatch('[0-9a-f]{40}', meta['source_commit']):
            raise ValueError('Use an identified amd64 cloud release.')
        self.check_backup_recipient(recipient_file)
        for name, field in [('source.tar', 'source_sha256'), ('application.tar', 'image_archive_sha256')]:
            if digest(private_file(artifacts / name)) != meta[field]:
                raise ValueError('Local release archive checksum differs.')
        target = self.folder + '/artifacts/' + meta['source_commit']
        self.ssh(['python3', '-c', 'from pathlib import Path;import os,pwd;'
                  'p=Path(' + repr(target) + ');p.mkdir(mode=0o700,parents=True,exist_ok=True);'
                  'u=pwd.getpwnam(' + repr(self.config['user']) + ');os.chown(p,u.pw_uid,u.pw_gid)'])
        for name in ('build.json', 'source.tar', 'application.tar'):
            self.copy(artifacts / name, target + '/' + name)
        # The initial deployment controller includes upgrade dispatch. Its path
        # remains stable even when the active application source is changed.
        result = self.operation('upgrade', ['--artifacts', target, '--recipient-file',
            self.remote_bundle + '/private/backup-recipient.txt', '--expected-current-commit', expected_current,
            '--age', age], timeout=900)
        from scripts.g4_release import update_plan
        self.plan = update_plan(self.bundle, meta['source_commit'], meta['app_image'], controller=meta['source_commit'])
        return result

    def rollback(self, source, recipient_file, expected_current, age='age'):
        self.check_backup_recipient(recipient_file)
        from scripts.g4_release import update_plan, versions
        image = versions(self.plan).get(source)
        if not image:
            raise ValueError('Rollback source is not in the local accepted deployment history.')
        result = self.operation('rollback', ['--to-source', source, '--recipient-file',
            self.remote_bundle + '/private/backup-recipient.txt', '--expected-current-commit', expected_current,
            '--age', age], timeout=900)
        self.plan = update_plan(self.bundle, source, image)
        return result

    def install_offsite(self, config):
        from scripts.g4_offsite import read_config
        values = read_config(config)
        if values['project'] != self.plan['project']:
            raise ValueError('Object storage configuration belongs to another deployment.')
        self.ssh(['apt-get', 'install', '-y', '--no-install-recommends', 'gcc', 'python3-dev'], timeout=600)
        self.ssh(['python3', '-m', 'venv', self.folder + '/operations-venv'], timeout=120)
        self.ssh([self.folder + '/operations-venv/bin/python', '-m', 'pip', 'install',
                  '-r', self.folder + '/requirements-operations.txt'], timeout=600)
        self.copy(private_file(config), self.folder + '/offsite-config.json')
        self.ssh(['python3', '-c', 'from pathlib import Path;import os;'
            'p=Path(' + repr(self.folder + '/offsite-config.json') + ');'
            'q=Path(' + repr(self.remote_bundle + '/private/offsite.json') + ');'
            'p.replace(q);os.chmod(q,0o600)'])
        return {'status': 'OFFSITE_CONFIGURED_NOT_VERIFIED', 'retention_daily': 30,
                'next_action': 'Create and read-back verify an encrypted backup.'}

    def sync(self, destination, identity_file, age='age'):
        destination = private_directory(destination)
        identity = private_file(identity_file)
        with exclusive(destination / '.sync.lock'):
            listing = self.operation('list-backups')
            if listing['project'] != self.plan['project'] or not listing['backups']:
                raise ValueError('No complete backup for the explicitly selected project.')
            rows = listing['backups']
            if not isinstance(rows, list) or len(rows) > 32:
                raise ValueError('Remote inventory exceeds the bounded retention contract.')
            book = ReceiptBook(destination / 'recovery', self.plan['project'])
            book.load()
            backup_inventory(destination, self.plan['project'])
            key_sha256 = file_digest(identity)
            verified = []
            seen = set()
            # Validate every current/cached copy with the CURRENT key before
            # installing any sidecar, advancing receipts, or pruning old points.
            with tempfile.TemporaryDirectory(dir=destination) as staging:
                staging = Path(staging)
                for index, row in enumerate(rows):
                    if (row['project'] != self.plan['project'] or not BACKUP_NAME.fullmatch(row['name']) or
                            type(row['size']) is not int or not 0 < row['size'] < MAX_ARCHIVE or
                            not re.fullmatch('[0-9a-f]{64}', row['sha256']) or row['name'] in seen):
                        raise ValueError('Invalid or repeated remote backup metadata.')
                    seen.add(row['name'])
                    target = destination / row['name']
                    work = staging / str(index)
                    work.mkdir(mode=0o700)
                    pending = work / row['name']
                    cached = target.exists() or target.is_symlink()
                    if cached:
                        private_file(target)
                        encrypted = target
                    else:
                        self.copy(pending, self.remote_bundle + '/backups/' + row['name'], download=True)
                        encrypted = pending
                    if encrypted.stat().st_size != row['size'] or file_digest(encrypted) != row['sha256']:
                        raise ValueError('Downloaded/cached backup checksum differs.')
                    meta = decrypt_backup(encrypted, identity, work, self.log, age)
                    fact = artifact(meta, row)
                    from scripts.g4_release import versions
                    if (fact['project'] != self.plan['project'] or
                            versions(self.plan).get(fact['source_commit']) != fact['app_image']):
                        raise ValueError('Downloaded/cached recovery provenance differs.')
                    # Validate clocks/schema before publishing any of the batch.
                    recovery_age(fact['created_at'], utc_now())
                    verified.append((fact, row, None if cached else pending, target))
                if file_digest(identity) != key_sha256:
                    raise ValueError('The current recovery key changed during synchronization.')
                verified.sort(key=lambda item: instant(item[0]['created_at']))
                last_fact, last, _, _ = verified[-1]
                # Preflight receipt conflicts before installing bytes. Receipts
                # are still untouched if a later item in the batch was invalid.
                state = book.load()
                for kind in ('created', 'downloaded'):
                    previous = state['latest'][kind]
                    if previous and instant(previous['artifact']['created_at']) == instant(last_fact['created_at']) and previous['artifact'] != last_fact:
                        raise ValueError('Conflicting recovery archive at the latest point.')
                for fact, row, pending, target in verified:
                    if pending is not None:
                        os.replace(pending, target)
                    atomic_text(destination / (row['name'] + '.json'), json.dumps(row) + '\n')
                # Fresh observations are distinct from the original backup time.
                book.record('created', last_fact)
                book.record('downloaded', last_fact, key_sha256=key_sha256)
            prune_backups(destination, self.plan['project'], 30)
            result = {'status': 'MAC_BACKUP_VERIFIED', 'project': self.plan['project'],
                      'last_off_host_backup': last['created_at'], 'sha256': last['sha256'],
                      'verified_at': datetime.now(timezone.utc).isoformat(),
                      'recovery_point': 'last_verified_download', 'public_acceptance_executed': False}
            atomic_text(destination / 'last-sync.json', json.dumps(result, indent=2) + '\n')
            return result

    def install_mac_job(self, destination, identity_file, age):
        if sys.platform != 'darwin':
            raise ValueError('Mac synchronization jobs require macOS.')
        private_directory(destination)
        private_file(identity_file)
        age_binary = Path(age).resolve(strict=True)
        if not age_binary.is_file() or not os.access(age_binary, os.X_OK):
            raise ValueError('Use an absolute reviewed age executable.')
        folder = Path.home() / 'Library/LaunchAgents'
        folder.mkdir(parents=True, exist_ok=True)
        label = 'org.adc.course.sync.' + self.plan['project']
        target = folder / (label + '.plist')
        arguments = [sys.executable, str(ROOT / 'scripts/g4_remote.py'), '--ssh-config', str(self.config_path),
                     '--output', str(self.bundle), 'sync', '--destination', str(Path(destination).absolute()),
                     '--identity-file', str(Path(identity_file).absolute()), '--age', str(age_binary)]
        payload = {'Label': label, 'ProgramArguments': arguments, 'StartInterval': 3600, 'RunAtLoad': True,
                   'StandardOutPath': str(self.bundle / 'private/mac-sync.log'),
                   'StandardErrorPath': str(self.bundle / 'private/mac-sync-errors.log'),
                   'Umask': 0o077}
        data = plistlib.dumps(payload).decode()
        if target.exists() and target.read_text() != data:
            raise ValueError('Existing Mac job differs; preserve and review it.')
        if not target.exists():
            atomic_text(target, data)
        loaded = subprocess.run(['launchctl', 'print', 'gui/' + str(os.getuid()) + '/' + label],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if loaded.returncode:
            run(['launchctl', 'bootstrap', 'gui/' + str(os.getuid()), str(target)], self.log)
        return {'status': 'MAC_SYNC_JOB_INSTALLED', 'interval_seconds': 3600,
                'limitation': 'Mac must be awake and network reachable'}


def generate_key(destination, age_keygen='age-keygen'):
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('A new private key folder is required.')
    private_directory(destination)
    key = destination / 'identity.txt'
    log = destination / 'operations.log'
    run([age_keygen, '-o', str(key)], log)
    os.chmod(key, 0o600)
    recipient = run([age_keygen, '-y', str(key)], log).decode().strip()
    if not RECIPIENT.fullmatch(recipient):
        raise ValueError('Generated recipient format differs.')
    atomic_text(destination / 'recipient.txt', recipient + '\n')
    return {'status': 'MAC_KEY_CREATED', 'private_key': 'owner-only identity.txt; never uploaded',
            'recipient_file': str(destination / 'recipient.txt')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-config')
    parser.add_argument('--output', default=str(ROOT / '.g4'))
    sub = parser.add_subparsers(dest='action', required=True)
    key = sub.add_parser('generate-backup-key')
    key.add_argument('--destination', required=True)
    key.add_argument('--age-keygen', default='age-keygen')
    publish = sub.add_parser('publish')
    publish.add_argument('--artifacts', required=True)
    publish.add_argument('--recipient-file', required=True)
    publish.add_argument('--restore-backup')
    publish.add_argument('--identity-file')
    publish.add_argument('--age', default='age')
    publish.add_argument('--trusted-synthetic-copy', action='store_true')
    publish.add_argument('--offsite-config')
    for action in ('upgrade', 'rollback'):
        command = sub.add_parser(action)
        command.add_argument('--recipient-file', required=True)
        command.add_argument('--expected-current-commit', required=True)
        command.add_argument('--age', default='age')
        command.add_argument('--artifacts' if action == 'upgrade' else '--to-source', required=True)
    offsite = sub.add_parser('install-offsite')
    offsite.add_argument('--config-file', required=True)
    for name in ('sync', 'install-mac-job'):
        command = sub.add_parser(name)
        command.add_argument('--destination', required=True)
        command.add_argument('--identity-file', required=True)
        command.add_argument('--age', default='age')
    status = sub.add_parser('recovery-status')
    status.add_argument('--destination', required=True)
    status.add_argument('--identity-file', required=True)
    sub.add_parser('status')
    args = parser.parse_args()
    if args.action == 'generate-backup-key':
        result = generate_key(args.destination, args.age_keygen)
    else:
        if not args.ssh_config:
            raise ValueError('Use a private pinned SSH configuration.')
        remote = Remote(args.ssh_config, args.output)
        if args.action == 'publish':
            if args.restore_backup and not args.trusted_synthetic_copy:
                raise ValueError('Recovery requires the explicit trusted-synthetic-copy flag.')
            result = remote.publish(args.artifacts, args.recipient_file,
                                    args.restore_backup, args.identity_file, args.age, args.offsite_config)
        elif args.action == 'upgrade':
            result = remote.upgrade(args.artifacts, args.recipient_file, args.expected_current_commit, args.age)
        elif args.action == 'rollback':
            result = remote.rollback(args.to_source, args.recipient_file, args.expected_current_commit, args.age)
        elif args.action == 'install-offsite':
            result = remote.install_offsite(args.config_file)
        elif args.action == 'sync':
            result = remote.sync(args.destination, args.identity_file, args.age)
        elif args.action == 'recovery-status':
            folder = private_directory(args.destination)
            result = ReceiptBook(folder / 'recovery', remote.plan['project']).status(
                remote.plan['requested_source_commit'], remote.plan['images']['app'], folder,
                mode='mac', identity_file=args.identity_file)
        elif args.action == 'install-mac-job':
            result = remote.install_mac_job(args.destination, args.identity_file, args.age)
        else:
            result = remote.operation('status')
    print(json.dumps(result, indent=2))
    if args.action == 'recovery-status' and result.get('code') in (1,2,3):
        raise SystemExit(result['code'])


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError, RuntimeError, subprocess.SubprocessError, tarfile.TarError):
        raise SystemExit('Remote operation stopped. Preserve private state and diagnostics; no cloud acceptance granted.') from None
