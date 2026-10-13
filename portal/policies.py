from django.core.exceptions import PermissionDenied
from portal.models import PatientAccess

def patient_access(user, *, lock=False):
    from workspaces.context import require_active
    require_active(user, ("PATIENT",))
    if not user.is_authenticated:
        raise PermissionDenied("请先登录患者端。")
    qs = PatientAccess.objects.filter(user_id=user.pk, user__is_active=True, is_active=True, patient__is_active=True)
    if lock:
        # Do not join nullable rows under FOR UPDATE.
        qs = qs.select_for_update(of=("self",))
    access = qs.first()
    if access is None:
        raise PermissionDenied("当前账号没有有效患者端授权。患者编号不能用作登录凭据。")
    return access
