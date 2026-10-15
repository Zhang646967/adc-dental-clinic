from django.core.exceptions import PermissionDenied
from accounts.policies import bindings, lock_clinic_grant
from adc_core.proposals import workspace_binding
from registry.models import Clinic

def equipment_scope(actor):
    binding = workspace_binding(actor, ('MANAGER','FINANCE','HQ'))
    if binding['role'] == 'MANAGER':
        if binding['clinic'] is None or not bindings(actor).filter(
                role='MANAGER',scope_kind='CLINIC',clinic_id=binding['clinic']).exists():
            raise PermissionDenied('请选择获授权的当前诊所。')
        return binding['clinic']
    if not bindings(actor).filter(role=binding['role'],scope_kind='CHAIN').exists():
        raise PermissionDenied('需要当前全链查询授权。')
    return None

def manager_clinic(actor, lock=False):
    binding = workspace_binding(actor, ('MANAGER',))
    clinic_id = equipment_scope(actor)
    if lock:
        lock_clinic_grant(actor,clinic_id,roles=('MANAGER',))
    if not Clinic.objects.filter(pk=clinic_id,is_active=True).exists():
        raise PermissionDenied('当前诊所已停用。')
    return clinic_id
