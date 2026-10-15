"""Scope for de-identified reconciliation; never expands clinical/invoice access."""
from django.core.exceptions import PermissionDenied
from accounts.models import RoleAssignment, UserAccount
from accounts.finance_access import lock_finance_write
from adc_core.proposals import workspace_binding
from equipment.policies import manager_clinic
from registry.models import Clinic
from finance.reconciliation_models import PaymentAccount

def reconciliation_scope(actor, *, detail=True):
    binding=workspace_binding(actor,('MANAGER','FINANCE','HQ'))
    if binding['role']=='MANAGER':return manager_clinic(actor)
    if not RoleAssignment.objects.filter(user_id=actor.pk,user__is_active=True,role=binding['role'],scope_kind='CHAIN',is_active=True).exists():
        raise PermissionDenied('需要当前全链财务或总部授权。')
    if detail and binding['role']=='HQ':raise PermissionDenied('总部仅可查阅汇总。')
    return None

def account_choices(actor):
    b=workspace_binding(actor,('FRONT_DESK','MANAGER'))
    from accounts.policies import require_clinic
    require_clinic(actor,b['clinic'],roles=(b['role'],))
    return PaymentAccount.objects.filter(clinic_id=b['clinic'],is_active=True).order_by('code')

def lock_people(*ids):
    return {u.pk:u for u in UserAccount.objects.select_for_update().filter(pk__in=ids).order_by('pk')}

def lock_finance(actor):
    lock_finance_write(actor)

def preparer_current(user_id, clinic_id, role):
    return UserAccount.objects.filter(pk=user_id,is_active=True).exists() and RoleAssignment.objects.filter(
        user_id=user_id,role=role,scope_kind='CLINIC',clinic_id=clinic_id,is_active=True).exists()

def require_live_clinic(clinic):
    if not Clinic.objects.filter(pk=clinic,is_active=True).exists():raise PermissionDenied('诊所已停用。')
