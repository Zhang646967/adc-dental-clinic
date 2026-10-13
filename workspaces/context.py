"""Public context contract. Database grants are re-read, never inferred from a token."""
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from accounts.models import RoleAssignment, UserAccount
from portal.models import PatientAccess
from workspaces.models import WorkspaceContext
from workspaces.rules import ROLES, CLINIC_ROLES, matches_context

SESSION_KEY = 'adc_workspace_id'
SALT = 'adc.workspace.v07'

def raw_bindings(user):
    if not user.is_authenticated:
        return RoleAssignment.objects.none()
    return RoleAssignment.objects.filter(user_id=user.pk, user__is_active=True, is_active=True)

def available_roles(user):
    if not user.is_authenticated or not UserAccount.objects.filter(pk=user.pk,is_active=True).exists():
        return []
    roles=set(raw_bindings(user).values_list('role',flat=True))
    for clinic_role in CLINIC_ROLES:
        if not authorized_clinics(user, clinic_role).exists():
            roles.discard(clinic_role)
    if not UserAccount.objects.filter(pk=user.pk,dentist__is_active=True).exists():
        roles.discard('DENTIST')
    if PatientAccess.objects.filter(user_id=user.pk,is_active=True,patient__is_active=True).exists():
        roles.add('PATIENT')
    return [r for r in ROLES if r in roles]

def authorized_clinics(user, role):
    from registry.models import Clinic
    if role not in CLINIC_ROLES:
        return Clinic.objects.none()
    return Clinic.objects.filter(is_active=True,pk__in=raw_bindings(user).filter(
        role=role,scope_kind='CLINIC').values('clinic_id')).order_by('clinic_code')

def ensure_context(request):
    key=request.session.get(SESSION_KEY)
    try:
        ctx=WorkspaceContext.objects.filter(pk=key,user_id=request.user.pk).first() if key else None
    except (ValueError,TypeError,ValidationError,signing.BadSignature):
        ctx=None
    if ctx is None:
        ctx=WorkspaceContext.objects.create(user=request.user)
        request.session[SESSION_KEY]=str(ctx.pk)
    return ctx

def valid_context(user,ctx):
    if ctx.user_id!=user.pk or ctx.role not in available_roles(user):
        return False
    if ctx.clinic_id is not None:
        return authorized_clinics(user,ctx.role).filter(pk=ctx.clinic_id).exists()
    return True

def attach(request,ctx):
    request.workspace=ctx
    # Only this middleware attaches the narrowing context to request.user.
    request.user._adc_workspace=ctx

def token_for(ctx):
    return signing.dumps({'key':str(ctx.pk),'uid':ctx.user_id,'role':ctx.role,
        'clinic':ctx.clinic_id,'revision':ctx.revision},salt=SALT)

def check_token(ctx,token):
    try:
        payload=signing.loads(token,salt=SALT,max_age=8*3600)
    except (signing.BadSignature,TypeError,ValueError):
        return False
    return matches_context(payload,ctx.pk,ctx.user_id,ctx.role,ctx.clinic_id,ctx.revision)

def require_active(user, roles, clinic_id=None):
    """Narrow an HTTP actor. Trusted management/tests without context still need RBAC."""
    ctx=getattr(user,'_adc_workspace',None)
    if ctx is not None:
        if not valid_context(user,ctx) or ctx.role not in roles:
            raise PermissionDenied('请切换到有权限的工作身份后再操作。')
        if ctx.role in CLINIC_ROLES and (ctx.clinic_id is None or (clinic_id is not None and ctx.clinic_id!=clinic_id)):
            raise PermissionDenied('请先在工作台选择正确的诊所。')
