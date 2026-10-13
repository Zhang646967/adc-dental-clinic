"""Business authorization: no is_staff/is_superuser bypass; one binding per grant."""
from django.core.exceptions import PermissionDenied
from django.db import connection
from accounts.models import UserAccount, RoleAssignment
from adc_core.rules import validate_role_scope

def bindings(user):
    from workspaces.context import raw_bindings
    qs = raw_bindings(user)
    ctx = getattr(user, '_adc_workspace', None)
    if ctx is not None:
        qs = qs.filter(role=ctx.role)
        if ctx.role in ('MANAGER', 'FRONT_DESK'):
            qs = qs.filter(clinic_id=ctx.clinic_id) if ctx.clinic_id else qs.none()
    return qs

def clinic_ids(user, roles=("FRONT_DESK",)):
    return bindings(user).filter(role__in=roles, scope_kind="CLINIC").values_list("clinic_id", flat=True)

def has_role(user, role):
    return bindings(user).filter(role=role).exists()

def require_clinic(user, clinic_id, roles=("FRONT_DESK",)):
    if not bindings(user).filter(role__in=roles, scope_kind="CLINIC", clinic_id=clinic_id).exists():
        raise PermissionDenied("没有该诊所的操作授权。")

def require_writable(user):
    from django.conf import settings
    if settings.ADC_READ_ONLY:
        raise PermissionDenied("当前实例仅供只读演示。")
    if not user.is_authenticated:
        raise PermissionDenied("请先登录。")
    # Services call this only inside atomic; an unlocked assertion would mislead.
    if not connection.in_atomic_block:
        raise RuntimeError("Write authorization must be checked inside a transaction")
    if not UserAccount.objects.select_for_update().filter(pk=user.pk, is_active=True).exists():
        raise PermissionDenied("账号已停用。")
    ctx = getattr(user, '_adc_workspace', None)
    if ctx is not None:
        from workspaces.models import WorkspaceContext
        from workspaces.context import valid_context
        latest = WorkspaceContext.objects.select_for_update().get(pk=ctx.pk, user_id=user.pk)
        if latest.revision != ctx.revision or latest.role != ctx.role or latest.clinic_id != ctx.clinic_id or not valid_context(user, latest):
            raise PermissionDenied("当前身份或诊所已经变化。请刷新后重新确认；没有执行本次操作。")


def lock_clinic_grant(user, clinic_id, roles=("FRONT_DESK",)):
    from workspaces.context import require_active
    require_active(user, roles, clinic_id)
    require_writable(user)
    grant = RoleAssignment.objects.select_for_update().filter(
        user_id=user.pk, is_active=True, role__in=roles, scope_kind="CLINIC", clinic_id=clinic_id
    ).first()
    if grant is None:
        raise PermissionDenied("没有该诊所的操作授权，或授权已经撤销。")
    return grant

def assign_role(*, operator, user, role, scope_kind, clinic=None):
    """Technical management command boundary; do not use ModelForm.save to assign roles."""
    from django.db import transaction
    from care.audit import emit
    from workspaces.context import require_active
    require_active(operator, ("SYSADMIN",))
    with transaction.atomic():
        # Canonical user locking order for concurrent grants/revocations.
        list(UserAccount.objects.select_for_update().filter(pk__in=[operator.pk, user.pk]).order_by("pk"))
        require_writable(operator)
        if not bindings(operator).filter(role="SYSADMIN", scope_kind="TECHNICAL").exists():
            raise PermissionDenied("需要技术管理授权。")
        target = UserAccount.objects.get(pk=user.pk)
        validate_role_scope(role, scope_kind, clinic.pk if clinic else None, target.dentist_id)
        obj, _ = RoleAssignment.objects.update_or_create(user=user, role=role, scope_kind=scope_kind,
                                                          clinic=clinic, defaults={"is_active": True})
        emit(operator, "ROLE_ASSIGNED", obj, summary={"role": role, "scope": scope_kind})
        return obj
