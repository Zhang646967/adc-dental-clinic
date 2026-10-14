"""Offline G4 bundle preparation/inspection: no Docker, SSH, DNS or DB writes.

Creates a NEW private .g4 directory only. It never edits .env/.rc, installs a
certificate, deploys a service, or reports public acceptance from file checks.
"""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config.production_contract import validate_production_inputs


def read_env(path):
    values = {}
    for line in path.read_text(encoding='ascii').splitlines():
        if not line or line.startswith('#'):
            continue
        key, value = line.split('=', 1)
        if key in values:
            raise ValueError('Duplicate private configuration key.')
        values[key] = value
    return values


def pinned_image(value):
    return bool(re.fullmatch(r'(?:sha256:[0-9a-f]{64}|[a-z0-9][a-z0-9._/:\-]*@sha256:[0-9a-f]{64})', value))


def write_private(path, text):
    with path.open('x', encoding='utf-8') as output:
        os.chmod(path, 0o600)
        output.write(text)


def write_env(path, values):
    write_private(path, ''.join(k + '=' + str(v) + '\n' for k, v in values.items()))


def prepare(output, *, host, source_commit, app_image, db_image, nginx_image,
            bind_ip='127.0.0.1', http_port=80, https_port=443):
    output = Path(output)
    if output.name != '.g4' or output.exists() or output.is_symlink():
        raise ValueError('Use a new private directory named .g4; existing state is never overwritten.')
    if not re.fullmatch('[0-9a-f]{40}', source_commit):
        raise ValueError('A complete reviewed source commit is required.')
    if not all(pinned_image(x) for x in (app_image, db_image, nginx_image)):
        raise ValueError('All images must be pinned by SHA-256 digest/image ID.')
    if not db_image.startswith('postgres:17@sha256:') or not nginx_image.startswith('nginx:stable-alpine@sha256:'):
        raise ValueError('This bundle supports pinned PostgreSQL 17 and Nginx stable-alpine only.')
    if ipaddress.ip_address(bind_ip).version != 4:
        raise ValueError('This first bundle uses explicit IPv4 binding; review IPv6 separately.')
    if not all(isinstance(p, int) and 1 <= p <= 65535 for p in (http_port, https_port)) or http_port == https_port:
        raise ValueError('Two distinct valid gateway ports are required.')
    # Validate before creating any files. Secrets are generated separately from
    # the Mac configuration and are never printed.
    runtime = {
        'DJANGO_SETTINGS_MODULE': 'config.settings.production',
        'ADC_DEPLOYMENT_STAGE': 'staging', 'ADC_PUBLIC_HOST': host,
        'DJANGO_SECRET_KEY': secrets.token_urlsafe(64),
        'POSTGRES_DB': 'adc_rc_demo', 'POSTGRES_USER': 'adc_g4_runtime',
        'POSTGRES_PASSWORD': secrets.token_urlsafe(48),
        'ADC_DATABASE_OWNER': 'adc_g4_owner', 'DB_HOST': 'db', 'DB_PORT': '5432',
        'ADC_DB_SSLMODE': 'disable', 'ADC_PRIVATE_DB_NETWORK_ACK': '1',
        'ADC_TRUST_PROXY_HEADERS': '1', 'ADC_READ_ONLY': '1',
        'AI_MODE': 'disabled', 'AI_API_KEY': '', 'OPENAI_API_KEY': '',
    }
    checked = validate_production_inputs(runtime)
    runtime['ADC_PUBLIC_HOST'] = checked.host
    owner_password = secrets.token_urlsafe(48)
    admin_password = secrets.token_urlsafe(48)
    maintenance = runtime | {
        'DJANGO_SETTINGS_MODULE': 'config.settings.g4_maintenance',
        'ADC_G4_MAINTENANCE': '1', 'ADC_MIGRATION_PASSWORD': owner_password,
        'ADC_READ_ONLY': '0',
    }
    database = {
        'POSTGRES_DB': 'adc_rc_demo', 'POSTGRES_USER': 'adc_g4_admin',
        'POSTGRES_PASSWORD': admin_password, 'G4_OWNER_DB_PASSWORD': owner_password,
        'G4_RUNTIME_DB_PASSWORD': runtime['POSTGRES_PASSWORD'],
    }
    output.mkdir(mode=0o700)
    for directory in ('private', 'tls', 'acme', 'backups'):
        (output / directory).mkdir(mode=0o755 if directory == 'acme' else 0o700)
    # HTTP-01 challenge tokens are intentionally public, unlike certificates'
    # private keys and credentials. Nginx's worker must traverse these folders.
    for directory in ('acme/.well-known', 'acme/.well-known/acme-challenge'):
        (output / directory).mkdir(mode=0o755)
    write_env(output / 'private/runtime.env', runtime)
    write_env(output / 'private/maintenance.env', maintenance)
    write_env(output / 'private/database.env', database)
    project = 'adc_g4_' + secrets.token_hex(6)
    write_env(output / 'compose.env', {
        'G4_PROJECT': project, 'G4_SOURCE_COMMIT': source_commit,
        'G4_APP_IMAGE': app_image, 'G4_DB_IMAGE': db_image, 'G4_NGINX_IMAGE': nginx_image,
        'G4_BIND_IP': bind_ip, 'G4_HTTP_PORT': http_port, 'G4_HTTPS_PORT': https_port,
    })
    templates = ROOT / 'deployment/g4'
    for source, target in [('compose.template.yaml', 'compose.yaml'), ('init-db.sh', 'init-db.sh')]:
        (output / target).write_bytes((templates / source).read_bytes())
    os.chmod(output / 'init-db.sh', 0o555)
    nginx = (templates / 'nginx.template.conf').read_text().replace('__ADC_HOST__', checked.host)
    (output / 'nginx.conf').write_text(nginx)
    plan = {
        'status': 'PREPARED_NOT_DEPLOYED', 'project': project, 'host': checked.host,
        'requested_source_commit': source_commit, 'read_only': True,
        'bind_ip': bind_ip, 'ports': [http_port, https_port],
        'images': {'app': app_image, 'db': db_image, 'nginx': nginx_image},
        'public_acceptance_executed': False,
        'pending': ['Actual server/SSH and firewall', 'DNS and trusted TLS',
                    'Image revision/architecture inspection', 'Target backup/restore and monitoring',
                    'Target HTTPS/browser/restart/capacity checks'],
        'file_sha256': {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                        for name in ('compose.yaml', 'init-db.sh', 'nginx.conf')},
    }
    write_private(output / 'plan.json', json.dumps(plan, indent=2) + '\n')
    return plan


def inspect_bundle(output, rendered=None):
    output = Path(output)
    plan = json.loads((output / 'plan.json').read_text())
    if not re.fullmatch('adc_g4_[0-9a-f]{12}', plan['project']):
        raise ValueError('Invalid G4 project identity.')
    for name, expected in plan['file_sha256'].items():
        if hashlib.sha256((output / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Prepared public configuration differs; review and regenerate in a new directory.')
    for name in ('compose.env', 'plan.json', 'private/runtime.env', 'private/maintenance.env', 'private/database.env'):
        path = output / name
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError('Private configuration must be nonsymlink files with owner-only access.')
    runtime = read_env(output / 'private/runtime.env')
    maintenance = read_env(output / 'private/maintenance.env')
    database = read_env(output / 'private/database.env')
    inputs = validate_production_inputs(runtime)
    if not inputs.read_only or runtime['DJANGO_SETTINGS_MODULE'] != 'config.settings.production':
        raise ValueError('First G4 acceptance must use read-only runtime production settings.')
    if runtime['AI_MODE'] != 'disabled' or runtime.get('ADC_MIGRATION_PASSWORD') or runtime.get('ADC_G4_MAINTENANCE'):
        raise ValueError('Runtime must not receive maintenance credentials/flags or external AI.')
    if (maintenance.get('DJANGO_SETTINGS_MODULE') != 'config.settings.g4_maintenance' or
            maintenance.get('ADC_G4_MAINTENANCE') != '1' or
            maintenance.get('ADC_MIGRATION_PASSWORD') != database['G4_OWNER_DB_PASSWORD'] or
            runtime['POSTGRES_PASSWORD'] != database['G4_RUNTIME_DB_PASSWORD'] or
            runtime['DJANGO_SECRET_KEY'] != maintenance['DJANGO_SECRET_KEY']):
        raise ValueError('Owner/runtime private configuration is inconsistent.')
    passwords = [database['POSTGRES_PASSWORD'], database['G4_OWNER_DB_PASSWORD'], database['G4_RUNTIME_DB_PASSWORD']]
    if len(set(passwords)) != 3 or any(len(p) < 32 for p in passwords):
        raise ValueError('Admin, migration and runtime passwords must be separate strong values.')
    if rendered:
        doc = json.loads(Path(rendered).read_text())
        services = doc['services']
        if set(services) != {'db', 'schema', 'bootstrap', 'web', 'notification-worker', 'gateway'}:
            raise ValueError('Unexpected deployment services.')
        if not doc['networks']['private'].get('internal') or any(n.get('external') for n in doc['networks'].values()):
            raise ValueError('G4 database network must remain private and self-contained.')
        for name, service in services.items():
            if service.get('privileged') or service.get('network_mode') or service.get('container_name'):
                raise ValueError('Unsafe deployment service option.')
            if name != 'gateway' and service.get('ports'):
                raise ValueError('Only the HTTPS gateway may publish ports.')
        for name in ('web', 'notification-worker'):
            if services[name]['environment'] != runtime or services[name]['image'] != plan['images']['app']:
                raise ValueError('Runtime service configuration does not match the reviewed bundle.')
        ports = services['gateway'].get('ports', [])
        if len(ports) != 2 or {int(p['target']) for p in ports} != {80, 443}:
            raise ValueError('Gateway must publish only HTTP/HTTPS.')
        if any(p.get('host_ip') != plan['bind_ip'] for p in ports):
            raise ValueError('Gateway binding does not match the reviewed plan.')
    return {'status': 'PREPARED_NOT_DEPLOYED', 'configuration_checks': 'PASS',
            'project': plan['project'], 'host': inputs.host, 'read_only': True,
            'tls_files_present': all((output / 'tls' / p).is_file() for p in ('fullchain.pem', 'privkey.pem')),
            'public_acceptance_executed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    prepare_parser = sub.add_parser('prepare')
    for name in ('host', 'source-commit', 'app-image', 'db-image', 'nginx-image'):
        prepare_parser.add_argument('--' + name, required=True)
    prepare_parser.add_argument('--output', default=str(ROOT / '.g4'))
    prepare_parser.add_argument('--bind-ip', default='127.0.0.1')
    prepare_parser.add_argument('--http-port', type=int, default=80)
    prepare_parser.add_argument('--https-port', type=int, default=443)
    inspect_parser = sub.add_parser('inspect')
    inspect_parser.add_argument('--output', default=str(ROOT / '.g4'))
    inspect_parser.add_argument('--rendered-compose')
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            plan = prepare(args.output, host=args.host, source_commit=args.source_commit,
                           app_image=args.app_image, db_image=args.db_image, nginx_image=args.nginx_image,
                           bind_ip=args.bind_ip, http_port=args.http_port, https_port=args.https_port)
            result = {'status': plan['status'], 'project': plan['project'], 'host': plan['host'],
                      'credentials': 'private files only; not displayed', 'public_acceptance_executed': False}
        else:
            result = inspect_bundle(args.output, args.rendered_compose)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError):
        raise SystemExit('G4 preparation/inspection stopped. Preserve partial state; inspect private files locally. No deployment performed.') from None
