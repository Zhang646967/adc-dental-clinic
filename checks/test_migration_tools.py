"""Portable migration unit tests; fake Docker/Session tests are NOT database restores."""
from __future__ import annotations
import argparse
import ast
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts import migration_core as core
from scripts import migration_tool as tool

ROOT=Path(__file__).resolve().parents[1]
CID='a'*64
NEWID='b'*64


def sample_snapshot():
    return {'server_major':17,'encoding':'UTF8',
            'tables':{n:{'rows':1,'row_md5':'c'*32} for n in sorted(core.REQUIRED_TABLES)},
            'schema':{'constraints':[],'indexes':[],'columns':[],'user_triggers':[],'functions':[],'extensions':[]}}


def make_source(root):
    root.mkdir()
    (root/'scripts').mkdir()
    (root/'docs/sql').mkdir(parents=True)
    (root/'manage.py').write_text('print("synthetic")\n')
    (root/'scripts/entry.sh').write_text('#!/bin/bash\nexit 0\n')
    (root/'docs/sql/guard.sql').write_text('-- documented schema guard\n')
    files={n:core.sha256_file(root/n) for n in ('manage.py','scripts/entry.sh','docs/sql/guard.sql')}
    (root/'UPDATE_MANIFEST.json').write_text(json.dumps({'target':'0.7','files':files}))
    return root


class FakeSession:
    closed=0
    def __init__(self,*a):pass
    def scalar(self,sql):return '00000003-0000001A-1'
    def snapshot(self):return sample_snapshot()
    def close(self):FakeSession.closed+=1


class FakeDocker:
    info={'Architecture':'aarch64','OSType':'linux','ServerVersion':'fake'}
    def __init__(self, fail=None):self.calls=[];self.owner=None;self.fail=fail;self.other_running=False
    def inspect(self,cid):
        if cid==NEWID:return {'Id':NEWID,'Config':{'Labels':{'adc.migration.owner':self.owner}},'Image':'fake-pg17'}
        return {'Id':CID,'State':{'Running':True},'Image':'fake-source-image',
                'Config':{'Env':['POSTGRES_DB=adc_local','POSTGRES_USER=adc_local'],
                          'Labels':{'com.docker.compose.service':'db','com.docker.compose.project':'adc_old'}}}
    def run(self,args,**kw):
        self.calls.append(args)
        joined=' '.join(args)
        if self.fail and self.fail in joined:raise core.MigrationError('Injected command failure.')
        if args[0]=='ps':return CID+'\n'
        if kw.get('stdout_file') is not None:kw['stdout_file'].write(b'PGDMP synthetic only');return ''
        if args[0]=='create':
            self.owner=next(v.split('=',1)[1] for v in args if v.startswith('adc.migration.owner='));return NEWID
        return ''


class PureContracts(unittest.TestCase):
    def test_normal_relative_path(self):self.assertEqual(str(core.safe_relative('患者/test.py')),'患者/test.py')
    def test_path_traversal_and_absolute_rejected(self):
        for n in ['../x','/x','a/../x','D:/x','a\\b','a//b','a/./b']:
            with self.subTest(n=n),self.assertRaises(core.MigrationError):core.safe_relative(n)
    def test_reserved_windows_filenames(self):
        for n in ['CON.py','data/aux.txt','LPT1','x/a.','a:b','a\nx']:
            with self.subTest(n=n),self.assertRaises(core.MigrationError):core.safe_relative(n)
    def test_case_collision(self):
        with self.assertRaises(core.MigrationError):core.validate_names(['a/Views.py','a/views.py'])
    def test_unicode_normalization_collision(self):
        with self.assertRaises(core.MigrationError):core.validate_names(['caf\u00e9.py','cafe\u0301.py'])
    def test_private_paths_filtered(self):
        for n in ['.env','.ENV','.env.local','.local_credentials.txt','.git/config','.venv/bin/python',
                  'media/a.png','backups/a.txt','private_migration/a.json','x/password.pem','a.dump','export.sql']:
            with self.subTest(n=n):self.assertTrue(core.private_name(n))
    def test_documented_sql_is_preserved(self):self.assertFalse(core.private_name('docs/sql/guard.sql'))
    def test_identifier_quoting(self):self.assertEqual(core.sql_identifier('x";DROP'),'"x"";DROP"')
    def test_identifier_nul_rejected(self):
        with self.assertRaises(core.MigrationError):core.sql_identifier('a\x00b')
    def test_equal_snapshots(self):self.assertTrue(core.compare_snapshots(sample_snapshot(),sample_snapshot())['all_compared_equal'])
    def test_changed_rows(self):
        x=sample_snapshot();x['tables']['adc_visit']['rows']=2
        self.assertEqual(core.compare_snapshots(sample_snapshot(),x)['differing_tables'],['adc_visit'])
    def test_changed_digest_not_hidden_by_equal_counts(self):
        x=sample_snapshot();x['tables']['adc_user']['row_md5']='a'*32
        self.assertFalse(core.compare_snapshots(sample_snapshot(),x)['all_compared_equal'])
    def test_missing_table(self):
        x=sample_snapshot();del x['tables']['adc_invoice']
        with self.assertRaises(core.MigrationError):core.validate_snapshot(x)
    def test_pg_major_change_rejected(self):
        x=sample_snapshot();x['server_major']=18
        with self.assertRaises(core.MigrationError):core.validate_snapshot(x)
    def test_boolean_row_count_rejected(self):
        x=sample_snapshot();x['tables']['adc_visit']['rows']=True
        with self.assertRaises(core.MigrationError):core.validate_snapshot(x)
    def test_schema_change_detected(self):
        x=sample_snapshot();x['schema']['user_triggers']=['missing']
        self.assertFalse(core.compare_snapshots(sample_snapshot(),x)['schema_metadata_equal'])
    def test_remote_environment_rejected_before_command(self):
        with patch.dict(os.environ,{'DOCKER_HOST':'tcp://remote:2375'}),self.assertRaises(core.MigrationError):tool.local_env()
    def test_compose_ambient_overrides_removed(self):
        with patch.dict(os.environ,{'COMPOSE_FILE':'production.yml','COMPOSE_PROJECT_NAME':'original','DOCKER_DEFAULT_PLATFORM':'linux/amd64'},clear=True):
            env=tool.local_env();self.assertNotIn('COMPOSE_FILE',env);self.assertNotIn('DOCKER_DEFAULT_PLATFORM',env)
    def test_local_environment_allowed(self):
        with patch.dict(os.environ,{'DOCKER_HOST':'unix:///tmp/docker.sock'},clear=True):self.assertIsInstance(tool.local_env(),dict)
    def test_explicit_source_id_required(self):
        with self.assertRaises(core.MigrationError):tool.source_db(FakeDocker(),'db')
    def test_source_wrong_service_rejected(self):
        d=FakeDocker();d.inspect=lambda x:{'State':{'Running':True},'Config':{'Labels':{'com.docker.compose.service':'web'}}}
        with self.assertRaises(core.MigrationError):tool.source_db(d,CID)
    def test_source_connection_url_cannot_override_local_socket(self):
        d=FakeDocker();base=d.inspect(CID)
        base['Config']['Env']=['POSTGRES_DB=postgresql://remote/private','POSTGRES_USER=adc_local']
        d.inspect=lambda _:base
        with self.assertRaises(core.MigrationError):tool.source_db(d,CID)
    def test_cutover_refuses_running_sibling(self):
        d=FakeDocker();d.run=lambda *a,**k:CID+'\n'+'c'*64+'\n'
        old=d.inspect
        d.inspect=lambda c:old(c) if c==CID else {'Id':'c'*64}
        with self.assertRaises(core.MigrationError):tool.source_db(d,CID,cutover=True)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.src=make_source(self.base/'source with spaces');self.out=self.base/'private backup'
    def tearDown(self):self.tmp.cleanup()
    def args(self,**kwargs):
        return argparse.Namespace(**({'source':str(self.src),'db':CID,'out':str(self.out),
          'confirm_private_data':True,'cutover':False,'confirm_writers_stopped':False}|kwargs))
    def export(self,d=None):
        with patch.object(tool,'Session',FakeSession):return tool.export_bundle(self.args(),d or FakeDocker())
    def test_original_v07_manifest_with_separate_checksums_supported(self):
        p=self.src/'UPDATE_MANIFEST.json';v=json.loads(p.read_text())
        (self.src/'CHECKSUMS.sha256').write_text(''.join(h+'  '+n+'\n' for n,h in v['files'].items()))
        p.write_text(json.dumps({'target':'0.7-candidate','basis':'synthetic legacy fixture'}))
        result=self.export()
        self.assertTrue(result['export_completed'])
        with ZipFile(self.out/'source.zip') as z:self.assertIn('CHECKSUMS.sha256',z.namelist())
    def test_export_preserves_source_and_marks_not_restored(self):
        before={p.relative_to(self.src):p.read_bytes() for p in self.src.rglob('*') if p.is_file()}
        result=self.export()
        self.assertTrue(result['export_completed']);self.assertFalse(result['restored_and_verified'])
        self.assertEqual(before,{p.relative_to(self.src):p.read_bytes() for p in self.src.rglob('*') if p.is_file()})
        self.assertEqual(core.verify_bundle(self.out)['format'],core.FORMAT)
    def test_export_uses_snapshot_flag_and_no_stop(self):
        d=FakeDocker();self.export(d)
        dump=next(c for c in d.calls if '--snapshot' in ' '.join(c))
        self.assertIn('00000003-0000001A-1',dump)
        self.assertFalse(any(c[0] in ('stop','rm','restart') for c in d.calls))
    def test_export_requires_private_ack(self):
        with self.assertRaises(core.MigrationError):tool.export_bundle(self.args(confirm_private_data=False),FakeDocker())
        self.assertFalse(self.out.exists())
    def test_export_outside_repo(self):
        with self.assertRaises(core.MigrationError):tool.export_bundle(self.args(out=str(self.src/'copy')),FakeDocker())
    def test_export_cutover_needs_freeze_ack(self):
        with self.assertRaises(core.MigrationError):tool.export_bundle(self.args(cutover=True),FakeDocker())
    def test_export_never_overwrites_existing_bundle(self):
        self.out.mkdir()
        with self.assertRaises(FileExistsError):self.export()
    def test_no_env_or_unlisted_file_in_source_zip(self):
        (self.src/'.env').write_text('API_KEY=synthetic-private')
        (self.src/'unlisted.txt').write_text('uncommitted-note')
        result=self.export()
        self.assertEqual(result['unlisted_source_files'],1)
        with ZipFile(self.out/'source.zip') as z:
            self.assertNotIn('.env',z.namelist());self.assertNotIn('unlisted.txt',z.namelist())
    def test_modified_declared_source_preserved(self):
        (self.src/'manage.py').write_text('# local change\n')
        self.assertEqual(self.export()['local_source_edits_preserved'],1)
        with ZipFile(self.out/'source.zip') as z:self.assertEqual(z.read('manage.py'),b'# local change\n')
    def test_missing_declared_source_stops_export(self):
        (self.src/'manage.py').unlink()
        with self.assertRaises(core.MigrationError):self.export()
    def test_source_edit_during_pack_rejected(self):
        inv=core.source_inventory(self.src);(self.src/'manage.py').write_text('# race\n')
        with self.assertRaises(core.MigrationError):core.pack_source(self.src,self.base/'x.zip',inv)
    def test_symlink_rejected(self):
        (self.src/'manage.py').unlink();(self.base/'private.py').write_text('secret')
        (self.src/'manage.py').symlink_to(self.base/'private.py')
        with self.assertRaises(core.MigrationError):self.export()
    def test_truncated_dump_detected(self):
        self.export();(self.out/'database.dump').write_bytes(b'PGDMP')
        with self.assertRaises(core.MigrationError):core.verify_bundle(self.out)
    def test_modified_dump_detected(self):
        self.export();p=self.out/'database.dump';b=p.read_bytes();p.write_bytes(b[:-1]+b'X')
        with self.assertRaises(core.MigrationError):core.verify_bundle(self.out)
    def test_incomplete_marker_blocks_restore(self):
        self.export();(self.out/'INCOMPLETE').touch()
        with self.assertRaises(core.MigrationError):core.verify_bundle(self.out)
    def test_manifest_traversal_payload_rejected(self):
        self.export();p=self.out/'manifest.json';v=json.loads(p.read_text());v['files']['../x']=v['files'].pop('source.zip');p.write_text(json.dumps(v))
        with self.assertRaises(core.MigrationError):core.verify_bundle(self.out)
    def test_failure_retains_incomplete_not_success(self):
        with self.assertRaises(core.MigrationError):self.export(FakeDocker(fail='pg_dump'))
        self.assertTrue((self.out/'INCOMPLETE').exists());self.assertFalse((self.out/'manifest.json').exists())
    def test_rehearsal_is_fresh_no_ports_no_source_mount(self):
        self.export();d=FakeDocker()
        args=argparse.Namespace(bundle=str(self.out),out=str(self.base/'result.json'),confirm_trusted_backup=True)
        with patch.object(tool,'Session',FakeSession):result=tool.rehearse(args,d)
        self.assertTrue(result['all_rehearsal_checks_passed'])
        create=next(c for c in d.calls if c[0]=='create')
        self.assertEqual(create[create.index('--network')+1],'none')
        self.assertNotIn('--publish',create);self.assertNotIn('--mount',create)
        self.assertIn('--tmpfs',create)
        self.assertEqual(next(c for c in d.calls if c[0]=='rm'),['rm','--force',NEWID])
    def test_rehearsal_failure_still_cleans_only_new_container(self):
        self.export();d=FakeDocker(fail='pg_restore')
        args=argparse.Namespace(bundle=str(self.out),out=str(self.base/'failed.json'),confirm_trusted_backup=True)
        with patch.object(tool,'Session',FakeSession):result=tool.rehearse(args,d)
        self.assertFalse(result['restore_executed']);self.assertFalse(result['all_rehearsal_checks_passed'])
        self.assertTrue(result['cleanup_passed']);self.assertIn(['rm','--force',NEWID],d.calls)
    def test_cleanup_needs_matching_ownership(self):
        self.export();d=FakeDocker();old=d.inspect
        d.inspect=lambda c: {'Config':{'Labels':{'adc.migration.owner':'other'}}} if c==NEWID else old(c)
        args=argparse.Namespace(bundle=str(self.out),out=str(self.base/'failed.json'),confirm_trusted_backup=True)
        with patch.object(tool,'Session',FakeSession):result=tool.rehearse(args,d)
        self.assertFalse(result['cleanup_passed']);self.assertFalse(any(c[0]=='rm' for c in d.calls))
    def test_rehearsal_needs_trust_ack(self):
        args=argparse.Namespace(bundle=str(self.out),out=str(self.base/'x.json'),confirm_trusted_backup=False)
        d=FakeDocker()
        with self.assertRaises(core.MigrationError):tool.rehearse(args,d)
        self.assertEqual(d.calls,[])
    def test_doctor_no_database_commands(self):
        with patch.object(tool,'Docker',return_value=FakeDocker()):r=tool.doctor(argparse.Namespace(source=str(self.src),out=None))
        self.assertFalse(r['database_accessed']);self.assertFalse(r['live_environment_modified'])
    def test_doctor_missing_engine_not_success(self):
        with patch.object(tool,'Docker',side_effect=core.MigrationError('not installed')):r=tool.doctor(argparse.Namespace(source=str(self.src),out=None))
        self.assertFalse(r['docker']['local_engine_available'])


class PlatformEntryTests(unittest.TestCase):
    def test_mac_verifier_no_host_python_requirement(self):
        s=(ROOT/'VERIFY_ISOLATED_MAC.sh').read_text()
        self.assertIn('python:3.13-slim',s);self.assertNotIn('command -v python',s)
        self.assertIn('--validate-config',s);self.assertIn('--env-file',s)
        self.assertNotIn('down -v',s);self.assertNotIn('/var/run/docker.sock',s)
    def test_mac_shells_are_lf_without_bom(self):
        for name in ['VERIFY_ISOLATED_MAC.sh','ADC_MIGRATION_MAC.sh']:
            b=(ROOT/name).read_bytes();self.assertNotIn(b'\r\n',b);self.assertTrue(b.startswith(b'#!/bin/bash\n'))
    def test_no_architecture_forcing_in_current_compose(self):
        for name in ['compose.yaml','compose.verify.yaml','Dockerfile']:
            self.assertNotIn('linux/amd64',(ROOT/name).read_text())
    def test_host_tools_never_import_django(self):
        for name in ['migration_core.py','migration_tool.py']:
            s=(ROOT/'scripts'/name).read_text();self.assertNotIn('import django',s);self.assertNotIn('import psycopg',s)
    def test_no_destructive_live_restore_command(self):
        s=(ROOT/'scripts/migration_tool.py').read_text()
        self.assertNotIn('--clean',s);self.assertNotIn('DROP DATABASE',s);self.assertFalse(any(k.arg=='shell' and isinstance(k.value,ast.Constant) and k.value.value is True for n in ast.walk(ast.parse(s)) if isinstance(n,ast.Call) for k in n.keywords))
        self.assertIn('--single-transaction',s);self.assertIn('--exit-on-error',s)
    def test_git_contract_separates_crlf_and_lf(self):
        s=(ROOT/'.gitattributes').read_text();self.assertIn('*.cmd text eol=crlf',s);self.assertIn('*.sh text eol=lf',s)
    def test_sql_read_contract(self):
        self.assertIn('REPEATABLE READ READ ONLY',(ROOT/'scripts/migration_tool.py').read_text())
        self.assertIn('pg_export_snapshot',(ROOT/'scripts/migration_tool.py').read_text())

if __name__=='__main__':unittest.main()
