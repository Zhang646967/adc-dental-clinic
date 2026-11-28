"""Exercise private Linux services with new data, HTTPS forms and independent PG volumes."""
import argparse
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.clinic_release import ClinicInstallation
from scripts.g4_course import digest, exclusive, private_directory
from scripts.g4_prepare import prepare
from scripts.g4_mac_demo import atomic_text


class Hidden(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('type') == 'hidden' and attrs.get('name'):
            self.values[attrs['name']] = attrs.get('value', '')


class Forms:
    """Talk to the real gateway with TLS verification and ordinary signed HTML forms."""
    def __init__(self, clinic, folder):
        self.host = clinic.plan['host']
        self.port = clinic.plan['ports'][1]
        self.ca = clinic.ca_file
        self.cookies = folder / ('cookies-' + secrets.token_hex(6))

    def request(self, path, values=None):
        cmd = ['curl', '--silent', '--show-error', '--noproxy', '*', '--max-time', '25',
               '--connect-to', f'{self.host}:443:127.0.0.1:{self.port}', '--cacert', str(self.ca),
               '--cookie', str(self.cookies), '--cookie-jar', str(self.cookies),
               '--referer', 'https://' + self.host + path, '--write-out', '\n%{http_code}\n%{redirect_url}']
        if values is not None:
            cmd += ['--data-binary', '@-', '--header', 'Content-Type: application/x-www-form-urlencoded']
        raw = subprocess.run(cmd + ['https://' + self.host + path], check=True, capture_output=True,
                             input=urlencode(values).encode() if values is not None else None).stdout.decode()
        body, status, location = raw.rsplit('\n', 2)
        return int(status), body, location.removeprefix('https://' + self.host)

    def submit(self, path, values):
        status, html, _ = self.request(path)
        assert status == 200, (path, status)
        hidden = Hidden()
        hidden.feed(html)
        assert 'csrfmiddlewaretoken' in hidden.values, path
        status, _, location = self.request(path, hidden.values | values)
        assert status == 302, (path, status)
        return location

    def login(self, account):
        return self.submit('/accounts/login/', account)

    def grant_frontdesk(self, administrator, username):
        self.login(administrator)
        password = secrets.token_urlsafe(25)
        authority = dict(reason='门店岗位交接核验', operator_password=administrator['password'], confirmed='on')
        detail = self.submit('/technical/accounts/new/', authority | dict(
            username=username, password1=password, password2=password))
        assert re.fullmatch('/technical/accounts/[0-9]+/', detail)
        assert self.submit(detail + 'grant/', authority | dict(role='FRONT_DESK', clinic=1)) == detail
        return {'username': username, 'password': password}


def configure(args, release, name, ports):
    folder = private_directory(args.workdir / name)
    bundle = folder / '.g4'
    host = name + '.clinic.example.org'
    prepare(bundle, host=host, source_commit=release['source_commit'], app_image=release['app_image'],
            db_image=args.db_image, nginx_image=args.nginx_image, bind_ip='127.0.0.1',
            http_port=ports[0], https_port=ports[1], architecture=args.architecture,
            access_mode='clinic-writable', dataset='empty')
    cert = bundle / 'tls/fullchain.pem'
    key = bundle / 'tls/privkey.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-sha256',
                    '-days', '2', '-subj', '/CN=' + host, '-addext', 'subjectAltName=DNS:' + host,
                    '-addext', 'basicConstraints=critical,CA:TRUE', '-addext',
                    'keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign',
                    '-out', str(cert), '-keyout', str(key)], check=True, capture_output=True)
    return ClinicInstallation(bundle, context=args.context, rehearsal=True,
                              architecture=args.architecture, ca_file=cert)


def sql(clinic, query):
    return clinic.dc('exec', '-T', 'db', 'psql', '-XAt', '-v', 'ON_ERROR_STOP=1',
                     '-U', 'adc_g4_admin', '-d', 'adc_clinic', '-c', query).decode().strip()


def records(clinic):
    return sql(clinic, """SELECT json_build_object(
     'clinics',(SELECT count(*) FROM adc_clinic),
     'users',(SELECT count(*) FROM adc_user),
     'grants',(SELECT count(*) FROM adc_role_assignment WHERE is_active),
     'patients',(SELECT count(*) FROM adc_patient),
     'visits',(SELECT count(*) FROM adc_visit),
     'grants_hash',(SELECT md5(string_agg(concat_ws('|',id,user_id,role,scope_kind,clinic_id,is_active),'/' ORDER BY id))
                      FROM adc_role_assignment));""")


def check_frontdesk(clinic, folder, account):
    session = Forms(clinic, folder)
    target = session.login(account)
    assert target and '/accounts/login' not in target
    assert session.request('/technical/accounts/')[0] == 403
    assert sql(clinic, 'SELECT count(*) FROM adc_user WHERE is_superuser OR is_staff;') == '0'


def exercise(args):
    active = recovery = None
    work = private_directory(args.workdir)
    candidate = json.loads((args.candidate / 'build.json').read_text())
    previous = json.loads((args.previous / 'build.json').read_text())
    assert candidate['source_commit'] != previous['source_commit']
    # The release rehearsal uses its own recipient and never prints a secret.
    key = work / 'restore-identity'
    public = work / 'recipient'
    subprocess.run([args.age_keygen, '-o', str(key)], check=True, capture_output=True)
    atomic_text(public, subprocess.check_output([args.age_keygen, '-y', str(key)], text=True))
    institution = work / 'institution.json'
    admin = {'username': 'technical-' + secrets.token_hex(5), 'password': secrets.token_urlsafe(28)}
    atomic_text(institution, json.dumps({'clinic': {'clinic_code': 'HF01', 'name': '海棠门诊',
                'postal_address': '核验路一号', 'supervisor_name': '何主任', 'phone': '000-0000000',
                'email': 'office@example.org', 'area_sqm': '160.00'}, 'administrator': admin}))
    try:
        active = configure(args, candidate, 'first', (args.port, args.port+1))
        recovery = configure(args, candidate, 'recovery', (args.port+2, args.port+3))
        with exclusive(active.bundle / 'private/release.lock'):
            result = active.deploy(institution)
        assert result['status'] == 'ORIGIN_READY'
        initial = json.loads(records(active))
        assert [initial[k] for k in ('clinics','users','grants','patients','visits')] == [1,1,1,0,0]
        source_storage = active.database_identity()
        desker = Forms(active, work).grant_frontdesk(admin, 'front-' + secrets.token_hex(4))
        check_frontdesk(active, work, desker)
        # The previous image predates clean installation. Run it against the same
        # migrated institution before exercising the real old-to-new upgrade.
        previous_sha, current_sha = previous['source_commit'], candidate['source_commit']
        result = active.upgrade(args.previous, public, current_sha, args.age)
        assert result['status'] == 'UPGRADED'
        assert active.plan['requested_source_commit'] == previous_sha
        check_frontdesk(active, work, desker)
        prior = records(active)
        # Inject a real TLS trust failure *after* a successful write through the
        # candidate gateway. The ordinary upgrade recovery must keep that write.
        ordinary_status = active.status
        successor = []
        def independent_probe():
            if active.plan['requested_source_commit'] == current_sha and not successor:
                account = Forms(active, work).grant_frontdesk(admin, 'continuity-' + secrets.token_hex(4))
                successor.append(account)
                orig_ca = active.ca_file
                try:
                    active.ca_file = recovery.ca_file
                    return ordinary_status()
                finally:
                    active.ca_file = orig_ca
            return ordinary_status()
        active.status = independent_probe
        try:
            try:
                active.upgrade(args.candidate, public, previous_sha, args.age)
            except RuntimeError:
                action = json.loads((active.bundle / 'private/release-operation.json').read_text())
                assert action['status'] == 'FAILED_IMAGE_REVERTED' and not action['database_restored']
            else:
                raise AssertionError('Trust failure should revert to the previous image.')
        finally:
            active.status = ordinary_status
        assert len(successor) == 1 and active.plan['requested_source_commit'] == previous_sha
        check_frontdesk(active, work, successor[0])
        following = records(active)
        assert json.loads(following)['users'] == json.loads(prior)['users'] + 1
        assert json.loads(following)['grants'] == json.loads(prior)['grants'] + 1
        result = active.upgrade(args.candidate, public, previous_sha, args.age)
        assert result['status'] == 'UPGRADED' and active.plan['requested_source_commit'] == current_sha
        assert following == records(active) and active.database_identity() == source_storage
        check_frontdesk(active, work, successor[0])
        with exclusive(active.bundle / 'private/release.lock'):
            result = active.backup(public, args.age)
        transfer = private_directory(work / 'private-transfer')
        sealed = transfer / result['name']
        shutil.copyfile(active.bundle / 'backups' / sealed.name, sealed)
        sealed.chmod(0o600)
        assert digest(sealed) == result['sha256']
        started = time.monotonic()
        result = recovery.restore(sealed, key, args.age, schema_mode='migration-built')
        assert result['business_comparison'] == 'PASSED'
        assert recovery.status()['status'] == 'ORIGIN_READY' and following == records(recovery)
        assert recovery.database_identity()['volume'] != source_storage['volume']
        check_frontdesk(recovery, work, successor[0])
        print(json.dumps({'installation': 'PASS', 'https_login_and_frontdesk_grant': 'PASS',
               'upgrade': {'previous': previous_sha, 'current': current_sha},
               'failed_upgrade': 'previous image, original volume, new account and new audited grant retained',
               'encrypted_restore': result['restore']['comparison'],
               'restore_service_elapsed_ms': result['restore']['elapsed_ms'],
               'decrypt_through_staff_login_ms': round((time.monotonic()-started)*1000),
               'storage': 'two independent Compose projects and PG17 volumes on the same engine',
               'public_or_customer_deployment': False}, indent=2))
    finally:
        for clinic in (recovery, active):
            if clinic:
                # Only our explicitly prepared projects. Leave all volumes for examination.
                clinic.dc('stop', '--timeout', '20', timeout=120)


if __name__ == '__main__':
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    for field in ('workdir', 'candidate', 'previous'):
        p.add_argument('--' + field, type=Path, required=True)
    for field in ('context', 'architecture', 'db-image', 'nginx-image'):
        p.add_argument('--' + field, required=True)
    p.add_argument('--age', default='age')
    p.add_argument('--age-keygen', default='age-keygen')
    p.add_argument('--port', type=int, default=19574)
    exercise(p.parse_args())
