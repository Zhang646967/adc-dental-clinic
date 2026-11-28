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


def assemble(artifacts, output, commit, db_image, nginx_image, context):
    meta = json.loads(private_file(artifacts / 'build.json').read_text())
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
    image = json.loads(subprocess.check_output(['docker', '--context', context, 'image', 'inspect', meta['app_image']]))[0]
    if (image['Architecture'] != 'amd64' or image['Config'].get('Labels',{}).get('org.opencontainers.image.revision') != commit
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
    for s in ('artifacts','output'):
        p.add_argument('--'+s, type=Path, required=True)
    for s in ('source-commit','db-image','nginx-image','context'):
        p.add_argument('--'+s, required=True)
    a = p.parse_args()
    print(json.dumps(assemble(a.artifacts, a.output, a.source_commit, a.db_image, a.nginx_image, a.context)))
