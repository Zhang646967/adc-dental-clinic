"""Publish only immutable source and runtime artifacts after the installation gate."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.g4_course import digest, private_file
from scripts.g4_prepare import pinned_image


PRIVATE_DIRS = {'.git', '.g4', '.rc', '.ssh', '.runtime', 'private_migration', '私有试用'}
PRIVATE_NAMES = {'institution.json', 'demo-credentials.txt', 'credentials.json', 'identity.txt',
                 'project.private.config.json', 'operations.log', 'database.env', 'runtime.env', 'maintenance.env'}
SECRET = re.compile(rb'(?m)^-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----\r?$|^AGE-SECRET-KEY-1[A-Z0-9]{58,}\r?$')
REPORT_PDF = '课程报告/课程报告_张加良_8210241102.pdf'
DIAGRAM_SOURCE = 'docs/report-source/acceptance/门诊模型.drawio'
MIGRATION = re.compile(r'^[^/]+/migrations/[0-9][^/]*\.py$')


def component_record(archive):
    """Project-relative file names, sorted by UTF-8 bytes, bind names and contents."""
    trees = {'patient_mini_program': {}, 'web_templates_and_assets': {}, 'database_migrations': {}}
    documents = {}
    for item in archive:
        if not item.isfile():
            continue
        name = item.name
        if name.startswith('clients/wechat/'):
            group = trees['patient_mini_program']
        elif name.startswith(('templates/', 'static/')):
            group = trees['web_templates_and_assets']
        elif MIGRATION.fullmatch(name):
            group = trees['database_migrations']
        elif name in (REPORT_PDF, DIAGRAM_SOURCE):
            group = documents
        else:
            continue
        with archive.extractfile(item) as stream:
            group[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    if set(documents) != {REPORT_PDF, DIAGRAM_SOURCE} or not all(trees.values()):
        raise ValueError('Required application, migration or acceptance document missing from release.')
    result = {}
    for label, rows in trees.items():
        tree = hashlib.sha256()
        for name in sorted(rows, key=lambda path: path.encode('utf-8')):
            tree.update(name.encode('utf-8') + b'\0' + rows[name].encode('ascii') + b'\n')
        result[label] = {'files': len(rows), 'sha256': tree.hexdigest()}
    return {'tree_algorithm': 'SHA-256 over sorted UTF-8 repository-relative path + NUL + lowercase file SHA-256 hex + LF',
            'trees': result, 'documents': documents}


def audit_source(source, commit):
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Complete Git revision required.')
    with tempfile.TemporaryFile() as stream:
        subprocess.run(['git', '-C', str(ROOT), 'archive', '--format=tar', commit], stdout=stream, check=True)
        stream.seek(0)
        if hashlib.file_digest(stream, 'sha256').hexdigest() != digest(source):
            raise ValueError('The package source differs from the exact Git archive.')
    with tarfile.open(source) as archive:
        for item in archive:
            path = PurePosixPath(item.name)
            if path.is_absolute() or '..' in path.parts or not (item.isfile() or item.isdir()):
                raise ValueError('Unexpected source archive entry.')
            if (PRIVATE_DIRS.intersection(path.parts) or path.name in PRIVATE_NAMES or path.name == '.env'
                    or path.name.startswith('.env.') or path.suffix.lower() in {'.age','.dump','.sqlite3','.p12','.pfx','.pem','.key'}):
                raise ValueError('Private configuration or recovery material in source archive.')
            if item.isfile() and SECRET.search(archive.extractfile(item).read()):
                raise ValueError('Private key in source archive.')


def assemble(artifacts, output, commit, db_image, nginx_image, context, evidence):
    meta = json.loads(private_file(artifacts / 'build.json').read_text())
    observed = json.loads(private_file(evidence).read_text())
    if (observed['installation'] != 'PASS' or observed['https_login_and_frontdesk_grant'] != 'PASS'
            or observed['upgrade']['current'] != commit or observed['public_or_customer_deployment'] is not False):
        raise ValueError('Installation evidence does not match the candidate.')
    if (meta['source_commit'] != commit or meta['architecture'] != 'amd64'
            or not re.fullmatch('sha256:[0-9a-f]{64}', meta['app_image'])
            or not all(pinned_image(x) for x in (db_image, nginx_image))
            or not db_image.startswith('postgres:17@sha256:') or not nginx_image.startswith('nginx:stable-alpine@sha256:')):
        raise ValueError('Source, architecture or runtime dependencies differ.')
    names = {'source.tar':'source_sha256', 'application.tar':'image_archive_sha256'}
    for name, field in names.items():
        if digest(private_file(artifacts / name)) != meta[field]:
            raise ValueError('Release artifact digest differs.')
    audit_source(artifacts / 'source.tar', commit)
    with tarfile.open(artifacts / 'source.tar') as archive:
        components = component_record(archive)
    image = json.loads(subprocess.check_output(['docker', '--context', context, 'image', 'inspect', meta['app_image']]))[0]
    if (image['Os'] != 'linux' or image['Architecture'] != 'amd64' or image['Config'].get('Labels',{}).get('org.opencontainers.image.revision') != commit
            or any(re.match(r'(POSTGRES_PASSWORD|DJANGO_SECRET_KEY|ADC_WECHAT_MINI_APP_SECRET|ADC_MIGRATION_PASSWORD)=.+', e)
                   for e in image['Config']['Env'])):
        raise ValueError('Runtime image settings differ from the package contract.')
    output.mkdir(mode=0o700)
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        files = {f:artifacts/f for f in [*names,'build.json']}
        deps = folder/'BASE_IMAGES.json'
        deps.write_text(json.dumps({'source_commit':commit, 'postgres':db_image, 'nginx':nginx_image}, indent=2)+'\n')
        files[deps.name] = deps
        release = folder / 'RELEASE.json'
        release.write_text(json.dumps({'schema': 1, 'source_commit': commit,
                                      'source_archive_sha256': meta['source_sha256'], 'runtime_image': meta['app_image'],
                                      'platform': 'linux/amd64', **components,
                                      'installation_rehearsal': {'status': 'passed', 'previous_commit': observed['upgrade']['previous'],
                                           'restore_to_staff_login_ms': observed['decrypt_through_staff_login_ms'], 'storage': observed['storage']},
                                      'institutional_acceptance': 'awaiting_signed_acceptance'},
                                     ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        files[release.name] = release
        checks = folder/'SHA256SUMS'
        checks.write_text(''.join(digest(path)+'  '+name+'\n' for name,path in files.items()))
        files[checks.name] = checks
        name = 'adc-clinic-linux-amd64-' + commit + '.tar'
        target = output / name
        with tarfile.open(target, 'x:') as archive:
            for name, path in files.items():
                info = archive.gettarinfo(str(path), arcname=name)
                info.mode, info.uid, info.gid, info.uname, info.gname = 0o600, 0, 0, '', ''
                with path.open('rb') as stream:
                    archive.addfile(info, stream)
    checksum = digest(target)
    (output/(target.name+'.sha256')).write_text(checksum+'  '+target.name+'\n')
    return {'package':target.name, 'sha256':checksum, 'source_commit':commit, 'architecture':'amd64'}


if __name__ == '__main__':
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    for s in ('artifacts','output','evidence'):
        p.add_argument('--'+s, type=Path, required=True)
    for s in ('source-commit','db-image','nginx-image','context'):
        p.add_argument('--'+s, required=True)
    a = p.parse_args()
    print(json.dumps(assemble(a.artifacts, a.output, a.source_commit, a.db_image, a.nginx_image, a.context, a.evidence)))
