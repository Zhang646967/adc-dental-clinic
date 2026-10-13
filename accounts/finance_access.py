"""Shared account capability policy; has no dependency on care or finance models."""
from django.core.exceptions import PermissionDenied
from accounts.models import RoleAssignment
from accounts.policies import bindings, require_writable

def require_finance_read(actor):
    if not bindings(actor).filter(role__in=["FINANCE","HQ"],scope_kind="CHAIN").exists():
        raise PermissionDenied("需要全链财务或总部查询授权。")

def lock_finance_write(actor):
    from workspaces.context import require_active
    require_active(actor, ("FINANCE",))
    require_writable(actor)
    grant=RoleAssignment.objects.select_for_update().filter(user_id=actor.pk,is_active=True,role="FINANCE",scope_kind="CHAIN").first()
    if grant is None: raise PermissionDenied("需要当前有效的财务写入授权。")
    return grant
