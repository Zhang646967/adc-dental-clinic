"""Release maintenance. Persistent data is never restored or reseeded."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tarfile
import time

from scripts.g4_course import digest, exclusive, private_directory, private_file, run
from scripts.g4_mac_demo import atomic_text
from scripts.g4_prepare import pinned_image, read_env

SHA = re.compile('[0-9a-f]{40}')
MIGRATIONS = (
    "import hashlib,json;from pathlib import Path;root=Path('/app');"
    "print(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() "
    "for p in sorted(root.glob('*/migrations/[0-9]*.py'))}))"
)


def versions(plan):
    result = {plan['requested_source_commit']: plan['images']['app']}
    for row in plan.get('release_history', []):
        source, image = row['source_commit'], row['app_image']
        if not SHA.fullmatch(source) or not pinned_image(image) or source in result and result[source] != image:
            raise ValueError('Release history has a conflicting source/image identity.')
        result[source] = image
    return result


def update_plan(bundle, source, image, *, controller=None, history=None):
    """Change release identity only; retain secrets, project, ports and volumes."""
    bundle = Path(bundle)
    plan = json.loads(private_file(bundle / 'plan.json').read_text())
    known = versions(plan) if history is None else dict(history)
    if source in known and known[source] != image:
        raise ValueError('The same accepted source cannot silently become a different image.')
    initial = plan.get('initial_source_commit', plan['requested_source_commit'])
    known[source] = image
    for name in ('compose.env', 'private/runtime.env', 'private/maintenance.env'):
        path = bundle / name
        values = read_env(private_file(path))
        if name == 'compose.env':
            values.update(G4_APP_IMAGE=image, G4_SOURCE_COMMIT=source)
        else:
            values['ADC_SOURCE_COMMIT'] = source
        atomic_text(path, ''.join(k + '=' + v + '\n' for k, v in values.items()))
    plan.update(requested_source_commit=source, initial_source_commit=initial,
                release_history=[{'source_commit': s, 'app_image': i} for s, i in sorted(known.items())])
    plan['images']['app'] = image
    if controller:
        plan['controller_source_commit'] = controller
    atomic_text(bundle / 'plan.json', json.dumps(plan, indent=2) + '\n')
    marker = bundle / 'private/deployed.json'
    if marker.exists():
        previous = json.loads(private_file(marker).read_text())
        previous['source_commit'] = source
        atomic_text(marker, json.dumps(previous) + '\n')
    return plan


def image_migrations(course, image):
    return json.loads(run(course.docker + ['run', '--rm', '--entrypoint', 'python', image,
                                           '-c', MIGRATIONS], course.log))


def inspect_artifacts(course, artifacts):
    folder = private_directory(artifacts)
    meta = json.loads(private_file(folder / 'build.json').read_text())
    if not SHA.fullmatch(meta['source_commit']) or meta['architecture'] != course.architecture:
        raise ValueError('Release source or architecture differs from the selected target.')
    if not pinned_image(meta['app_image']):
        raise ValueError('Use a pinned release image.')
    for name, key in [('source.tar', 'source_sha256'), ('application.tar', 'image_archive_sha256')]:
        if digest(private_file(folder / name)) != meta[key]:
            raise ValueError('Release transfer checksum differs.')
    run(course.docker + ['load', '-i', str(folder / 'application.tar')], course.log, timeout=600)
    image = json.loads(run(course.docker + ['image', 'inspect', meta['app_image']], course.log))[0]
    if (image['Architecture'] != course.architecture or
            image['Config'].get('Labels', {}).get('org.opencontainers.image.revision') != meta['source_commit']):
        raise ValueError('Loaded image does not identify the selected release.')
    destination = course.bundle.parent / 'release_sources' / meta['source_commit']
    if not destination.exists():
        private_directory(destination)
        with tarfile.open(folder / 'source.tar') as archive:
            archive.extractall(destination, filter='data')
    run(['python3', str(destination / 'scripts/verify_update.py')], course.log)
    return meta


def wait_candidate(course, timeout=150):
    """Keep the gateway stopped until fresh web/worker/observer checks pass."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            course.dc('exec', '-T', 'web', 'python', 'scripts/g4_health.py', timeout=15)
            observation = course.operations()
            if observation.get('state') == 'HEALTHY':
                return
        except (OSError, RuntimeError):
            pass
        time.sleep(2)
    raise RuntimeError('Candidate health/worker observations did not recover; gateway remains closed.')


def start_candidate(course):
    course.render()
    course.images()
    # Old observations belong to the previous source. Archive them explicitly,
    # retain the pre-upgrade encrypted copy, and require two fresh good samples.
    course.dc('run', '--rm', '--no-deps', 'operations', 'python', 'manage.py',
              'operations_reset', '--confirm-reset-observations', timeout=30)
    course.dc('--profile', 'maintenance', 'run', '--rm', '--no-deps', 'schema',
              'python', 'manage.py', 'collectstatic', '--noinput', timeout=180)
    course.dc('up', '-d', '--wait', '--wait-timeout', '120', 'web', 'notification-worker', 'operations', timeout=150)
    course.dc('exec', '-T', 'web', 'python', 'manage.py', 'check_runtime_role')
    wait_candidate(course)
    course.dc('up', '-d', '--wait', '--wait-timeout', '30', 'gateway', timeout=45)
    result = course.status()
    if result['status'] != 'ORIGIN_READY':
        raise RuntimeError('Release HTTPS check did not pass.')
    return result


MIGRATE_FORWARD = """
import sys
import django
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

django.setup()
executor = MigrationExecutor(connection)
executor.loader.check_consistent_history(connection)
plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
approved = set(sys.argv[2:])
if any(backwards or not migration.atomic or
       migration.app_label + '.' + migration.name not in approved
       for migration, backwards in plan):
    raise SystemExit('Only reviewed, atomic forward migrations are permitted.')
if sys.argv[1] == 'apply':
    call_command('migrate', interactive=False)
"""


def migration_names(files):
    return {Path(name).parts[0] + '.' + Path(name).stem for name in files}


def applied_migrations(course):
    return set(course.dc('exec', '-T', 'db', 'psql', '--no-psqlrc', '-U', 'adc_g4_admin',
        '-d', 'adc_rc_demo', '-At', '-c',
        "SELECT app || '.' || name FROM django_migrations "
        "WHERE app NOT IN ('auth','contenttypes','sessions','admin')").decode().splitlines())


def check_upgrade_space(course):
    size = int(course.dc('exec', '-T', 'db', 'psql', '--no-psqlrc', '-U', 'adc_g4_admin',
                        '-d', 'adc_rc_demo', '-At', '-c', 'SELECT pg_database_size(current_database())'))
    pg_kib = int(course.dc('exec', '-T', 'db', 'df', '-Pk', '/var/lib/postgresql/data')
                 .decode().splitlines()[-1].split()[3])
    minimum = 2 * size + 128 * 1024 * 1024
    if min(shutil.disk_usage(course.bundle).free, pg_kib * 1024) < minimum:
        raise ValueError('Insufficient free space for migration and the encrypted checkpoint.')


def pending_additive(bundle):
    path = bundle / 'private/release-operation.json'
    if path.exists():
        state = json.loads(private_file(path).read_text())
        if state.get('mode') == 'ADDITIVE' and state['status'] not in ('UPGRADED', 'FAILED_IMAGE_REVERTED'):
            return state
    return None


def schema_step(course, image, source, approved, *, apply=False):
    name = course.plan['project'] + '_release_schema'
    running = run(course.docker + ['ps', '-a', '--filter', 'name=^/' + name + '$',
                                   '--format', '{{.Names}}'], course.log)
    if running.strip():
        raise ValueError('Previous migration container still exists; inspect it before resuming.')
    # Use the existing maintenance role without switching the live configuration
    # or booting dependencies against a partially upgraded schema.
    with tempfile.TemporaryDirectory(dir=course.bundle / 'private') as folder:
        override = Path(folder) / 'schema.json'
        atomic_text(override, json.dumps({'services': {'schema': {'image': image}}}))
        run(course.command + ['-f', str(override), '--profile', 'maintenance', 'run',
            '--rm', '-T', '--no-deps', '--name', name, '-e', 'ADC_SOURCE_COMMIT=' + source,
            'schema', 'python', '-c', MIGRATE_FORWARD, 'apply' if apply else 'check',
            *sorted(approved)], course.log, timeout=600 if apply else 90)


def retain_checkpoint(course, backup):
    checkpoint = private_directory(course.bundle / 'private/release-checkpoints')
    for suffix in ('', '.json'):
        original = private_file(course.bundle / 'backups' / (backup + suffix))
        retained = checkpoint / original.name
        if not retained.exists():
            shutil.copyfile(original, retained)
            retained.chmod(0o600)
        if digest(private_file(retained)) != digest(original):
            raise ValueError('Existing release checkpoint differs.')
    return digest(checkpoint / backup)


def additive_release(course, *, source, image, old_source, old_image, current, target,
                     expected_current, recipient_file, age, state):
    path = course.bundle / 'private/release-operation.json'
    def record(status):
        state['status'] = status
        atomic_text(path, json.dumps(state, indent=2) + '\n')

    before, after = migration_names(current), migration_names(target)
    if not before or not current.items() < target.items():
        raise ValueError('Additive upgrade must retain every old migration byte and append new files.')
    new = after - before
    identity = course.database_identity()
    applied = applied_migrations(course)
    if state:
        if (state['from_source'], state['to_source'], state['to_image'], state['database_identity']) != (
                expected_current, source, image, identity):
            raise ValueError('Resume requires the same original commit, target artifact and database.')
        if not before <= applied <= after or (not state.get('backup_sha256') and applied != before):
            raise ValueError('The actual migration history differs from the interrupted release.')
        if state.get('backup_sha256'):
            archive = course.bundle / 'private/release-checkpoints' / state['backup']
            if digest(private_file(archive)) != state['backup_sha256']:
                raise ValueError('The original encrypted checkpoint is missing or changed.')
    else:
        if applied != before or course.status()['status'] != 'ORIGIN_READY':
            raise ValueError('The running version and exact applied migrations must match before maintenance.')
        state = dict(mode='ADDITIVE', from_source=old_source, from_image=old_image,
                     to_source=source, to_image=image, database_identity=identity,
                     database_restored=False, added_migrations=sorted(new),
                     started_at=datetime.now(timezone.utc).isoformat())
    check_upgrade_space(course)
    # The plan is checked before touching a healthy running service; it is
    # rechecked immediately before execution and when resuming a partial run.
    schema_step(course, image, source, new)
    record('MAINTENANCE')
    course.dc('stop', '--timeout', '30', 'gateway', timeout=45)
    course.dc('stop', '--timeout', '30', 'web', 'notification-worker', 'operations', timeout=90)
    try:
        if not state.get('backup_sha256'):
            backup = course.backup(recipient_file, age)
            state['backup'] = backup['name']
            state['backup_sha256'] = retain_checkpoint(course, state['backup'])
        # Write this boundary before Django can commit any migration. Even if
        # the client loses the reply, no earlier image is restarted thereafter.
        state['migration_started'] = True
        record('MIGRATING')
        if applied_migrations(course) != after:
            schema_step(course, image, source, new, apply=True)
        if applied_migrations(course) != after:
            raise RuntimeError('Candidate migration history is incomplete.')
        record('SCHEMA_APPLIED')
        course.plan = update_plan(course.bundle, source, image, controller=source)
        result = start_candidate(course)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        course.dc('stop', '--timeout', '30', 'gateway', 'web', 'notification-worker', 'operations', timeout=90)
        if state.get('migration_started'):
            record('FAILED_MAINTENANCE_REQUIRED')
        else:
            try:
                # The original schema and configuration were never switched.
                # A failed backup remains visible in operations and must not
                # prevent the unchanged original web service from returning.
                course.start_runtime()
                if course.status()['status'] != 'ORIGIN_READY':
                    raise RuntimeError('Original HTTPS service did not return.')
                record('FAILED_IMAGE_REVERTED')
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                course.dc('stop', '--timeout', '30', 'gateway', timeout=45)
                record('FAILED_MAINTENANCE_REQUIRED')
        raise
    state['completed_at'] = datetime.now(timezone.utc).isoformat()
    record('UPGRADED')
    return {**state, 'release': result, 'public_acceptance_executed': False}


def change_release(course, *, recipient_file, expected_current, artifacts=None, to_source=None, age='age', allow_additive=False):
    if bool(artifacts) == bool(to_source):
        raise ValueError('Choose an upgrade artifact or one previously accepted rollback source.')
    with exclusive(course.bundle / 'private/release.lock'):
        # A stale in-memory plan must not select the wrong running version.
        course.plan = json.loads(private_file(course.bundle / 'plan.json').read_text())
        old_source, old_image = course.plan['requested_source_commit'], course.plan['images']['app']
        old_versions = versions(course.plan)
        pending = pending_additive(course.bundle)
        if pending and not (artifacts and allow_additive):
            raise ValueError('An additive migration needs the original upgrade command to resume.')
        if artifacts:
            meta = inspect_artifacts(course, artifacts)
            source, image = meta['source_commit'], meta['app_image']
        else:
            source = to_source
            image = versions(course.plan).get(source)
            if image is None:
                raise ValueError('Rollback source is not in this deployment history.')
        if not pending and (source, image) == (old_source, old_image):
            return {'status': 'ALREADY_ACTIVE', 'release': course.status()}
        if source in old_versions and old_versions[source] != image:
            raise ValueError('An accepted source is already pinned to a different image.')
        if not pending and old_source != expected_current:
            raise ValueError('Running release changed; inspect status before another upgrade.')
        if pending and (source, image, expected_current) != (
                pending['to_source'], pending['to_image'], pending['from_source']):
            raise ValueError('Resume requires the same original commit and exact target artifact.')
        current = image_migrations(course, pending['from_image'] if pending else old_image)
        target = image_migrations(course, image)
        if pending or current != target:
            if not (artifacts and allow_additive):
                raise ValueError('Changed migrations require an explicitly approved additive upgrade; downgrade is disabled.')
            return additive_release(course, source=source, image=image, old_source=old_source,
                old_image=old_image, current=current, target=target, expected_current=expected_current,
                recipient_file=recipient_file, age=age, state=pending)
        state_path = course.bundle / 'private/release-operation.json'
        state = {'from_source': old_source, 'to_source': source, 'database_restored': False,
                 'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'MAINTENANCE'}
        atomic_text(state_path, json.dumps(state, indent=2) + '\n')
        course.dc('stop', '--timeout', '30', 'gateway', timeout=45)
        course.dc('stop', '--timeout', '30', 'web', 'notification-worker', 'operations', timeout=60)
        try:
            backup = course.backup(recipient_file, age)
            state['backup'] = backup['name']
            checkpoint = private_directory(course.bundle / 'private/release-checkpoints')
            for suffix in ('', '.json'):
                original = private_file(course.bundle / 'backups' / (backup['name'] + suffix))
                retained = checkpoint / original.name
                if not retained.exists():
                    shutil.copyfile(original, retained)
                    retained.chmod(0o600)
                elif digest(retained) != digest(original):
                    raise ValueError('Existing release checkpoint differs.')
            state['encrypted_release_checkpoint_retained'] = True
            controller = source if artifacts else course.plan.get('controller_source_commit')
            course.plan = update_plan(course.bundle, source, image, controller=controller)
            result = start_candidate(course)
        except Exception:
            # Revert only image/config identity. Never restore or remove data,
            # even if a request reached the new gateway before a failed check.
            course.dc('stop', '--timeout', '30', 'gateway', 'web', 'notification-worker', 'operations', timeout=90)
            course.plan = update_plan(course.bundle, old_source, old_image, history=old_versions)
            try:
                start_candidate(course)
                state['status'] = 'FAILED_IMAGE_REVERTED'
            except Exception:
                state['status'] = 'FAILED_MAINTENANCE_REQUIRED'
                course.dc('stop', 'gateway', timeout=45)
            atomic_text(state_path, json.dumps(state, indent=2) + '\n')
            raise
        state.update(status='UPGRADED' if artifacts else 'ROLLED_BACK',
                     completed_at=datetime.now(timezone.utc).isoformat())
        atomic_text(state_path, json.dumps(state, indent=2) + '\n')
        return {**state, 'release': result, 'public_acceptance_executed': False}
