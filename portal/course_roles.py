"""Prefill a dedicated trial account, without authenticating or granting access."""
import hashlib
import hmac
import json
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from accounts.models import UserAccount
from portal.mini_api import endpoint, result
from portal.models import PatientAccess
from portal.policies import active_grants
from workspaces.context import available_roles


ROLE_OPTIONS = {
    'owner': ('patient', '患者本人', 'PATIENT'),
    'delegate': ('patient', '预约代办', 'PATIENT'),
    'medical': ('patient', '医疗代理', 'PATIENT'),
    'front': ('staff', '前台', 'FRONT_DESK'),
    'dentist': ('staff', '医师', 'DENTIST'),
    'nurse': ('staff', '护理', 'NURSE'),
    'pharmacist': ('staff', '药房', 'PHARMACIST'),
    'finance': ('staff', '财务', 'FINANCE'),
    'manager': ('staff', '门店主管', 'MANAGER'),
    'hq': ('staff', '总部管理', 'HQ'),
}
INVITE_PATTERN = re.compile(r'[A-Za-z0-9_-]{43}')


@sensitive_variables()
def current_roster(filename):
    if not settings.ADC_CLINICAL_SYNTHETIC or not filename:
        return {}
    try:
        path = Path(filename)
        with path.open('rb') as file:
            contents = file.read(16385)
        if len(contents) > 16384:
            return {}
        value = json.loads(contents)
        expiry = parse_datetime(value['expires_at'])
        if expiry is None or not timezone.is_aware(expiry) or expiry <= timezone.now():
            return {}
        return value if isinstance(value.get('roles'), dict) else {}
    except (OSError, ValueError, TypeError, KeyError):
        return {}


@sensitive_variables()
def invitation(raw):
    if not INVITE_PATTERN.fullmatch(raw):
        return {}
    roster = current_roster(settings.ADC_COURSE_ROLE_FILE)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    expected = roster.get('invite_sha256')
    if isinstance(expected, str) and re.fullmatch('[a-f0-9]{64}', expected) and hmac.compare_digest(expected, digest):
        return roster['roles']
    return {}


@sensitive_variables()
def public_trial_roles():
    if not public_trial_database():
        return {}
    roster = current_roster(settings.ADC_PUBLIC_TRIAL_ROLE_FILE)
    if (roster.get('purpose') != 'public-role-trial-v1' or 'invite_sha256' in roster
            or roster.get('database') != connection.settings_dict['NAME']):
        return {}
    return {
        role: entry for role, entry in roster['roles'].items()
        if role in ROLE_OPTIONS and isinstance(entry, dict) and isinstance(entry.get('username'), str)
        and re.fullmatch(r'trial_' + role + r'(?:_[a-zA-Z0-9_-]+)?', entry['username'])
    }


def public_trial_database():
    return (settings.ADC_CLINICAL_SYNTHETIC and settings.ADC_PUBLIC_TRIAL_ROLE_FILE
            and re.fullmatch(r'adc_public_trial_[a-z0-9_]+', connection.settings_dict['NAME'] or ''))


def require_personal_password(user):
    if public_trial_database() and any(
        re.fullmatch(r'trial_' + role + r'(?:_[a-zA-Z0-9_-]+)?', user.username) for role in ROLE_OPTIONS
    ):
        raise PermissionDenied('此岗位使用共用体验账号，密码由门店统一维护。')


def assigned_to(role, user):
    if set(available_roles(user)) != {ROLE_OPTIONS[role][2]}:
        return False
    if role == 'owner':
        return PatientAccess.objects.filter(user=user, is_active=True, patient__is_active=True).exists()
    if role == 'delegate':
        return active_grants(user).exists()
    if role == 'medical':
        from portal.medical_authority import active_proxies
        return active_proxies(user).exists()
    return True


@sensitive_variables()
def permitted_entry(role, entry, *, verify_password=False):
    if not isinstance(entry, dict):
        return False
    username, password = entry.get('username'), entry.get('password')
    if not isinstance(username, str) or not 0 < len(username) <= 150:
        return False
    if not isinstance(password, str) or not 0 < len(password) <= 128:
        return False
    user = UserAccount.objects.filter(username=username, is_active=True, is_staff=False, is_superuser=False).first()
    return (user is not None and user.has_usable_password() and assigned_to(role, user)
            and (not verify_password or check_password(password, user.password)))


@sensitive_post_parameters('invite')
@endpoint(('POST',), public=True)
@sensitive_variables()
def prefill(request, channel):
    unavailable = {'status': 404, 'code': 'COURSE_UNAVAILABLE',
                   'message': '体验入口无效或已过期。你可以继续手动登录。'}
    public = request.POST.get('trial') == 'public' and 'invite' not in request.POST
    if public:
        roles = public_trial_roles()
    else:
        roles = invitation(request.POST.get('invite', ''))
    role = request.POST.get('role', '')
    if role:
        option = ROLE_OPTIONS.get(role)
        entry = roles.get(role)
        if option is None or option[0] != channel or not permitted_entry(role, entry, verify_password=public):
            return result(request, **unavailable)
        return result(request, {'username': entry['username'], 'password': entry['password']})
    choices = [
        {'id': key, 'label': label} for key, (target, label, _) in ROLE_OPTIONS.items()
        if target == channel and key in roles and permitted_entry(key, roles[key])
    ]
    if not choices:
        return result(request, **unavailable)
    return result(request, {'roles': choices})
