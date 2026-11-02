"""Public source inventory for a fixed ADC build; never reads private settings."""
import hashlib
import json
from pathlib import Path


def migrations(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.glob('*/migrations/[0-9]*.py'))}


def source_inventory(root):
    root = Path(root)
    migration_files = migrations(root)
    client = root / 'clients/wechat'
    files = sorted(p for p in client.rglob('*') if p.is_file()
                   and p.name != 'project.private.config.json')
    records = ''.join(p.relative_to(client).as_posix() + '\0' +
                      hashlib.sha256(p.read_bytes()).hexdigest() + '\n' for p in files)
    app = client / 'miniprogram/app.json'
    pages = len(json.loads(app.read_text())['pages']) if app.is_file() else 0
    requirements = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(root.glob('requirements*.txt'))}
    return {'format': 1, 'product': 'ADC', 'release_edition': 'UNIFIED',
            'application_migrations': len(migration_files),
            'migration_sha256': hashlib.sha256(json.dumps(migration_files, sort_keys=True).encode()).hexdigest(),
            'requirements_sha256': requirements,
            'native_client': {'source_files': len(files), 'pages': pages,
                              'source_tree_sha256': hashlib.sha256(records.encode()).hexdigest(),
                              'compiled_or_platform_verified': False},
            'access_paths': {'public': '/', 'patient': '/portal/login/',
                             'staff': '/accounts/login/'},
            'scope': 'Archived source inventory; not installed dependencies or cloud/device acceptance.'}
