"""Prefill assigned credentials for a private synthetic course invitation."""
import hashlib
import hmac
import json
import re
from pathlib import Path

from django.conf import settings
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
def invitation(raw):
    if not settings.ADC_CLINICAL_SYNTHETIC or not settings.ADC_COURSE_ROLE_FILE or not INVITE_PATTERN.fullmatch(raw):
        return {}
    try:
        path = Path(settings.ADC_COURSE_ROLE_FILE)
        with path.open('rb') as file:
            contents = file.read(16385)
        if len(contents) > 16384:
            return {}
        value = json.loads(contents)
        expiry = parse_datetime(value['expires_at'])
        digest = hashlib.sha256(raw.encode()).hexdigest()
        if (expiry is None or not timezone.is_aware(expiry) or expiry <= timezone.now()
                or not hmac.compare_digest(value['invite_sha256'], digest)):
            return {}
        return value['roles'] if isinstance(value['roles'], dict) else {}
    except (OSError, ValueError, TypeError, KeyError):
        return {}


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
def permitted_entry(role, entry):
    if not isinstance(entry, dict):
        return False
    username, password = entry.get('username'), entry.get('password')
    if not isinstance(username, str) or not 0 < len(username) <= 150:
        return False
    if not isinstance(password, str) or not 0 < len(password) <= 128:
        return False
    user = UserAccount.objects.filter(username=username, is_active=True, is_staff=False, is_superuser=False).first()
    return user is not None and user.has_usable_password() and assigned_to(role, user)


@sensitive_post_parameters('invite')
@endpoint(('POST',), public=True)
@sensitive_variables()
def prefill(request, channel):
    unavailable = {'status': 404, 'code': 'COURSE_UNAVAILABLE',
                   'message': '体验入口无效或已过期。你可以继续手动登录。'}
    roles = invitation(request.POST.get('invite', ''))
    role = request.POST.get('role', '')
    if role:
        option = ROLE_OPTIONS.get(role)
        entry = roles.get(role)
        if option is None or option[0] != channel or not permitted_entry(role, entry):
            return result(request, **unavailable)
        return result(request, {'username': entry['username'], 'password': entry['password']})
    choices = [
        {'id': key, 'label': label} for key, (target, label, _) in ROLE_OPTIONS.items()
        if target == channel and key in roles and permitted_entry(key, roles[key])
    ]
    if not choices:
        return result(request, **unavailable)
    return result(request, {'roles': choices})
