"""Portable migration contracts. Standard library only; no DB/settings imports.

Checksums detect accidental difference, not authenticity. Bundle files are PRIVATE:
logical dumps contain password hashes, session records and synthetic patient data.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

FORMAT = 'adc-logical-transfer-v1'
VERSION = '0.9.0-alpha.4'
PG_MAJOR = 17
REQUIRED_TABLES = {'adc_user', 'adc_patient', 'adc_visit', 'adc_invoice', 'django_migrations'}
PAYLOADS = {'database.dump', 'db_snapshot.json', 'source.zip', 'source_manifest.json'}
DENY_PARTS = {'.git', '.venv', 'venv', '__pycache__', '.runtime', 'node_modules',
              'backups', 'media', 'staticfiles', 'private_migration', '.migration', 'evidence'}
DENY_SUFFIX = {'.dump', '.key', '.pem', '.p12', '.pfx', '.log', '.pyc'}
RESERVED = {'con', 'prn', 'aux', 'nul'} | {f'{p}{i}' for p in ('com', 'lpt') for i in range(1, 10)}

class MigrationError(RuntimeError):
    """Safe, deliberately non-sensitive error text suitable for terminal output."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def safe_relative(name: str) -> PurePosixPath:
    if not isinstance(name, str) or not name or '\\' in name:
        raise MigrationError('Unsafe relative source path.')
    rel = PurePosixPath(name)
    if rel.is_absolute() or any(p in ('', '.', '..') for p in name.split('/')):
        raise MigrationError('Unsafe relative source path.')
    for part in rel.parts:
        if any(ord(ch) < 32 or ch in '<>:"|?*' for ch in part) or part.endswith((' ', '.')):
            raise MigrationError('Non-portable source filename.')
        if part.split('.')[0].casefold() in RESERVED:
            raise MigrationError('Reserved source filename.')
    return rel


def private_name(name: str) -> bool:
    rel = PurePosixPath(name)
    return (any(p.casefold() in DENY_PARTS or p.casefold().startswith('.env') or
                p.casefold().startswith('.local_credentials') or p in ('.DS_Store', '__MACOSX') or
                p.startswith('._') for p in rel.parts) or
            rel.suffix.casefold() in DENY_SUFFIX or
            (rel.suffix.casefold() == '.sql' and not name.startswith('docs/sql/')))


def canonical_name(name: str) -> str:
    return unicodedata.normalize('NFC', name).casefold()


def validate_names(names: list[str]) -> None:
    seen: set[str] = set()
    for name in names:
        safe_relative(name)
        key = canonical_name(name)
        if key in seen:
            raise MigrationError('Case/Unicode-colliding source paths; fix before export.')
        seen.add(key)


def sql_identifier(value: str) -> str:
    if not isinstance(value, str) or not value or '\x00' in value:
        raise MigrationError('Invalid database identifier.')
    return '"' + value.replace('"', '""') + '"'


def source_inventory(root: Path) -> dict[str, Any]:
    """Only declared release files, preserving local edits without copying secrets.
    Unlisted files and Git history are NOT exported. User must preserve a separate
    private full working copy. Schema SQL snapshots are excluded by policy.
    """
    root = root.resolve()
    try:
        release = json.loads((root / 'UPDATE_MANIFEST.json').read_text(encoding='utf-8-sig'))
        if isinstance(release.get('files'), dict):
            declared = release['files']
        elif str(release.get('target', '')).startswith(('0.7', 'v0.7')):
            # Original v0.7 describes the update in JSON, with file hashes stored
            # separately. Do not force-upgrade Windows merely to read its manifest.
            declared = {}
            for line in (root / 'CHECKSUMS.sha256').read_text(encoding='utf-8-sig').splitlines():
                if not line.strip():
                    continue
                match = re.fullmatch(r'([0-9a-fA-F]{64})  (.+)', line)
                if not match or match[2] in declared:
                    raise MigrationError('Invalid legacy v0.7 checksum manifest.')
                declared[match[2]] = match[1].lower()
        else:
            raise MigrationError('Unsupported source release manifest format.')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MigrationError('Source root needs its release UPDATE_MANIFEST.json.') from exc
    if not isinstance(declared, dict):
        raise MigrationError('Invalid release file manifest.')
    candidates = [n for n in declared if not private_name(n)]
    validate_names(candidates)
    files: dict[str, str] = {}
    modified, missing = [], []
    for name in sorted(candidates):
        rel = safe_relative(name)
        path = root.joinpath(*rel.parts)
        if any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
            raise MigrationError('Symlinked source paths require manual review.')
        if not path.is_file():
            missing.append(name)
            continue
        actual = sha256_file(path)
        files[name] = actual
        if actual != declared[name]:
            modified.append(name)
    if missing:
        raise MigrationError('Declared source files are missing; preserve and reconcile the working copy.')
    # Package declaration itself, which is intentionally not self-hashed upstream.
    files['UPDATE_MANIFEST.json'] = sha256_file(root / 'UPDATE_MANIFEST.json')
    if (root / 'CHECKSUMS.sha256').is_file():
        files['CHECKSUMS.sha256'] = sha256_file(root / 'CHECKSUMS.sha256')
    unlisted = []
    for path in root.rglob('*'):
        name = path.relative_to(root).as_posix()
        if path.is_file() and not private_name(name) and name not in files and name != 'CHECKSUMS.sha256':
            unlisted.append(name)
    return {'declared_version': release.get('target', 'unknown'), 'files': files,
            'locally_modified_files': modified, 'unlisted_file_count': len(unlisted),
            'unlisted_files': sorted(unlisted), 'runtime_image_matches_source': 'not_verified',
            'scope': 'release-declared files, not a full private working-copy backup'}


def pack_source(root: Path, target: Path, inventory: dict[str, Any]) -> None:
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, expected in inventory['files'].items():
            path = root.joinpath(*safe_relative(name).parts)
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                raise MigrationError('Source changed during export; repeat after saving and freezing files.')
            archive.writestr(name, data)


def validate_snapshot(snapshot: Any) -> None:
    if not isinstance(snapshot, dict) or snapshot.get('server_major') != PG_MAJOR:
        raise MigrationError('Only the existing PostgreSQL 17 baseline is supported.')
    if snapshot.get('encoding') != 'UTF8':
        raise MigrationError('This migration contract requires the UTF8 database baseline.')
    tables = snapshot.get('tables')
    if not isinstance(tables, dict) or not REQUIRED_TABLES <= set(tables):
        raise MigrationError('Snapshot is not the expected ADC database.')
    for name, value in tables.items():
        sql_identifier(name)
        if not isinstance(value, dict) or type(value.get('rows')) is not int or value['rows'] < 0:
            raise MigrationError('Malformed table row count.')
        if not re.fullmatch(r'[0-9a-f]{32}', str(value.get('row_md5', ''))):
            raise MigrationError('Malformed table comparison digest.')
    if not isinstance(snapshot.get('schema'), dict):
        raise MigrationError('Missing schema comparison metadata.')


def compare_snapshots(before: dict, after: dict) -> dict:
    validate_snapshot(before); validate_snapshot(after)
    differences = sorted(n for n in set(before['tables']) | set(after['tables'])
                         if before['tables'].get(n) != after['tables'].get(n))
    schema_equal = before['schema'] == after['schema']
    return {'table_rows_and_digests_equal': not differences,
            'schema_metadata_equal': schema_equal, 'differing_tables': differences,
            'all_compared_equal': not differences and schema_equal,
            'scope': 'public table rows, indexes/constraints/triggers/functions and extensions; not application acceptance'}


def verify_bundle(folder: Path) -> dict:
    folder = folder.resolve()
    manifest_path = folder / 'manifest.json'
    if (folder / 'INCOMPLETE').exists():
        raise MigrationError('Incomplete export; do not restore.')
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise MigrationError('Missing or unsafe transfer manifest.')
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise MigrationError('Unreadable transfer manifest.') from exc
    if manifest.get('format') != FORMAT or manifest.get('postgres_major') != PG_MAJOR:
        raise MigrationError('Unsupported transfer format/PostgreSQL major.')
    entries = manifest.get('files', {})
    if not isinstance(entries, dict) or set(entries) != PAYLOADS:
        raise MigrationError('Unexpected transfer payload list.')
    for name, record in entries.items():
        path = folder / name
        if path.is_symlink() or not path.is_file() or not isinstance(record, dict):
            raise MigrationError('Missing or unsafe transfer payload.')
        if type(record.get('bytes')) is not int or path.stat().st_size != record['bytes']:
            raise MigrationError('Transfer file length differs; do not restore.')
        if sha256_file(path) != record.get('sha256'):
            raise MigrationError('Transfer checksum differs; do not restore.')
    with (folder / 'database.dump').open('rb') as stream:
        if stream.read(5) != b'PGDMP':
            raise MigrationError('Expected a PostgreSQL custom-format archive.')
    try:
        snapshot = json.loads((folder / 'db_snapshot.json').read_text(encoding='utf-8'))
        source = json.loads((folder / 'source_manifest.json').read_text(encoding='utf-8'))
        validate_snapshot(snapshot)
        with zipfile.ZipFile(folder / 'source.zip') as z:
            validate_names(z.namelist())
            if len(z.namelist()) != len(set(z.namelist())) or set(z.namelist()) != set(source['files']):
                raise MigrationError('Source archive entries differ from inventory.')
            for entry in z.infolist():
                if private_name(entry.filename) or entry.file_size > 128 * 1024 * 1024:
                    raise MigrationError('Unsafe or oversized source archive entry.')
                if hashlib.sha256(z.read(entry)).hexdigest() != source['files'][entry.filename]:
                    raise MigrationError('Source entry checksum mismatch.')
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        raise MigrationError('Invalid private bundle content.') from exc
    return manifest
