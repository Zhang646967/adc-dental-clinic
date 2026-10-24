"""Small shared rules for the two explicitly owned coordination workflows."""
from datetime import datetime,date
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from accounts.models import RoleAssignment
from accounts.policies import require_clinic
from adc_core.rules import RuleError
from workspaces.context import require_active


def front_clinic(actor):
    require_active(actor,('FRONT_DESK',));clinic_id=actor._adc_workspace.clinic_id
    require_clinic(actor,clinic_id);return clinic_id


def moment(value,label,*,future=False):
    if isinstance(value,str):
        try:value=datetime.fromisoformat(value)
        except ValueError:raise RuleError('请核对'+label+'。')
    if not isinstance(value,datetime) or timezone.is_naive(value):raise RuleError(label+'需明确北京时间。')
    if future and value<=timezone.now():raise RuleError(label+'需在未来，便于继续跟进。')
    if not future and value>timezone.now():raise RuleError(label+'不能晚于当前时间。')
    return value


def day(value,label):
    if isinstance(value,date) and not isinstance(value,datetime):return value
    try:return date.fromisoformat(value)
    except (TypeError,ValueError):raise RuleError('请核对'+label+'。')


def available_front(user_id,clinic_id):
    return RoleAssignment.objects.filter(user_id=user_id,user__is_active=True,role='FRONT_DESK',scope_kind='CLINIC',clinic_id=clinic_id,is_active=True).exists()


def require_owner(actor,owner_id,clinic_id):
    if owner_id is None:raise RuleError('尚无前台协调责任，请先认领并明确内部跟进期限。')
    if owner_id!=actor.pk:
        raise PermissionDenied('此事项由其他前台负责；原负责人失效时请先明确接续责任。')
    if not available_front(owner_id,clinic_id):raise PermissionDenied('联系责任已失效，请由在岗前台接续。')
