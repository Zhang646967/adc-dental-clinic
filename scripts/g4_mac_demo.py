"""Start/stop the explicitly prepared, read-only Mac course demonstration.

No account, DNS changes, router forwarding, credential output or volume removal.
Use only a verified cloudflared binary and a separate mac_tunnel .g4 bundle.
"""
import argparse
import fcntl
import hashlib
from http.client import HTTPConnection, HTTPException
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.g4_prepare import inspect_bundle, read_env

HOST_PATTERN = r'[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com'
DOCKER = '/Applications/Docker.app/Contents/Resources/bin/docker'


def atomic_text(path, text):
    descriptor, temporary = tempfile.mkstemp(prefix='.g4-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(text)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def process_stamp(pid):
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart=', '-o', 'command='],
                            capture_output=True, text=True, timeout=5)
    return result.stdout.strip() if result.returncode == 0 else ''


def matches_process(metadata):
    pid = metadata.get('pid')
    return bool(type(pid) is int and pid > 0 and metadata.get('process_stamp') and
                process_stamp(metadata['pid']) == metadata['process_stamp'])


def check_origin(hostname, port):
    connection = HTTPConnection('127.0.0.1', port, timeout=10)
    try:
        connection.request('GET', '/health/', headers={'Host': hostname, 'X-Forwarded-Proto': 'https'})
        response = connection.getresponse()
        body = response.read(4097)
        try:
            healthy = len(body) <= 4096 and json.loads(body).get('status') == 'ok'
        except (ValueError, AttributeError, UnicodeError):
            healthy = False
        if response.status != 200 or not healthy:
            raise RuntimeError('The actual loopback gateway is not ready.')
    finally:
        connection.close()


def refresh_access(bundle, hostname):
    """Keep the private operator guide current without reading seed credentials."""
    if not re.fullmatch(HOST_PATTERN, hostname):
        raise ValueError('Use the assigned free demo hostname.')
    path = bundle / 'private/DEMO_ACCESS.md'
    text = path.read_text() if path.exists() else (
        '# Temporary course demo access（临时演示登录）\n\n'
        'Business read-only mode. Accounts remain in private `demo-credentials.txt`.\n'
    )
    url = 'https://' + hostname
    for label, route in (('Staff login', '/accounts/login/'), ('Patient login', '/portal/login/')):
        # Replace only the defined login lines; account entries are opaque text.
        pattern = r'^' + re.escape(label) + r': https://' + HOST_PATTERN + re.escape(route) + r'(?=$|[ \t\r])'
        text, replaced = re.subn(pattern, label + ': ' + url + route, text, flags=re.MULTILINE)
        if not replaced:
            text = text.rstrip() + '\n\n' + label + ': ' + url + route + '\n'
    atomic_text(path, text)


def checked_bundle(bundle):
    if sys.platform != 'darwin':
        raise ValueError('This helper is limited to the selected Mac course host.')
    inspect_bundle(bundle)
    plan = json.loads((bundle / 'plan.json').read_text())
    if plan.get('mode') != 'mac_tunnel' or not plan['read_only'] or plan['bind_ip'] != '127.0.0.1':
        raise ValueError('A separate read-only Mac tunnel bundle is required.')
    return plan


def compose_command(bundle, plan):
    endpoint = subprocess.run([DOCKER, '--context', 'desktop-linux', 'context', 'inspect',
                               'desktop-linux', '--format', '{{json .Endpoints.docker.Host}}'],
                              capture_output=True, text=True, check=True, timeout=10)
    if not json.loads(endpoint.stdout).startswith('unix://'):
        raise ValueError('Only the explicit local Docker Desktop context is accepted.')
    return [DOCKER, '--context', 'desktop-linux', 'compose', '--env-file', str(bundle / 'compose.env'),
            '-p', plan['project'], '-f', str(bundle / 'compose.yaml')]


def start(bundle, binary):
    plan = checked_bundle(bundle)
    metadata_file = bundle / 'private/tunnel.json'
    if metadata_file.exists() and matches_process(json.loads(metadata_file.read_text())):
        raise ValueError('The recorded tunnel is already running; use status or stop first.')
    binary = Path(binary).resolve(strict=True)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError('A reviewed executable cloudflared path is required.')
    command = compose_command(bundle, plan)
    gateway = subprocess.run(command + ['ps', '-q', 'gateway'], capture_output=True,
                             text=True, check=True, timeout=20).stdout.strip()
    if not gateway:
        raise ValueError('Initialize and start the separate local gateway before publishing.')
    ports = subprocess.run([DOCKER, '--context', 'desktop-linux', 'inspect', gateway,
                            '--format', '{{json .NetworkSettings.Ports}}'], capture_output=True,
                           text=True, check=True, timeout=10)
    bindings = json.loads(ports.stdout)
    expected = [{'HostIp': '127.0.0.1', 'HostPort': str(plan['ports'][0])}]
    if bindings.get('80/tcp') != expected or any(v for k, v in bindings.items() if k != '80/tcp'):
        raise ValueError('The actual gateway must publish only the reviewed loopback origin.')
    config = bundle / 'private/cloudflared.yaml'
    atomic_text(config, '{}\n')
    log_file = bundle / 'private/tunnel.log'
    with log_file.open('w') as log:
        os.chmod(log_file, 0o600)
        environment = {k: v for k, v in os.environ.items() if not k.startswith('TUNNEL_')}
        environment['NO_PROXY'] = '127.0.0.1,localhost'
        process = subprocess.Popen([str(binary), 'tunnel', '--config', str(config), '--no-autoupdate',
                                    '--protocol', 'http2', '--metrics', '127.0.0.1:0',
                                    '--url', 'http://127.0.0.1:' + str(plan['ports'][0])],
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env=environment)
    try:
        hostname = None
        for _ in range(240):
            found = re.search(r'https://(' + HOST_PATTERN + r')(?=[\s|]|$)', log_file.read_text(errors='replace'))
            if found:
                hostname = found.group(1)
                break
            if process.poll() is not None:
                raise RuntimeError('Tunnel exited; inspect its private log.')
            time.sleep(0.25)
        if not hostname:
            raise RuntimeError('No assigned free hostname; inspect the private tunnel log.')
        # Only the explicit hostname changes on restart. Passwords, image IDs,
        # database identity and business read-only state remain pinned.
        for name in ('runtime.env', 'maintenance.env'):
            path = bundle / 'private' / name
            values = read_env(path)
            values['ADC_PUBLIC_HOST'] = hostname
            atomic_text(path, ''.join(k + '=' + v + '\n' for k, v in values.items()))
        nginx = (ROOT / 'deployment/g4/nginx.mac-tunnel.template.conf').read_text()
        atomic_text(bundle / 'nginx.conf', nginx.replace('__ADC_HOST__', hostname))
        plan['host'] = hostname
        plan['file_sha256']['nginx.conf'] = hashlib.sha256((bundle / 'nginx.conf').read_bytes()).hexdigest()
        atomic_text(bundle / 'plan.json', json.dumps(plan, indent=2) + '\n')
        rendered = subprocess.run(command + ['--profile', 'maintenance', '--profile', 'writer',
                                             'config', '--format', 'json'], capture_output=True,
                                  text=True, check=True, timeout=30)
        private_render = bundle / 'private/rendered.json'
        atomic_text(private_render, rendered.stdout)
        inspect_bundle(bundle, private_render)
        subprocess.run(command + ['up', '-d', '--wait', '--wait-timeout', '90',
                                   '--force-recreate', 'web', 'gateway'], check=True, timeout=120)
        check_origin(hostname, plan['ports'][0])
        if process.poll() is not None:
            raise RuntimeError('Tunnel exited during startup.')
        refresh_access(bundle, hostname)
        metadata = {'pid': process.pid, 'process_stamp': process_stamp(process.pid),
                    'url': 'https://' + hostname, 'project': plan['project'],
                    'read_only': True, 'public_acceptance_executed': False}
        atomic_text(metadata_file, json.dumps(metadata, indent=2) + '\n')
        return {'status': 'TEMPORARY_DEMO_RUNNING', 'url': metadata['url'],
                'read_only': True, 'public_acceptance_executed': False}
    except BaseException:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        raise


def status_or_stop(bundle, stop=False):
    plan = checked_bundle(bundle)
    path = bundle / 'private/tunnel.json'
    metadata = json.loads(path.read_text()) if path.exists() else {}
    running = (metadata.get('project') == plan['project'] and matches_process(metadata))
    if stop and running:
        os.kill(metadata['pid'], signal.SIGTERM)
        metadata['stopped'] = True
        atomic_text(path, json.dumps(metadata, indent=2) + '\n')
    origin_ready = None
    if running and not stop:
        try:
            check_origin(plan['host'], plan['ports'][0])
            origin_ready = True
        except (OSError, HTTPException, RuntimeError):
            origin_ready = False
    status = ('STOP_REQUESTED' if running else 'STOPPED') if stop else (
        'RUNNING' if running and origin_ready else ('DEGRADED' if running else 'STOPPED'))
    return {'status': status, 'tunnel_running': running, 'origin_ready': origin_ready,
            'public_https': 'NOT_CHECKED',
            'url': 'https://' + plan['host'] if running else None, 'database': 'preserved',
            'public_acceptance_executed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'status', 'stop'))
    parser.add_argument('--output', default=str(ROOT / '.g4'))
    parser.add_argument('--cloudflared')
    args = parser.parse_args()
    bundle = Path(args.output).resolve()
    try:
        if args.action == 'start' and not args.cloudflared:
            raise ValueError('Provide the checksum-verified cloudflared path.')
        with (bundle / 'private/tunnel.lock').open('a') as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = start(bundle, args.cloudflared) if args.action == 'start' else status_or_stop(bundle, args.action == 'stop')
        print(json.dumps(result, indent=2))
        if args.action == 'status' and result['status'] != 'RUNNING':
            raise SystemExit(1)
    except (OSError, ValueError, RuntimeError, HTTPException, subprocess.SubprocessError):
        raise SystemExit('Mac demo operation stopped. Preserve private state and inspect .g4/private locally; no volumes removed.') from None
