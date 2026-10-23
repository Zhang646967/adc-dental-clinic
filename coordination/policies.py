from django.core.exceptions import PermissionDenied
from accounts.policies import bindings,clinic_ids,lock_clinic_grant
from workspaces.context import require_active
from portal.policies import patient_access
from coordination.models import WaitRequest,WaitOffer

def entries_for(user):
    ctx=getattr(user,'_adc_workspace',None)
    if ctx and ctx.role=='PATIENT':return patient_access(user).scope(WaitRequest.objects.all())
    roles=bindings(user).filter(role__in=['FRONT_DESK','MANAGER'])
    if roles.exists():return WaitRequest.objects.filter(clinic_id__in=clinic_ids(user,('FRONT_DESK','MANAGER')))
    # Direct service tests use the existing patient binding, but never allow arbitrary ids.
    if ctx is None:
        try:return patient_access(user).scope(WaitRequest.objects.all())
        except PermissionDenied:pass
    raise PermissionDenied('当前身份没有候补权限。')

def require_owner_or_front(actor,entry,*,lock=False,authority=None):
    ctx=getattr(actor,'_adc_workspace',None)
    if ctx and ctx.role=='PATIENT':
        access=patient_access(actor,lock=lock)
        if access.patient_id!=entry.patient_id:raise PermissionDenied
        access.require_clinic(entry.clinic_id)
        if lock:
            from portal.policies import check_action_authority
            check_action_authority(access,authority)
    elif bindings(actor).filter(role='FRONT_DESK',scope_kind='CLINIC',clinic_id=entry.clinic_id).exists():
        require_active(actor,('FRONT_DESK',),entry.clinic_id)
        if lock:lock_clinic_grant(actor,entry.clinic_id)
    elif ctx is None and patient_access(actor,lock=lock).patient_id==entry.patient_id:pass
    else:raise PermissionDenied('只有本人或该店前台可确认候补。')
