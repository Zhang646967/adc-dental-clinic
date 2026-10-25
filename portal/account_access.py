"""Own-account channel access without prematurely granting PATIENT authority."""
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from accounts.external_identity import _account_actor
from accounts.external_models import ExternalIdentity,AccountPhone
from portal.policies import has_patient_access,has_patient_account
from workspaces.context import existing_context,attach,check_token,token_for


def can_account_login(user):
    return has_patient_account(user)


def account_context(request,*,unsafe=False):
    if not request.user.is_authenticated:raise PermissionDenied('请先登录患者渠道账号。')
    ctx=existing_context(request)
    if ctx is None or ctx.login_channel!='PATIENT' or ctx.role not in ('','PATIENT'):raise PermissionDenied('请从患者通道办理账号资料。')
    attach(request,ctx);_account_actor(request.user)
    if unsafe:
        token=request.headers.get('X-ADC-Account','') or request.POST.get('account_token','')
        if not check_token(ctx,token):raise PermissionDenied('账号办理页面已过期，请刷新后继续。')
    return ctx


def account_data(request):
    ctx=account_context(request)
    phone=AccountPhone.objects.filter(user=request.user).first()
    from portal.models import PatientAccess
    own=PatientAccess.objects.filter(user=request.user).values('is_active','patient__is_active').first()
    return dict(account_authenticated=True,account_token=token_for(ctx),account_name=request.user.username,workspace_id=str(ctx.pk),subject_revision=ctx.revision,
        enrollment_required=not has_patient_access(request.user),password_ready=request.user.has_usable_password(),
        can_request_enrollment=own is None or (not own['is_active'] and own['patient__is_active']),self_binding_needs_review=own is not None and not (own['is_active'] and own['patient__is_active']),
        phone=dict(number=phone.phone,source=phone.source,verified_at=phone.verified_at.isoformat(),revision=phone.revision) if phone else None,
        identities=list(ExternalIdentity.objects.filter(user=request.user).order_by('pk').values('id','provider','revision')))


def remember_pending_service(request,service):
    from scheduling.service_content import positive_id
    from portal.service_catalogue import public_profiles
    pk=positive_id(str(service or ''))
    if pk and any(p.service_id==pk and p.category!='CHILDREN' for p in public_profiles()):
        request.session['adc_enrollment_service']=dict(user=request.user.pk,service=pk,expires=timezone.now().timestamp()+600)


def resume_service(request):
    from portal.booking_intent import remember_service,destination_after_activation
    data=request.session.pop('adc_enrollment_service',None)
    if data and data['user']==request.user.pk and data['expires']>timezone.now().timestamp():remember_service(request,data['service'])
    return destination_after_activation(request)
