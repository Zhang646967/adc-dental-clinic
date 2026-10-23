"""Shared server-side activation. Automatic activation happens only after login POST."""
from django.db import transaction
from django.core.exceptions import PermissionDenied
from accounts.models import UserAccount
from workspaces.context import (SESSION_KEY, available_roles, ensure_context, attach, check_token)
from workspaces.models import WorkspaceContext
from workspaces.rules import ROLES
from workspaces.selection import sole_role


def apply_role(request, ctx, role):
    """Caller must hold user/context locks; grant check never trusts a request role."""
    if role not in available_roles(request.user):
        raise PermissionDenied('该身份已失效；请重新登录或核对授权。')
    ctx.role = role
    ctx.clinic = None
    ctx.revision += 1
    ctx.save(update_fields=['role', 'clinic', 'revision', 'updated_at'])
    request.session.pop('adc_guide', None)
    attach(request, ctx)
    return ROLES[role][1]


@transaction.atomic
def begin_login_workspace(request):
    if not UserAccount.objects.select_for_update().filter(pk=request.user.pk, is_active=True).exists():
        raise PermissionDenied('账号已停用，请重新登录或联系管理人员。')
    # New authenticated session context; old browser sessions retain their own contexts.
    request.session.pop(SESSION_KEY, None)
    request.session.pop('adc_guide', None)
    request.session.pop('adc_booking_intent', None)
    ctx = ensure_context(request)
    attach(request, ctx)
    role = sole_role(available_roles(request.user))
    if role is None:
        return 'select_role'
    return apply_role(request, ctx, role)


@transaction.atomic
def select_authorized_role(request, role, token):
    if not UserAccount.objects.select_for_update().filter(pk=request.user.pk, is_active=True).exists():
        raise PermissionDenied('账号已停用，请重新登录或联系管理人员。')
    ctx = WorkspaceContext.objects.select_for_update().get(pk=request.workspace.pk, user=request.user)
    if not check_token(ctx, token):
        raise PermissionDenied('身份选择页已过期，请刷新。')
    return apply_role(request, ctx, role)
