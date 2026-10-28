"""Same-schema image upgrades. Persistent data is never restored or reseeded."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
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


def change_release(course, *, recipient_file, expected_current, artifacts=None, to_source=None, age='age'):
    if bool(artifacts) == bool(to_source):
        raise ValueError('Choose an upgrade artifact or one previously accepted rollback source.')
    with exclusive(course.bundle / 'private/release.lock'):
        # A stale in-memory plan must not select the wrong running version.
        course.plan = json.loads(private_file(course.bundle / 'plan.json').read_text())
        old_source, old_image = course.plan['requested_source_commit'], course.plan['images']['app']
        old_versions = versions(course.plan)
        if artifacts:
            meta = inspect_artifacts(course, artifacts)
            source, image = meta['source_commit'], meta['app_image']
        else:
            source = to_source
            image = versions(course.plan).get(source)
            if image is None:
                raise ValueError('Rollback source is not in this deployment history.')
        if (source, image) == (old_source, old_image):
            return {'status': 'ALREADY_ACTIVE', 'release': course.status()}
        if source in old_versions and old_versions[source] != image:
            raise ValueError('An accepted source is already pinned to a different image.')
        if old_source != expected_current:
            raise ValueError('Running release changed; inspect status before another upgrade.')
        if image_migrations(course, old_image) != image_migrations(course, image):
            raise ValueError('This release command supports identical migrations only; no automatic schema downgrade.')
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
