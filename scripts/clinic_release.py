"""Linux installation, upgrade and recovery of an independent dental clinic."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.g4_course import Course, build, exclusive, private_file
from scripts.g4_prepare import prepare
from scripts.g4_release import pending_additive
from scripts.g4_mac_demo import atomic_text


class ClinicInstallation(Course):
    access_mode = 'clinic-writable'
    db_name = 'adc_clinic'

    def deploy(self, institution):
        if pending_additive(self.bundle):
            raise ValueError('Resolve the pending release first.')
        marker = self.bundle / 'private/deployed.json'
        phase = self.bundle / 'private/installation-phase.json'
        revision = self.plan['requested_source_commit']
        identity = {'project': self.plan['project'], 'source_commit': revision}
        if marker.exists():
            previous = json.loads(private_file(marker).read_text())
            if previous['project'] != identity['project']:
                raise ValueError('Existing deployment belongs to a different installation.')
            return self.status()
        institution = private_file(institution)
        if institution.stat().st_size > 16384:
            raise ValueError('Institution file is too large.')
        self.start_database()
        target = self.database_identity()
        expected = identity | {'target': target}
        if phase.exists():
            record = json.loads(private_file(phase).read_text())
            if record != expected:
                raise ValueError('Resume requires the original installation, image and database volume.')
        else:
            if self.tables():
                raise ValueError('Existing schema cannot be initialized by a fresh installation.')
            atomic_text(phase, json.dumps(expected) + '\n')
        if set(self.dc('ps', '--status', 'running', '--services').decode().split()) - {'db'}:
            result = self.status()
            if result['status'] != 'ORIGIN_READY':
                raise ValueError('Unexpected active services during initialization.')
        else:
            self.dc('--profile', 'maintenance', 'run', '--rm', '-T', 'schema', timeout=600)
        base = ['--profile', 'maintenance', 'run', '--rm', '-T', '--no-deps', 'bootstrap']
        state = json.loads(self.dc(*base, 'python', 'manage.py', 'initialize_clinic', '--status-only'))
        if state['status'] == 'UNINITIALIZED':
            with institution.open('rb') as stream:
                state = json.loads(self.dc(*base, input_file=stream, timeout=90))
        if state != {'status': 'INITIALIZED'} and state != {
                'status': 'INITIALIZED', 'clinics_created': 1, 'technical_administrators_created': 1}:
            raise ValueError('Database initialization did not return a completion receipt.')
        self.start_runtime()
        result = self.status()
        if result['status'] != 'ORIGIN_READY':
            raise ValueError('Initial HTTPS and application health verification failed.')
        atomic_text(marker, json.dumps(identity | {'fresh_seed': False, 'empty_clinic_installation': True}) + '\n')
        return result


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', type=Path, default=Path('.g4'))
    cli.add_argument('--context', required=True, help='Named local Docker context with Unix endpoint')
    cli.add_argument('--architecture', choices=('amd64', 'arm64'), default='amd64')
    cli.add_argument('--rehearsal', action='store_true', help='Use isolated loopback ports and a private CA')
    cli.add_argument('--ca-file', type=Path)
    commands = cli.add_subparsers(dest='action', required=True)
    package = commands.add_parser('build')
    package.add_argument('--artifacts', required=True)
    package.add_argument('--source-commit', required=True)
    setup = commands.add_parser('prepare')
    for field in ('host', 'source-commit', 'app-image', 'db-image', 'nginx-image'):
        setup.add_argument('--' + field, required=True)
    setup.add_argument('--bind-ip', default='127.0.0.1')
    setup.add_argument('--http-port', type=int, default=80)
    setup.add_argument('--https-port', type=int, default=443)
    setup.add_argument('--wechat-mini-app-id')
    setup.add_argument('--wechat-mini-secret-file', type=Path)
    install = commands.add_parser('install')
    install.add_argument('--institution-file', type=Path, required=True)
    commands.add_parser('status')
    for name in ('backup', 'upgrade', 'rollback'):
        command = commands.add_parser(name)
        command.add_argument('--recipient-file', type=Path, required=True)
        command.add_argument('--age', default='age')
        if name != 'backup':
            command.add_argument('--expected-current-commit', required=True)
        if name == 'upgrade':
            command.add_argument('--artifacts', type=Path, required=True)
            command.add_argument('--allow-additive-migrations', action='store_true')
        if name == 'rollback':
            command.add_argument('--to-source', required=True)
    restore = commands.add_parser('restore')
    restore.add_argument('--backup-file', type=Path, required=True)
    restore.add_argument('--identity-file', type=Path, required=True)
    restore.add_argument('--source-project', required=True, help='Source institution installation from the trusted custody record')
    restore.add_argument('--backup-sha256', required=True, help='Ciphertext digest from the trusted custody record')
    restore.add_argument('--age', default='age')
    tls = commands.add_parser('issue-tls')
    tls.add_argument('--public-ip', required=True)
    args = cli.parse_args()
    for key in list(os.environ):
        if key.startswith('COMPOSE_'):
            os.environ.pop(key)
    if args.action == 'build':
        return build(args.artifacts, 'docker', args.context, args.architecture, source_commit=args.source_commit)
    if args.action == 'prepare':
        plan = prepare(args.output, host=args.host, source_commit=args.source_commit,
                       app_image=args.app_image, db_image=args.db_image, nginx_image=args.nginx_image,
                       bind_ip=args.bind_ip, http_port=args.http_port, https_port=args.https_port,
                       access_mode='clinic-writable', dataset='empty', architecture=args.architecture,
                       wechat_mini_app_id=args.wechat_mini_app_id, wechat_mini_secret_file=args.wechat_mini_secret_file)
        return {'status': plan['status'], 'project': plan['project']}
    clinic = ClinicInstallation(args.output, context=args.context, rehearsal=args.rehearsal,
                               architecture=args.architecture, ca_file=args.ca_file,
                               resume_additive=getattr(args, 'allow_additive_migrations', False))
    if args.action == 'install':
        with exclusive(clinic.bundle / 'private/release.lock'):
            return clinic.deploy(args.institution_file)
    if args.action == 'status':
        return clinic.status()
    if args.action == 'issue-tls':
        return clinic.tls(args.public_ip)
    if args.action == 'restore':
        return clinic.restore(args.backup_file, args.identity_file, args.age, schema_mode='migration-built',
                              expected_source=args.source_project, expected_sha256=args.backup_sha256)
    if args.action == 'upgrade':
        return clinic.upgrade(args.artifacts, args.recipient_file, args.expected_current_commit,
                              args.age, allow_additive=args.allow_additive_migrations)
    if args.action == 'rollback':
        return clinic.rollback(args.to_source, args.recipient_file, args.expected_current_commit, args.age)
    with exclusive(clinic.bundle / 'private/release.lock'):
        if pending_additive(clinic.bundle):
            raise ValueError('Resume the pending upgrade before scheduling a backup.')
        return clinic.backup(args.recipient_file, args.age)


if __name__ == '__main__':
    try:
        print(json.dumps(main(), indent=2))
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from None
