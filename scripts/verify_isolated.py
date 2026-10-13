"""Host-only isolated Docker validation. Never runs the application's compose.yaml.
Python 3 standard library only. No credentials, existing ports, named volumes or .env read.
This runner validates the rendered Compose contract before creating a unique project.
"""
import json
import os
import ntpath
import re
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def normalized_host_path(value):
    value = str(value).replace('\\', '/')
    if re.match(r'^[A-Za-z]:/', value):
        return ntpath.normcase(ntpath.normpath(value))
    return str(Path(value).resolve())


def validate_configuration(config, root=ROOT):
    services = config.get('services', {})
    if set(services) != {'verify', 'verify-db'}:
        raise ValueError('Isolation requires exactly verify and verify-db services.')
    if any(n.get('external') for n in config.get('networks', {}).values()):
        raise ValueError('External networks are forbidden in isolated validation.')
    if config.get('volumes'):
        raise ValueError('Named/external volumes are forbidden in isolated validation.')
    for name, service in services.items():
        if any(service.get(k) for k in ('ports', 'container_name', 'network_mode', 'privileged', 'devices', 'env_file')):
            raise ValueError('Unsafe service option in isolation contract: ' + name)
        if service.get('volumes') and name != 'verify':
            raise ValueError('The verification database must not mount persistent storage.')
    app, db = services['verify'], services['verify-db']
    env = app.get('environment', {})
    if env.get('DB_HOST') != 'verify-db' or env.get('POSTGRES_DB') != 'adc_verify':
        raise ValueError('Only the isolated verification database may be used.')
    if env.get('DJANGO_SETTINGS_MODULE') != 'config.settings.test':
        raise ValueError('Verification must use test settings.')
    if env.get('AI_API_KEY') or env.get('OPENAI_API_KEY') or env.get('AI_MODE') not in ('demo', 'disabled'):
        raise ValueError('External AI is prohibited in isolated verification.')
    mounts = app.get('volumes', [])
    if len(mounts) != 1:
        raise ValueError('Only the evidence bind mount is permitted.')
    mount = mounts[0]
    expected = normalized_host_path(str(root).replace('\\', '/') + '/evidence/verification')
    if mount.get('type') != 'bind' or mount.get('target') != '/evidence' or normalized_host_path(mount.get('source', '')) != expected:
        raise ValueError('Unexpected bind mount in verification service.')
    if not db.get('tmpfs') or db.get('environment', {}).get('POSTGRES_DB') != 'adc_verify':
        raise ValueError('Verification DB requires tmpfs and adc_verify database.')
    return True


def compose_command(project, env_file, root=ROOT):
    if not project.startswith('adc_verify_') or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_' for c in project):
        raise ValueError('Invalid isolated project name.')
    return ['docker', 'compose', '--env-file', str(env_file), '--project-directory', str(root),
            '-p', project, '-f', str(root / 'compose.verify.yaml')]


def main():
    os.chdir(ROOT)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    project = 'adc_verify_' + stamp.lower() + '_' + uuid4().hex[:8]
    output = ROOT / 'evidence' / 'verification'
    output.mkdir(parents=True, exist_ok=True)
    status = {'project': project, 'timestamp_utc': stamp, 'scope': 'isolated local Docker only',
              'executed': False, 'all_gates_passed': False, 'cleanup_returncode': None}
    env_file = None
    started = False
    cmd = None
    try:
        # A remote Docker host is not an appropriate implicit target for this helper.
        host = os.environ.get('DOCKER_HOST', '')
        if host and not host.startswith(('unix://', 'npipe://')):
            raise ValueError('Use a local Docker Desktop context; remote DOCKER_HOST is not accepted.')
        endpoint = subprocess.run(['docker', 'context', 'inspect', '--format', '{{json .Endpoints.docker.Host}}'],
                                  capture_output=True, text=True, check=True, timeout=30)
        endpoint_host = json.loads(endpoint.stdout.strip())
        if not endpoint_host.startswith(('unix://', 'npipe://')):
            raise ValueError('The current Docker context is remote; choose the local Desktop context.')
        subprocess.run(['docker', 'info'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        # Verify source, but do not import Django or load application settings on the host.
        subprocess.run([sys.executable, str(ROOT / 'scripts/verify_update.py')], check=True, timeout=30)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False, encoding='ascii') as handle:
            handle.write('# Deliberately empty: do not load the application .env.\n')
            env_file = Path(handle.name)
        cmd = compose_command(project, env_file)
        rendered = subprocess.run(cmd + ['config', '--format', 'json'], capture_output=True, text=True,
                                  encoding='utf-8', errors='replace', check=True, timeout=60)
        validate_configuration(json.loads(rendered.stdout))
        with (output / ('host-' + stamp + '.log')).open('x', encoding='utf-8') as log:
            started = True
            process = subprocess.Popen(cmd + ['up', '--build', '--abort-on-container-exit', '--exit-code-from', 'verify'],
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                       encoding='utf-8', errors='replace')
            for line in process.stdout:
                print(line, end='', flush=True); log.write(line); log.flush()
            status['returncode'] = process.wait()
            status['executed'] = True
            status['all_gates_passed'] = status['returncode'] == 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        status['error_type'] = type(exc).__name__
        print('Verification did not complete. Check local Docker and preserve evidence. No running ADC instance was upgraded.')
    except KeyboardInterrupt:
        status['error_type'] = 'Interrupted'
        print('Interrupted; cleaning only the uniquely named verification project.')
    finally:
        if started and cmd:
            try:
                cleanup = subprocess.run(cmd + ['down', '--remove-orphans'], timeout=120)
                status['cleanup_returncode'] = cleanup.returncode
            except (OSError, subprocess.SubprocessError):
                status['cleanup_returncode'] = -1
                print('Cleanup needs attention for isolated project: ' + project)
        if env_file:
            env_file.unlink(missing_ok=True)
        (output / ('host-' + stamp + '.json')).write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0 if status['all_gates_passed'] and status['cleanup_returncode'] == 0 else 1

if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '--validate-config' and sys.argv[3] == '--source-root':
        # Used by the CMD wrapper inside the isolated image: no host Python needed.
        cfg = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8-sig'))
        validate_configuration(cfg, root=sys.argv[4])
        subprocess.run([sys.executable, str(ROOT/'scripts/verify_update.py')], check=True)
        print('Isolated Compose configuration and source manifest checked.')
    else:
        raise SystemExit(main())
