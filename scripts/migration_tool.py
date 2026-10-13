#!/usr/bin/env python3
"""Windows/macOS migration preparation. Requires host Python >=3.11 and local Docker.

No command stops/updates the existing app or restores into an existing database.
`rehearse` only restores a trusted local archive into a NEW disposable PG container.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

if __package__ in ('', None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.migration_core import (FORMAT, VERSION, PG_MAJOR, PAYLOADS, REQUIRED_TABLES,
    MigrationError, compare_snapshots, pack_source, sha256_file, source_inventory,
    sql_identifier, validate_snapshot, verify_bundle)

ROOT = Path(__file__).resolve().parents[1]
QUERY_TIMEOUT = 300
PSQL_SCRIPT = 'export PGCLIENTENCODING=UTF8; exec psql -X -q -A -t -v ON_ERROR_STOP=1 -h /var/run/postgresql -p 5432 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
SETUP = "SET timezone='UTC'; SET datestyle='ISO, YMD'; SET extra_float_digits=3; SET bytea_output='hex'; SET search_path=public,pg_catalog; SET statement_timeout='240s';"
TABLE_SQL = """SELECT coalesce(json_agg(c.relname ORDER BY c.relname COLLATE "C"),'[]'::json)
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind='r';"""
SCHEMA_SQL = """SELECT json_build_object(
'constraints',(SELECT coalesce(json_agg(x ORDER BY x::text COLLATE "C"),'[]'::json) FROM
 (SELECT json_build_array(c.relname,k.conname,k.contype,pg_get_constraintdef(k.oid),k.convalidated) x
 FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public') a),
'indexes',(SELECT coalesce(json_agg(x ORDER BY x::text COLLATE "C"),'[]'::json) FROM
 (SELECT json_build_array(tablename,indexname,indexdef) x FROM pg_indexes WHERE schemaname='public') a),
'columns',(SELECT coalesce(json_agg(x ORDER BY x::text COLLATE "C"),'[]'::json) FROM
 (SELECT json_build_array(table_name,column_name,data_type,is_nullable,column_default,ordinal_position)
 x FROM information_schema.columns WHERE table_schema='public') a),
'functions',(SELECT coalesce(json_agg(x ORDER BY x::text COLLATE "C"),'[]'::json) FROM
 (SELECT json_build_array(p.proname,pg_get_functiondef(p.oid)) x FROM pg_proc p
 JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prokind IN ('f','p')
 AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e')) a),
'extensions',(SELECT coalesce(json_agg(x ORDER BY x::text COLLATE "C"),'[]'::json) FROM
 (SELECT json_build_array(extname,extversion) x FROM pg_extension) a),
'user_triggers',(SELECT coalesce(json_agg(x ORDER BY x::text COLLATE "C"),'[]'::json) FROM
 (SELECT json_build_array(c.relname,t.tgname,pg_get_triggerdef(t.oid)) x FROM pg_trigger t
 JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public' AND NOT t.tgisinternal) a));"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: dict) -> None:
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def local_env() -> dict:
    env = dict(os.environ)
    if env.get('DOCKER_HOST') and not env['DOCKER_HOST'].startswith(('unix://', 'npipe://')):
        raise MigrationError('Remote DOCKER_HOST is not accepted. Select a local Docker Desktop engine.')
    # The selected local context is pinned explicitly on every Docker command.
    for key in list(env):
        if key.startswith('COMPOSE_') or key == 'DOCKER_DEFAULT_PLATFORM':
            env.pop(key, None)
    return env


class Docker:
    def __init__(self):
        self.env = local_env()
        exe = shutil.which('docker')
        if not exe:
            raise MigrationError('Docker CLI not found; start/install local Docker Desktop first.')
        self.prefix = [exe]
        context = self.run(['context', 'show'], timeout=30).strip()
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', context):
            raise MigrationError('Unexpected Docker context name.')
        host = json.loads(self.run(['context', 'inspect', context, '--format', '{{json .Endpoints.docker.Host}}'], timeout=30))
        if not isinstance(host, str) or not host.startswith(('unix://', 'npipe://')):
            raise MigrationError('Remote Docker context rejected; no command was sent to that engine.')
        self.prefix = [exe, '--context', context]
        data = json.loads(self.run(['info', '--format', '{{json .}}'], timeout=30))
        if data.get('OSType') != 'linux':
            raise MigrationError('This project requires the local Linux container engine.')
        self.info = {k: data.get(k) for k in ('OSType', 'Architecture', 'ServerVersion')}
        self.context = context

    def run(self, args: list[str], *, timeout: int = 120, input_bytes: bytes | None = None,
            stdout_file=None) -> str:
        """No shell=True, binary files bypass PowerShell text redirection.
        Raw Docker/SQL stderr is intentionally not persisted: it can contain data.
        """
        try:
            result = subprocess.run(self.prefix + args, input=input_bytes, stdout=stdout_file or subprocess.PIPE,
                                    stderr=subprocess.PIPE, env=self.env, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MigrationError('Docker command could not complete; check the engine/resources and preserve the source.') from exc
        if result.returncode:
            raise MigrationError('Docker command failed at ' + str(args[0]) + '; no success is recorded. Inspect locally without sharing secrets.')
        return result.stdout.decode('utf-8', errors='strict') if stdout_file is None else ''

    def inspect(self, container: str) -> dict:
        return json.loads(self.run(['inspect', '--type', 'container', container]))[0]


class Session:
    """Holds one PostgreSQL transaction and exported snapshot through psql stdin.
    A queue makes read deadlines portable (Windows pipes cannot use select()).
    """
    def __init__(self, docker: Docker, cid: str):
        self.process = subprocess.Popen(docker.prefix + ['exec', '-i', cid, 'sh', '-ceu', PSQL_SCRIPT],
              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
              text=True, encoding='utf-8', errors='strict', bufsize=1, env=docker.env)
        self.messages: queue.Queue = queue.Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self.query(SETUP)
            self.query('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;')
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                self.messages.put(line.rstrip('\r\n'))
        except (OSError, ValueError):
            pass
        finally:
            self.messages.put(None)

    def query(self, sql: str) -> list[str]:
        sentinel = 'adc_end_' + uuid4().hex
        try:
            self.process.stdin.write(sql + '\n\\echo ' + sentinel + '\n')
            self.process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise MigrationError('Database read session failed.') from exc
        lines = []
        deadline = time.monotonic() + QUERY_TIMEOUT
        while True:
            try:
                line = self.messages.get(timeout=max(0.01, deadline-time.monotonic()))
            except queue.Empty as exc:
                raise MigrationError('Database query timed out; no migration success is recorded.') from exc
            if line is None:
                raise MigrationError('Database rejected the query or connection closed; review permissions/schema locally.')
            if line == sentinel:
                return lines
            if line:
                lines.append(line)

    def scalar(self, sql: str) -> str:
        lines = self.query(sql)
        if len(lines) != 1:
            raise MigrationError('Unexpected database query response.')
        return lines[0]

    def snapshot(self) -> dict:
        major = int(self.scalar('SHOW server_version_num;')) // 10000
        if major != PG_MAJOR:
            raise MigrationError('Expected PostgreSQL 17. Do not combine a major-version upgrade with this migration.')
        # Reject unsupported structures rather than silently omitting their data.
        unsupported = int(self.scalar("""SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
            AND (c.relkind IN ('p','f','m') OR (n.nspname<>'public' AND c.relkind='r'));"""))
        if unsupported:
            raise MigrationError('Partitioned/foreign/materialized or non-public tables need a separate reviewed migration.')
        if int(self.scalar('SELECT count(*) FROM pg_largeobject_metadata;')):
            raise MigrationError('Large objects need a reviewed migration, including external media.')
        tables = json.loads(self.scalar(TABLE_SQL))
        if not REQUIRED_TABLES <= set(tables):
            raise MigrationError('Selected database is not the expected ADC instance.')
        result = {}
        for table in tables:
            qualified = 'public.' + sql_identifier(table)
            result[table] = json.loads(self.scalar(f"""SELECT json_build_object('rows',count(*),
                'row_md5',md5(coalesce(string_agg(h,'' ORDER BY h COLLATE "C"),'')))
                FROM (SELECT md5(to_jsonb(t)::text) h FROM {qualified} t) s;"""))
        output = {'server_major': major, 'encoding': self.scalar('SHOW server_encoding;'),
                  'tables': result, 'schema': json.loads(self.scalar(SCHEMA_SQL)),
                  'scope': 'same repeatable-read snapshot as dump; sequence counters are not MVCC snapshot data'}
        validate_snapshot(output)
        return output

    def close(self):
        try:
            if self.process.poll() is None:
                self.process.stdin.write('ROLLBACK;\n\\q\n'); self.process.stdin.flush()
                self.process.wait(timeout=10)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            self.process.kill(); self.process.wait(timeout=10)
        finally:
            for stream in (self.process.stdin, self.process.stdout):
                try: stream.close()
                except (OSError, ValueError): pass


def source_db(docker: Docker, ident: str, cutover: bool = False) -> tuple[str, dict]:
    # Require an explicit container ID, never guess from a directory/project name.
    if not re.fullmatch(r'[a-f0-9]{12,64}', ident):
        raise MigrationError('Pass an explicit local database container ID (12-64 hex characters).')
    info = docker.inspect(ident)
    labels = info.get('Config', {}).get('Labels') or {}
    if not info.get('State', {}).get('Running') or labels.get('com.docker.compose.service') != 'db':
        raise MigrationError('Source must be the running db service of the intended local ADC Compose project.')
    env = dict(x.split('=', 1) for x in info.get('Config', {}).get('Env', []) if '=' in x)
    for key in ('POSTGRES_DB', 'POSTGRES_USER'):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,62}', env.get(key, '')):
            raise MigrationError('Source requires simple POSTGRES_DB/POSTGRES_USER identifiers, not connection URLs.')
    project = labels.get('com.docker.compose.project')
    if not project:
        raise MigrationError('Missing source Compose project label.')
    if cutover:
        running = docker.run(['ps', '--filter', 'label=com.docker.compose.project='+project, '--format', '{{.ID}}']).splitlines()
        for candidate in running:
            if docker.inspect(candidate)['Id'] != info['Id']:
                raise MigrationError('For cutover, stop all other services of the source project first. Tool never stops them for you.')
    safe = {'compose_project': project, 'container_id': info['Id'], 'database_image_id': info['Image'],
            'source_architecture': docker.info.get('Architecture')}
    return info['Id'], safe


def export_bundle(args, docker: Docker) -> dict:
    if not args.confirm_private_data:
        raise MigrationError('Export contains password hashes/sessions and patient data. --confirm-private-data is required.')
    if args.cutover and not args.confirm_writers_stopped:
        raise MigrationError('Cutover export requires --confirm-writers-stopped after manually quiescing every writer.')
    source = Path(args.source).resolve()
    folder = Path(args.out).resolve()
    if folder == source or source in folder.parents:
        raise MigrationError('Put the private transfer folder outside the source/repository directory.')
    inventory = source_inventory(source)
    cid, info = source_db(docker, args.db, args.cutover)
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    marker = folder/'INCOMPLETE'; marker.write_text('Export has not completed. Do not restore.\n', encoding='ascii')
    session = None
    try:
        session = Session(docker, cid)
        snap_id = session.scalar('SELECT pg_export_snapshot();')
        if not re.fullmatch(r'[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+', snap_id):
            raise MigrationError('Invalid exported snapshot identifier.')
        # pg_dump and table fingerprints use the SAME still-open transaction snapshot.
        snapshot = session.snapshot()
        with (folder/'database.dump').open('xb') as dump:
            command = 'exec pg_dump -h /var/run/postgresql -p 5432 -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-privileges --snapshot="$1"'
            docker.run(['exec', cid, 'sh', '-ceu', command, 'adc-dump', snap_id],
                       stdout_file=dump, timeout=1800)
        session.close(); session = None
        with (folder/'database.dump').open('rb') as f:
            if f.read(5) != b'PGDMP':
                raise MigrationError('Invalid or truncated custom dump header.')
        write_json(folder/'db_snapshot.json', snapshot)
        write_json(folder/'source_manifest.json', inventory)
        pack_source(source, folder/'source.zip', inventory)
        source_db(docker, cid, args.cutover)
        manifest = {'format': FORMAT, 'tool_version': VERSION, 'created_at_utc': now(),
            'postgres_major': PG_MAJOR, 'source': info, 'mode': 'cutover' if args.cutover else 'rehearsal',
            'writer_freeze_confirmed_by_operator': bool(args.cutover and args.confirm_writers_stopped),
            'same_database_snapshot_for_dump_and_rows': True, 'restored_and_verified': False,
            'secret_env_included': False, 'git_history_included': False, 'media_included': False,
            'source_runtime_parity': 'not_verified',
            'warning': 'PRIVATE, unencrypted. Do not upload dump, source zip, manifest or credentials to chat/public Git.',
            'files': {n: {'sha256': sha256_file(folder/n), 'bytes': (folder/n).stat().st_size} for n in sorted(PAYLOADS)}}
        write_json(folder/'manifest.json', manifest)
        marker.unlink()
        for path in folder.iterdir():
            try: path.chmod(0o600)
            except OSError: pass
        try:
            verify_bundle(folder)
        except BaseException:
            marker.write_text('Post-export checks failed. Do not restore.\n', encoding='ascii')
            raise
        return {'operation': 'export', 'export_completed': True, 'restored_and_verified': False,
                'table_count': len(snapshot['tables']), 'unlisted_source_files': inventory['unlisted_file_count'],
                'local_source_edits_preserved': len(inventory['locally_modified_files']),
                'mode': manifest['mode'], 'source_was_stopped_or_modified_by_tool': False,
                'next': 'Keep this PRIVATE; copy securely then inspect and rehearse on the target. Do not retire Windows yet.'}
    finally:
        if session is not None: session.close()


def rehearse(args, docker: Docker) -> dict:
    if not args.confirm_trusted_backup:
        raise MigrationError('Restore executes SQL from the archive. Only your trusted local backup is allowed; use --confirm-trusted-backup.')
    folder = Path(args.bundle).resolve()
    verify_bundle(folder)
    name = 'adc_restore_' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S') + '_' + uuid4().hex[:10]
    nonce = uuid4().hex
    cid = None
    session = None
    status = {'operation': 'restore_rehearsal', 'started_at_utc': now(), 'container_name': name,
              'restore_executed': False, 'comparison_passed': False, 'cleanup_passed': False,
              'application_tests_executed': False, 'existing_database_touched': False,
              'manifest_sha256': sha256_file(folder/'manifest.json'),
              'dump_sha256': sha256_file(folder/'database.dump')}
    try:
        try:
            docker.run(['image', 'inspect', 'postgres:17'], timeout=30)
        except MigrationError:
            docker.run(['pull', 'postgres:17'], timeout=900)
        cid = docker.run(['create', '--name', name, '--network', 'none',
            '--label', 'adc.migration.owner='+nonce, '--tmpfs', '/var/lib/postgresql/data',
            '--env', 'POSTGRES_DB=adc_restore', '--env', 'POSTGRES_USER=adc_restore_owner',
            '--env', 'POSTGRES_PASSWORD=ephemeral-'+nonce, 'postgres:17'], timeout=900).strip()
        if not re.fullmatch(r'[0-9a-f]{64}', cid):
            raise MigrationError('Unexpected new restore container identifier.')
        status['target_image_id'] = docker.inspect(cid).get('Image')
        status['stage'] = 'start_disposable_database'
        docker.run(['start', cid])
        ready = False
        for _ in range(60):
            try:
                # Official image temporarily starts a setup-only server. Require its
                # final postgres PID1 before considering readiness to avoid that race.
                docker.run(['exec', cid, 'sh', '-ceu',
                    'test "$(cat /proc/1/comm)" = postgres; pg_isready -h /var/run/postgresql -p 5432 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'], timeout=10)
                ready = True; break
            except MigrationError: time.sleep(1)
        if not ready: raise MigrationError('Disposable PostgreSQL did not become ready.')
        status['stage'] = 'copy_archive_to_disposable_database'
        docker.run(['cp', str(folder/'database.dump'), cid+':/tmp/adc_restore.dump'], timeout=600)
        status['stage'] = 'restore_single_transaction'
        docker.run(['exec', cid, 'sh', '-ceu',
            'exec pg_restore --no-owner --no-privileges --exit-on-error --single-transaction '
            '-h /var/run/postgresql -p 5432 -U "$POSTGRES_USER" -d "$POSTGRES_DB" /tmp/adc_restore.dump'], timeout=1800)
        status['restore_executed'] = True
        status['stage'] = 'compare_restored_database'
        session = Session(docker, cid)
        restored = session.snapshot()
        expected = json.loads((folder/'db_snapshot.json').read_text(encoding='utf-8'))
        comparison = compare_snapshots(expected, restored)
        status.update(comparison)
        status['comparison_passed'] = comparison['all_compared_equal']
        status['snapshot_table_count'] = len(expected['tables'])
        status['target_architecture'] = docker.info.get('Architecture')
        status['source_architecture'] = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))['source'].get('source_architecture')
    except (MigrationError, OSError, ValueError) as exc:
        status['error'] = str(exc) if isinstance(exc, MigrationError) else type(exc).__name__
    finally:
        if session: session.close()
        if cid:
            try:
                info = docker.inspect(cid)
                if (info.get('Config', {}).get('Labels') or {}).get('adc.migration.owner') != nonce:
                    raise MigrationError('Cleanup ownership check failed; no container was removed.')
                docker.run(['rm', '--force', cid], timeout=90)
                status['cleanup_passed'] = True
            except MigrationError:
                status['cleanup_warning'] = 'Only the disposable restore container may need local cleanup: '+name
        status['finished_at_utc'] = now()
        status['all_rehearsal_checks_passed'] = bool(status['comparison_passed'] and status['cleanup_passed'])
        status['next'] = 'A green rehearsal proves only archive restoration/comparison. App tests, login, historical invoices and cutover remain separate.'
        evidence = Path(args.out).resolve()
        evidence.parent.mkdir(parents=True, exist_ok=True)
        write_json(evidence, status)
    return status


def doctor(args) -> dict:
    result = {'operation': 'doctor', 'tool_version': VERSION, 'checked_at_utc': now(),
              'host': {'system': platform.system(), 'machine': platform.machine(), 'python': platform.python_version()},
              'database_accessed': False, 'live_environment_modified': False,
              'mac_native_validation': 'not_performed_by_this_probe',
              'architecture_image_support': 'requires actual target pull/build and tests'}
    if args.source:
        inv = source_inventory(Path(args.source))
        result['source'] = {k: inv[k] for k in ('declared_version','unlisted_file_count','runtime_image_matches_source')}
        result['source']['declared_files_present'] = len(inv['files'])
        result['source']['locally_modified_file_count'] = len(inv['locally_modified_files'])
    try:
        d = Docker()
        result['docker'] = d.info | {'local_engine_available': True}
    except MigrationError as exc:
        result['docker'] = {'local_engine_available': False, 'reason': str(exc)}
    if args.out:
        out = Path(args.out).resolve(); out.parent.mkdir(parents=True, exist_ok=True)
        write_json(out, result)
    return result


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    d = sub.add_parser('doctor', help='Read-only environment/source preflight; no database queries')
    d.add_argument('--source'); d.add_argument('--out')
    e = sub.add_parser('export', help='Create a PRIVATE logical transfer bundle; no source writes or stop/start')
    e.add_argument('--source', required=True); e.add_argument('--db', required=True); e.add_argument('--out', required=True)
    e.add_argument('--confirm-private-data', action='store_true')
    e.add_argument('--cutover', action='store_true'); e.add_argument('--confirm-writers-stopped', action='store_true')
    i = sub.add_parser('inspect', help='Offline checksums/content structure only; not a restore')
    i.add_argument('--bundle', required=True)
    r = sub.add_parser('rehearse', help='Restore only into a newly created, network-isolated disposable PostgreSQL 17')
    r.add_argument('--bundle', required=True); r.add_argument('--out', required=True)
    r.add_argument('--confirm-trusted-backup', action='store_true')
    return p


def main(argv=None) -> int:
    if sys.version_info < (3, 11):
        print('Python 3.11+ is required for the migration tool (not for the Docker-only verifier).'); return 2
    args = parser().parse_args(argv)
    try:
        if args.command == 'doctor':
            value = doctor(args)
            code = 0 if value['docker']['local_engine_available'] else 2
        elif args.command == 'inspect':
            manifest = verify_bundle(Path(args.bundle))
            value = {'checksums_and_structure_passed': True, 'restoration_proven': False,
                     'source_version': json.loads((Path(args.bundle)/'source_manifest.json').read_text(encoding='utf-8'))['declared_version'],
                     'format': manifest['format']}; code = 0
        elif args.command == 'export': value = export_bundle(args, Docker()); code = 0
        else:
            if Path(args.out).exists(): raise MigrationError('Evidence path already exists; choose a new filename.')
            value = rehearse(args, Docker()); code = 0 if value['all_rehearsal_checks_passed'] else 1
        print(json.dumps(value, ensure_ascii=False, indent=2)); return code
    except (MigrationError, OSError, ValueError, KeyError, TypeError) as exc:
        error = str(exc) if isinstance(exc, MigrationError) else type(exc).__name__
        print(json.dumps({'completed': False, 'error': error,
                          'action': 'Keep the original Windows project/database. Never skip validation or delete old volumes.'}, ensure_ascii=False, indent=2))
        return 1
    except KeyboardInterrupt:
        print('Interrupted. Preserve the source; inspect only the printed disposable restore container for cleanup.'); return 130

if __name__ == '__main__':
    raise SystemExit(main())
