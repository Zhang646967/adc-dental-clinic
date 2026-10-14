"""Explicit course deployment/recovery operations; never certify cloud acceptance.

Only a reviewed course-writable .g4 bundle and an explicit local Unix Docker
context are accepted. SSH transfer uses separately pinned host keys. No volume
deletion, restore over existing tables, reseeding, or credential output.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.g4_prepare import inspect_bundle, read_env
from scripts.g4_mac_demo import atomic_text

BACKUP_NAME = re.compile(r'backup-[0-9]{8}T[0-9]{12}Z-adc_g4_[0-9a-f]{12}\.tar\.age')
RECIPIENT = re.compile(r'age1[0-9a-z]{58}')
MAX_BACKUP_BYTES = 512 * 1024 * 1024


def private_file(path):
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError('Use an owner-only regular private file.')
    return path


def private_directory(path):
    path = Path(path).absolute()
    if path.is_symlink():
        raise ValueError('Private folders cannot be symbolic links.')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_mode & 0o077:
        raise ValueError('Private folders require owner-only access.')
    return path


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def run(command, log, *, input_file=None, output_file=None, timeout=180):
    """Commands are argument arrays; diagnostics stay in a mode-600 private log."""
    result = subprocess.run(command, stdin=None if isinstance(input_file, bytes) else input_file,
                            input=input_file if isinstance(input_file, bytes) else None,
                            stdout=output_file or subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        with Path(log).open('ab') as stream:
            os.chmod(log, 0o600)
            stream.write(result.stderr)
        raise RuntimeError('Operation failed; inspect the private operations log.')
    return result.stdout or b''


def docker_command(binary, context, log):
    if not context or not re.fullmatch(r'[a-zA-Z0-9_.-]+', context):
        raise ValueError('Specify one local Docker context.')
    base = [binary, '--context', context]
    endpoint = json.loads(run(base + ['context', 'inspect', context, '--format',
                                     '{{json .Endpoints.docker.Host}}'], log))
    if not isinstance(endpoint, str) or not endpoint.startswith('unix://'):
        raise ValueError('Only an explicit local Unix Docker endpoint is accepted.')
    return base


@contextmanager
def exclusive(path):
    with Path(path).open('a') as stream:
        os.chmod(path, 0o600)
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def build(artifacts, docker, context, architecture):
    artifacts = Path(artifacts).absolute()
    if artifacts.exists():
        raise ValueError('Build artifacts require a new private directory.')
    if architecture not in ('amd64', 'arm64'):
        raise ValueError('Unsupported image architecture.')
    revision = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    if subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain']):
        raise ValueError('Build only an identified clean Git commit.')
    private_directory(artifacts)
    log = artifacts / 'operations.log'
    base = docker_command(docker, context, log)
    source = artifacts / 'source.tar'
    with source.open('xb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        run(['git', '-C', str(ROOT), 'archive', '--format=tar', revision], log, output_file=stream)
    with tempfile.TemporaryDirectory(dir=artifacts) as folder:
        with tarfile.open(source) as archive:
            archive.extractall(folder, filter='data')
        image_file = artifacts / 'image.id'
        run(base + ['build', '--platform', 'linux/' + architecture,
                    '--label', 'org.opencontainers.image.revision=' + revision,
                    '--iidfile', str(image_file), '-f', str(Path(folder) / 'Dockerfile.production'),
                    folder], log, timeout=1800)
    image = image_file.read_text().strip()
    os.chmod(image_file, 0o600)
    image_archive = artifacts / 'application.tar'
    with image_archive.open('xb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        run(base + ['save', image], log, output_file=stream, timeout=600)
    result = {'source_commit': revision, 'architecture': architecture, 'app_image': image,
              'source_sha256': digest(source), 'image_archive_sha256': digest(image_archive)}
    atomic_text(artifacts / 'build.json', json.dumps(result, indent=2) + '\n')
    return result


class OriginHTTPS(http.client.HTTPSConnection):
    def connect(self):
        raw = socket.create_connection(('127.0.0.1', self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class Course:
    def __init__(self, bundle, docker='docker', context=None, *, rehearsal=False,
                 architecture='amd64', ca_file=None):
        self.bundle = Path(bundle).absolute()
        inspect_bundle(self.bundle)
        self.plan = json.loads((self.bundle / 'plan.json').read_text())
        if (self.plan.get('mode') != 'direct_tls' or self.plan.get('access_mode') != 'course-writable'
                or self.plan['read_only']):
            raise ValueError('Use a separate reviewed course-writable direct HTTPS bundle.')
        if rehearsal:
            if self.plan['bind_ip'] != '127.0.0.1' or 80 in self.plan['ports'] or 443 in self.plan['ports']:
                raise ValueError('Rehearsals require separate IPv4 loopback ports.')
        elif (architecture != 'amd64' or ca_file or self.plan['bind_ip'] != '0.0.0.0'
              or self.plan['ports'] != [80, 443]):
            raise ValueError('Cloud deployment requires amd64 and explicit public ports 80/443.')
        self.rehearsal, self.architecture, self.ca_file = rehearsal, architecture, ca_file
        self.log = self.bundle / 'private/operations.log'
        self.docker = docker_command(docker, context, self.log)
        self.command = self.docker + ['compose', '--env-file', str(self.bundle / 'compose.env'),
                                     '-p', self.plan['project'], '-f', str(self.bundle / 'compose.yaml')]

    def dc(self, *args, **kwargs):
        return run(self.command + list(args), self.log, **kwargs)

    def render(self):
        path = self.bundle / 'private/rendered.json'
        atomic_text(path, self.dc('--profile', 'maintenance', 'config', '--format', 'json').decode())
        inspect_bundle(self.bundle, path)

    def images(self):
        for name, image in self.plan['images'].items():
            obj = json.loads(run(self.docker + ['image', 'inspect', image], self.log))[0]
            if obj['Architecture'] != self.architecture:
                raise ValueError('Image architecture does not match the selected target.')
            if name == 'app' and ((obj['Config'].get('Labels') or {}).get('org.opencontainers.image.revision')
                                   != self.plan['requested_source_commit']):
                raise ValueError('Application image must identify the reviewed source commit.')

    def tables(self):
        sql = "SELECT count(*) FROM pg_tables WHERE schemaname='public';"
        value = self.dc('exec', '-T', 'db', 'psql', '--no-psqlrc', '-U', 'adc_g4_admin',
                        '-d', 'adc_rc_demo', '-At', '-c', sql)
        return int(value.strip())

    def start_database(self):
        self.render()
        self.images()
        self.dc('up', '-d', '--wait', '--wait-timeout', '90', 'db', timeout=120)

    def deploy(self):
        marker = self.bundle / 'private/deployed.json'
        phase = self.bundle / 'private/deployment-phase.json'
        if marker.exists():
            recorded = json.loads(private_file(marker).read_text())
            if (recorded.get('project') != self.plan['project'] or
                    recorded.get('source_commit') != self.plan['requested_source_commit']):
                raise ValueError('Recorded deployment identity differs.')
            self.render()
            self.images()
            return self.status()
        if phase.exists():
            recorded = json.loads(private_file(phase).read_text())
            if (recorded.get('project') != self.plan['project'] or
                    recorded.get('source_commit') != self.plan['requested_source_commit'] or
                    recorded.get('phase') != 'BOOTSTRAP_COMPLETE'):
                raise ValueError('Interrupted initialization requires diagnosis; never reseed implicitly.')
            self.render()
            self.images()
            self.start_runtime()
            atomic_text(marker, json.dumps(recorded | {'fresh_seed': True}) + '\n')
            return self.status()
        self.start_database()
        if self.tables():
            raise ValueError('Fresh deployment refused: existing tables; never migrate or reseed them implicitly.')
        identity = {'project': self.plan['project'], 'source_commit': self.plan['requested_source_commit']}
        atomic_text(phase, json.dumps(identity | {'phase': 'SCHEMA_STARTED'}) + '\n')
        self.dc('--profile', 'maintenance', 'run', '--rm', 'schema', timeout=300)
        atomic_text(phase, json.dumps(identity | {'phase': 'BOOTSTRAP_STARTED'}) + '\n')
        credentials = self.bundle / 'private/demo-credentials.txt'
        with credentials.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            self.dc('--profile', 'maintenance', 'run', '--rm', 'bootstrap', output_file=stream, timeout=180)
        atomic_text(phase, json.dumps(identity | {'phase': 'BOOTSTRAP_COMPLETE'}) + '\n')
        self.start_runtime()
        atomic_text(marker, json.dumps({'project': self.plan['project'],
                    'source_commit': self.plan['requested_source_commit'], 'fresh_seed': True}) + '\n')
        return self.status()

    def start_runtime(self):
        self.dc('up', '-d', '--wait', '--wait-timeout', '120',
                'web', 'notification-worker', 'gateway', timeout=180)
        if self.dc('exec', '-T', 'web', 'id', '-u').strip() != b'10001':
            raise ValueError('Runtime application must use UID 10001.')
        self.dc('exec', '-T', 'web', 'python', 'manage.py', 'check_runtime_role')
        atomic_text(self.bundle / 'private/COURSE_ACCESS.md',
                    '# Course access（课程登录）\n\n'
                    'Staff login: https://' + self.plan['host'] + '/accounts/login/\n\n'
                    'Patient login: https://' + self.plan['host'] + '/portal/login/\n\n'
                    'Assigned synthetic accounts: private demo-credentials.txt.\n'
                    'Change passwords before account handover. Roles and clinics remain separate.\n'
                    'Operator workflow and teacher routes: docs/COURSE_ONLINE.md.\n')

    def status(self):
        self.render()
        raw = self.dc('ps', '--all', '--format', 'json').decode().strip()
        try:
            rows = json.loads(raw or '[]')
        except json.JSONDecodeError:
            rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        if isinstance(rows, dict):
            rows = [rows]
        states = {r['Service']: {'state': r.get('State'), 'health': r.get('Health')}
                  for r in rows if r['Service'] in ('db', 'web', 'notification-worker', 'gateway')}
        ready = all(states.get(s, {}).get('state') == 'running'
                    for s in ('db', 'web', 'notification-worker', 'gateway'))
        ready = ready and all(states.get(s, {}).get('health') == 'healthy'
                              for s in ('db', 'web', 'gateway'))
        tls = False
        try:
            ctx = ssl.create_default_context(cafile=self.ca_file)
            conn = OriginHTTPS(self.plan['host'], self.plan['ports'][1], context=ctx, timeout=10)
            try:
                conn.request('GET', '/health/', headers={'Host': self.plan['host']})
                reply = conn.getresponse()
                tls = reply.status == 200 and json.loads(reply.read(4096)).get('status') == 'ok'
            finally:
                conn.close()
        except (OSError, ValueError, http.client.HTTPException):
            pass
        copies = backup_inventory(self.bundle / 'backups', self.plan['project'])
        return {'status': 'ORIGIN_READY' if ready and tls else 'DEGRADED',
                'project': self.plan['project'], 'source_commit': self.plan['requested_source_commit'],
                'rehearsal': self.rehearsal, 'read_only': False, 'services': states,
                'origin_trusted_https': tls, 'public_acceptance_executed': False,
                'course_online_readiness': 'NOT_RUN', 'last_server_backup': copies[-1]['created_at'] if copies else None}

    def backup(self, recipient_file, age='age'):
        recipient = private_file(recipient_file).read_text().strip()
        if not RECIPIENT.fullmatch(recipient):
            raise ValueError('Use one age X25519 public recipient; private keys stay on the Mac.')
        name = 'backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + self.plan['project'] + '.tar.age'
        folder = private_directory(self.bundle / 'backups')
        with exclusive(folder / '.backup.lock'), tempfile.TemporaryDirectory(dir=folder) as temporary:
            temporary = Path(temporary)
            dump = temporary / 'database.dump'
            with dump.open('xb') as stream:
                os.fchmod(stream.fileno(), 0o600)
                self.dc('exec', '-T', 'db', 'sh', '-c',
                        'PGPASSWORD="$G4_OWNER_DB_PASSWORD" exec pg_dump -h 127.0.0.1 -U adc_g4_owner '
                        '-d adc_rc_demo -Fc --no-owner --no-privileges', output_file=stream, timeout=600)
            if dump.stat().st_size > MAX_BACKUP_BYTES:
                raise ValueError('Backup exceeds the bounded course dataset; preserve state and review capacity.')
            files = {'database.dump': dump, 'plan.json': self.bundle / 'plan.json',
                     'runtime.env': self.bundle / 'private/runtime.env',
                     'maintenance.env': self.bundle / 'private/maintenance.env',
                     'database.env': self.bundle / 'private/database.env',
                     'compose.yaml': self.bundle / 'compose.yaml', 'compose.env': self.bundle / 'compose.env',
                     'nginx.conf': self.bundle / 'nginx.conf', 'init-db.sh': self.bundle / 'init-db.sh'}
            meta = {'format': 1, 'project': self.plan['project'], 'server_major': 17,
                    'source_commit': self.plan['requested_source_commit'], 'images': self.plan['images'],
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'files': {key: {'sha256': digest(value), 'size': value.stat().st_size}
                              for key, value in files.items()}}
            atomic_text(temporary / 'archive.json', json.dumps(meta, indent=2) + '\n')
            archive_path = temporary / 'backup.tar'
            with tarfile.open(archive_path, 'w') as archive:
                for key, value in files.items():
                    archive.add(value, arcname=key, recursive=False)
                archive.add(temporary / 'archive.json', arcname='archive.json', recursive=False)
            pending = temporary / name
            run([age, '-r', recipient, '-o', str(pending), str(archive_path)], self.log, timeout=120)
            os.chmod(pending, 0o600)
            os.replace(pending, folder / name)
            record = {'name': name, 'project': self.plan['project'], 'created_at': meta['created_at'],
                      'size': (folder / name).stat().st_size, 'sha256': digest(folder / name)}
            atomic_text(folder / (name + '.json'), json.dumps(record) + '\n')
            prune_backups(folder, self.plan['project'], 7)
        return {'status': 'SERVER_BACKUP_CREATED', 'name': name, 'sha256': record['sha256'],
                'off_host_copy': 'NOT_CHECKED'}

    def restore(self, encrypted, identity, age='age'):
        encrypted, identity = private_file(encrypted), private_file(identity)
        with exclusive(self.bundle / 'private/restore.lock'), tempfile.TemporaryDirectory(dir=self.bundle / 'private') as temporary:
            temporary = Path(temporary)
            meta = decrypt_backup(encrypted, identity, temporary, self.log, age)
            if meta['project'] == self.plan['project']:
                raise ValueError('Restore requires a different project.')
            if meta['source_commit'] != self.plan['requested_source_commit'] or meta['images']['app'] != self.plan['images']['app']:
                raise ValueError('Restore only into the matching reviewed application image/schema.')
            return self.restore_decrypted(temporary / 'database.dump', meta)

    def restore_decrypted(self, dump, meta):
        # A Mac operator can transfer a verified dump through pinned SSH without
        # ever uploading the private decryption key. Its checksum remains bound
        # to the decrypted archive manifest.
        dump = private_file(dump)
        if (meta.get('server_major') != 17 or meta.get('project') == self.plan['project'] or
                meta.get('source_commit') != self.plan['requested_source_commit'] or
                meta['images']['app'] != self.plan['images']['app'] or
                meta['files']['database.dump']['sha256'] != digest(dump) or
                meta['files']['database.dump']['size'] != dump.stat().st_size):
            raise ValueError('Verified recovery dump does not match the target contract.')
        self.start_database()
        if self.tables() or self.dc('ps', '--status', 'running', '-q', 'web').strip():
            raise ValueError('Restore requires an empty target; existing tables or live web are refused.')
        with dump.open('rb') as stream:
            self.dc('exec', '-T', 'db', 'sh', '-c',
                    'PGPASSWORD="$G4_OWNER_DB_PASSWORD" exec pg_restore -h 127.0.0.1 -U adc_g4_owner '
                    '-d adc_rc_demo --no-owner --no-privileges --single-transaction --exit-on-error',
                    input_file=stream, timeout=600)
        self.dc('--profile', 'maintenance', 'run', '--rm', 'schema', timeout=300)
        self.start_runtime()
        atomic_text(self.bundle / 'private/deployed.json', json.dumps({
            'project': self.plan['project'], 'source_commit': self.plan['requested_source_commit'],
            'fresh_seed': False, 'restored_from': meta['project']}) + '\n')
        return {'status': 'INDEPENDENT_RESTORE_COMPLETED', 'source_project': meta['project'],
                'target_project': self.plan['project'], 'business_comparison': 'REQUIRED',
                'public_acceptance_executed': False}

    def tls(self, public_ip, certbot='certbot'):
        if self.rehearsal or self.plan['ports'] != [80, 443]:
            raise ValueError('Public certificate issuance is unavailable in a local rehearsal.')
        address = ipaddress.IPv4Address(public_ip)
        if not address.is_global:
            raise ValueError('An explicit global server IPv4 address is required.')
        addresses = {r[4][0] for r in socket.getaddrinfo(self.plan['host'], 80, socket.AF_INET)}
        if addresses != {str(address)}:
            raise ValueError('Actual hostname A records must resolve to this server.')
        if has_ipv6(self.plan['host']):
            raise ValueError('Remove unreviewed AAAA records before IPv4-only issuance.')
        if self.dc('ps', '--status', 'running', '-q', 'gateway').strip():
            raise ValueError('Initial challenge listener requires the gateway to be stopped.')
        challenge = self.bundle / 'private/http-challenge.conf'
        atomic_text(challenge, 'server { listen 80 default_server; server_name _; return 444; }\n'
                    'server { listen 80; server_name ' + self.plan['host'] + '; '
                    'location ^~ /.well-known/acme-challenge/ { root /srv/acme; } '
                    'location / { return 404; } }\n')
        cid = run(self.docker + ['run', '-d', '--rm', '--label', 'adc.course.project=' + self.plan['project'],
                  '-p', '0.0.0.0:80:80', '-v', str(challenge) + ':/etc/nginx/conf.d/default.conf:ro',
                  '-v', str(self.bundle / 'acme') + ':/srv/acme:ro', self.plan['images']['nginx']], self.log).decode().strip()
        try:
            run(self.certbot_command(certbot) + ['certonly', '--non-interactive', '--agree-tos',
                '--register-unsafely-without-email', '--webroot', '-w', str(self.bundle / 'acme'),
                '-d', self.plan['host'], '--cert-name', self.plan['project']], self.log, timeout=180)
            self.copy_certificate()
        finally:
            run(self.docker + ['stop', cid], self.log, timeout=30)
        return {'status': 'CERTIFICATE_ISSUED', 'public_acceptance_executed': False}

    def certbot_command(self, binary):
        return [binary, '--config-dir', str(self.bundle / 'private/certbot'),
                '--work-dir', str(self.bundle / 'private/certbot-work'),
                '--logs-dir', str(self.bundle / 'private/certbot-logs')]

    def copy_certificate(self):
        source = self.bundle / 'private/certbot/live' / self.plan['project']
        for name in ('fullchain.pem', 'privkey.pem'):
            atomic_text(self.bundle / 'tls' / name, (source / name).read_text())

    def renew(self, certbot='certbot', dry_run=False):
        if self.rehearsal:
            raise ValueError('Rehearsal certificates are never renewed against the public CA.')
        run(self.certbot_command(certbot) + ['renew', '--non-interactive', '--cert-name', self.plan['project']]
            + (['--dry-run'] if dry_run else []), self.log, timeout=300)
        previous = {n: (self.bundle / 'tls' / n).read_text() for n in ('fullchain.pem', 'privkey.pem')}
        try:
            if not dry_run:
                self.copy_certificate()
            self.dc('exec', '-T', 'gateway', 'nginx', '-t')
            self.dc('exec', '-T', 'gateway', 'nginx', '-s', 'reload')
        except BaseException:
            for name, value in previous.items():
                atomic_text(self.bundle / 'tls' / name, value)
            raise
        return {'status': 'RENEWAL_DRY_RUN_PASS' if dry_run else 'CERTIFICATE_RENEWAL_CHECKED',
                'public_acceptance_executed': False}

    def install_jobs(self, recipient_file):
        if self.rehearsal or sys.platform != 'linux' or os.geteuid() != 0:
            raise ValueError('Install server jobs only as root on the dedicated cloud host.')
        recipient = private_file(recipient_file).read_text().strip()
        if not RECIPIENT.fullmatch(recipient):
            raise ValueError('Invalid backup recipient.')
        destination = self.bundle / 'private/backup-recipient.txt'
        atomic_text(destination, recipient + '\n')
        base = [sys.executable, str(ROOT / 'scripts/g4_course.py'), '--output', str(self.bundle),
                '--docker', self.docker[0], '--context', self.docker[2]]
        # Systemd escaping differs from shell escaping: use simple, absolute,
        # whitespace-free owned deployment paths, and forbid specifiers.
        if any(not re.fullmatch(r'[a-zA-Z0-9_./-]+', part) for part in base):
            raise ValueError('Server unit arguments require simple absolute paths.')
        units = Path('/etc/systemd/system')
        for name, schedule, command in (
                ('backup', 'daily', base + ['backup', '--recipient-file', str(destination)]),
                ('renew', '*-*-* 00,12:00:00', base + ['renew-tls'])):
            stem = self.plan['project'] + '-' + name
            service = '[Unit]\nDescription=ADC course ' + name + '\nAfter=docker.service network-online.target\n' + (
                '[Service]\nType=oneshot\nUMask=0077\nExecStart=' + ' '.join(command) + '\n')
            timer = '[Unit]\nDescription=ADC course ' + name + ' timer\n[Timer]\nOnCalendar=' + (
                schedule + '\nPersistent=true\n[Install]\nWantedBy=timers.target\n')
            for suffix, contents in (('.service', service), ('.timer', timer)):
                path = units / (stem + suffix)
                if path.exists() and path.read_text() != contents:
                    raise ValueError('Existing server unit differs; preserve and review it.')
                atomic_text(path, contents)
            run(['systemctl', 'daemon-reload'], self.log)
            run(['systemctl', 'enable', '--now', stem + '.timer'], self.log)
        run(['systemctl', 'enable', 'docker.service'], self.log)
        return {'status': 'SERVER_TIMERS_INSTALLED', 'backup': 'daily', 'renewal': 'twice_daily',
                'off_host_copy': 'Mac synchronization still required'}


def has_ipv6(host):
    try:
        return bool(socket.getaddrinfo(host, 80, socket.AF_INET6))
    except socket.gaierror:
        return False


def backup_inventory(folder, project):
    rows = []
    for path in sorted(Path(folder).glob('backup-*.tar.age.json')):
        private_file(path)
        row = json.loads(path.read_text())
        if not BACKUP_NAME.fullmatch(row['name']) or row['name'] + '.json' != path.name or row['project'] != project:
            raise ValueError('Backup identity or filename differs.')
        encrypted = private_file(Path(folder) / row['name'])
        if row['size'] != encrypted.stat().st_size or row['sha256'] != digest(encrypted):
            raise ValueError('Encrypted backup checksum differs; no synchronization or pruning.')
        rows.append(row)
    return sorted(rows, key=lambda r: r['name'])


def prune_backups(folder, project, keep):
    rows = backup_inventory(folder, project)
    for row in rows[:-keep]:
        (Path(folder) / row['name']).unlink()
        (Path(folder) / (row['name'] + '.json')).unlink()


def decrypt_backup(encrypted, identity, target, log, age='age'):
    private_file(encrypted)
    private_file(identity)
    archive_path = Path(target) / 'backup.tar'
    run([age, '-d', '-i', str(identity), '-o', str(archive_path), str(encrypted)], log, timeout=120)
    os.chmod(archive_path, 0o600)
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        names = [m.name for m in members]
        if (len(names) != len(set(names)) or len(names) > 12 or
                sum(m.size for m in members) > MAX_BACKUP_BYTES + 1024 * 1024 or
                any(not m.isfile() or m.name != PurePosixPath(m.name).name for m in members) or
                'archive.json' not in names):
            raise ValueError('Unsafe backup archive refused.')
        meta = json.load(archive.extractfile('archive.json'))
        if (meta.get('format') != 1 or meta.get('server_major') != 17 or
                not re.fullmatch(r'adc_g4_[0-9a-f]{12}', meta.get('project', '')) or
                not re.fullmatch(r'[0-9a-f]{40}', meta.get('source_commit', '')) or
                set(names) != set(meta['files']) | {'archive.json'} or
                'database.dump' not in meta['files']):
            raise ValueError('Backup format or provenance differs.')
        for member in members:
            destination = Path(target) / member.name
            with destination.open('xb') as stream:
                os.fchmod(stream.fileno(), 0o600)
                shutil.copyfileobj(archive.extractfile(member), stream)
            if member.name != 'archive.json':
                fact = meta['files'][member.name]
                if fact['size'] != destination.stat().st_size or fact['sha256'] != digest(destination):
                    raise ValueError('Decrypted backup checksum differs.')
    return meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / '.g4'))
    parser.add_argument('--docker', default='docker')
    parser.add_argument('--context', required=True)
    parser.add_argument('--rehearsal', action='store_true')
    parser.add_argument('--architecture', choices=('amd64', 'arm64'), default='amd64')
    parser.add_argument('--ca-file')
    sub = parser.add_subparsers(dest='action', required=True)
    build_parser = sub.add_parser('build')
    build_parser.add_argument('--artifacts', required=True)
    for name in ('deploy', 'status', 'list-backups'):
        sub.add_parser(name)
    backup = sub.add_parser('backup')
    backup.add_argument('--recipient-file', required=True)
    backup.add_argument('--age', default='age')
    restore = sub.add_parser('restore')
    restore.add_argument('--backup-file', required=True)
    restore.add_argument('--identity-file', required=True)
    restore.add_argument('--age', default='age')
    restore.add_argument('--trusted-synthetic-copy', action='store_true', required=True)
    plain = sub.add_parser('restore-verified-dump')
    plain.add_argument('--dump-file', required=True)
    plain.add_argument('--manifest-file', required=True)
    plain.add_argument('--trusted-synthetic-copy', action='store_true', required=True)
    tls = sub.add_parser('issue-tls')
    tls.add_argument('--public-ip', required=True)
    tls.add_argument('--certbot', default='certbot')
    renew = sub.add_parser('renew-tls')
    renew.add_argument('--certbot', default='certbot')
    renew.add_argument('--dry-run', action='store_true')
    jobs = sub.add_parser('install-server-jobs')
    jobs.add_argument('--recipient-file', required=True)
    args = parser.parse_args()
    # Explicit flags win; ambient Compose profiles/files must not activate maintenance.
    for key in tuple(os.environ):
        if key.startswith('COMPOSE_'):
            os.environ.pop(key)
    if args.action == 'build':
        result = build(args.artifacts, args.docker, args.context, args.architecture)
    else:
        course = Course(args.output, args.docker, args.context, rehearsal=args.rehearsal,
                        architecture=args.architecture, ca_file=args.ca_file)
        if args.action == 'deploy':
            result = course.deploy()
        elif args.action == 'status':
            result = course.status()
        elif args.action == 'backup':
            result = course.backup(args.recipient_file, args.age)
        elif args.action == 'restore':
            result = course.restore(args.backup_file, args.identity_file, args.age)
        elif args.action == 'restore-verified-dump':
            result = course.restore_decrypted(args.dump_file, json.loads(private_file(args.manifest_file).read_text()))
        elif args.action == 'issue-tls':
            result = course.tls(args.public_ip, args.certbot)
        elif args.action == 'renew-tls':
            result = course.renew(args.certbot, args.dry_run)
        elif args.action == 'install-server-jobs':
            result = course.install_jobs(args.recipient_file)
        else:
            result = {'project': course.plan['project'],
                      'backups': backup_inventory(course.bundle / 'backups', course.plan['project'])}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError, tarfile.TarError):
        raise SystemExit('Course operation stopped. Preserve state and inspect private diagnostics; no cloud acceptance granted.') from None
