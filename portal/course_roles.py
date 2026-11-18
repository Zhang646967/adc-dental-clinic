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


@sensitive_post_parameters('invite')
@endpoint(('POST',), public=True)
@sensitive_variables()
def prefill(request, channel):
    unavailable = {'status': 404, 'code': 'COURSE_UNAVAILABLE',
                   'message': '体验入口无效或已过期。你可以继续手动登录。'}
    roles = invitation(request.POST.get('invite', ''))
    choices = {key: label for key, (target, label, _) in ROLE_OPTIONS.items()
               if target == channel and key in roles}
    if not choices:
        return result(request, **unavailable)
    role = request.POST.get('role', '')
    if not role:
        return result(request, {'roles': [{'id': key, 'label': label} for key, label in choices.items()]})
    entry = roles.get(role)
    if role not in choices or not isinstance(entry, dict):
        return result(request, **unavailable)
    username, password = entry.get('username'), entry.get('password')
    if not isinstance(username, str) or not 0 < len(username) <= 150 or not isinstance(password, str) or not 0 < len(password) <= 128:
        return result(request, **unavailable)
    user = UserAccount.objects.filter(username=username, is_active=True, is_staff=False, is_superuser=False).first()
    if user is None or not user.has_usable_password() or not assigned_to(role, user):
        return result(request, **unavailable)
    return result(request, {'username': username, 'password': password})
