from django.conf import settings
from django.core.exceptions import PermissionDenied
from accounts.finance_access import lock_finance_write
from accounts.models import RoleAssignment
from accounts.policies import bindings, lock_clinic_grant, require_writable
from adc_core.proposals import workspace_binding

ROLES = ('FRONT_DESK', 'MANAGER', 'FINANCE', 'HQ')


def scope(actor, roles=ROLES, *, lock=False):
    b = workspace_binding(actor, roles)
    if lock:
        if not settings.ADC_CLINICAL_SYNTHETIC:
            raise PermissionDenied('本阶段仅支持明确的课程合成医保流程。')
        require_writable(actor)
    if b['role'] in ('FRONT_DESK', 'MANAGER'):
        if lock:
            lock_clinic_grant(actor, b['clinic'], (b['role'],))
        elif not bindings(actor).filter(role=b['role'], scope_kind='CLINIC', clinic_id=b['clinic']).exists():
            raise PermissionDenied('请先选择获授权的本店工作区。')
    elif b['role'] in ('FINANCE', 'HQ'):
        if lock:
            lock_finance_write(actor)
        elif not bindings(actor).filter(role=b['role'], scope_kind='CHAIN').exists():
            raise PermissionDenied('需要当前全链财务或总部汇总授权。')
    return b


def preparer_active(user_id, role, clinic_id=None):
    q = RoleAssignment.objects.filter(user_id=user_id, user__is_active=True, is_active=True, role=role)
    return q.filter(scope_kind='CHAIN' if role == 'FINANCE' else 'CLINIC', clinic_id=clinic_id).exists()
