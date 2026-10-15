"""Fifteen-minute, workspace-bound proposals. Commands reauthorize under locks."""
import uuid
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.views.decorators.debug import sensitive_variables
from workspaces.context import require_active, valid_context
from workspaces.models import WorkspaceContext
from adc_core.rules import RuleError

def workspace_binding(actor, roles):
    ctx = getattr(actor, '_adc_workspace', None)
    if ctx is None or ctx.role not in roles:
        raise PermissionDenied('请进入已授权的当前工作身份。')
    require_active(actor, roles, ctx.clinic_id)
    if not valid_context(actor, ctx) or not WorkspaceContext.objects.filter(
            pk=ctx.pk, user_id=actor.pk, role=ctx.role, clinic_id=ctx.clinic_id, revision=ctx.revision).exists():
        raise PermissionDenied('工作身份或诊所已变化，请重新打开页面。')
    return dict(user=actor.pk, workspace=str(ctx.pk), role=ctx.role,
                clinic=ctx.clinic_id, revision=ctx.revision)

@sensitive_variables()
def proposal(actor, contract, roles, data):
    return signing.dumps(dict(contract=contract, binding=workspace_binding(actor, roles),
        operation=str(uuid.uuid4()), data=data), salt=contract, compress=True)

@sensitive_variables()
def read_proposal(actor, contract, roles, token):
    try:
        if type(token) is not str or not 1 <= len(token) <= 16384: raise ValueError
        payload = signing.loads(token, salt=contract, max_age=900)
        if type(payload) is not dict or set(payload) != {'contract','binding','operation','data'}:
            raise ValueError
        if payload['contract'] != contract or type(payload['data']) is not dict:
            raise ValueError
        if payload['binding'] != workspace_binding(actor, roles):
            raise RuleError('当前身份或诊所已变化，请重新预览。')
        if type(payload['operation']) is not str:raise ValueError
        uuid.UUID(payload['operation'])
        return payload
    except (signing.BadSignature, ValueError, TypeError, KeyError) as exc:
        raise RuleError('确认内容无效或已过期，请重新预览。') from exc
