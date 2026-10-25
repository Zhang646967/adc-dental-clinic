"""Own-account endpoints work before PATIENT activation; CSRF remains mandatory."""
from django.contrib.auth import login,update_session_auth_hash
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.views.decorators.debug import sensitive_post_parameters
from accounts.external_identity import exchange_login,verify_phone,unlink_identity,set_login_password
from patients.services import PATIENT_FIELDS
from portal import account_forms as forms,enrollment
from portal.account_access import account_context,account_data
from portal.mini_api import endpoint,result,session_data,validated
from portal.policies import has_patient_access
from workspaces.activation import begin_login_workspace


def case_data(row):
    return dict(id=row.pk,clinic=row.clinic_id,clinic_name=row.clinic.public_contact['name'],kind=row.kind,kind_label=row.get_kind_display(),state=row.state,
        state_label=row.get_state_display(),details=row.details,patient_message=row.patient_message,revision=row.revision,
        created_at=row.created_at.isoformat(),can_edit=row.state=='NEED_INFO',can_withdraw=row.state in ('PENDING','NEED_INFO'))


@sensitive_post_parameters('code','password')
@endpoint(('POST',),public=True)
@transaction.atomic
def local_login(request):
    d=validated(forms.LocalLoginForm(request.POST));old=None
    if d['username']:
        form=AuthenticationForm(request,data={'username':d['username'],'password':d['password']})
        if not form.is_valid():return result(request,status=401,code='LOGIN_FAILED',message='原账号或密码不正确，或账号已停用。')
        old=form.get_user()
    user=exchange_login(code=d['code'],existing_user=old,existing_password=d['password'])
    login(request,user,backend='django.contrib.auth.backends.ModelBackend');request.session.set_expiry(3600)
    begin_login_workspace(request,channel='PATIENT')
    return result(request,session_data(request))


@endpoint(public=True)
def profile(request):
    return result(request,dict(account_data(request),cases=[case_data(row) for row in enrollment.own_cases(request.user)[:20]]))


@sensitive_post_parameters('code')
@endpoint(('POST',),public=True)
def phone(request):
    account_context(request,unsafe=True);d=validated(forms.PhoneCodeForm(request.POST))
    verify_phone(actor=request.user,code=d['code'],confirmed=d['confirmed'])
    return result(request,account_data(request))


@sensitive_post_parameters('password')
@endpoint(('POST',),public=True)
def unlink(request):
    account_context(request,unsafe=True);d=validated(forms.UnlinkForm(request.POST))
    unlink_identity(actor=request.user,identity_id=d['identity'],expected_revision=d['revision'],password=d['password'],confirmed=d['confirmed'])
    return result(request,account_data(request))


@sensitive_post_parameters('code','new_password','repeat_password')
@endpoint(('POST',),public=True)
def password_setup(request):
    account_context(request,unsafe=True);d=validated(forms.PasswordSetupForm(request.POST))
    user=set_login_password(actor=request.user,code=d['code'],new_password=d['new_password'],confirmed=d['confirmed'])
    update_session_auth_hash(request,user)
    request.user=user
    return result(request,session_data(request))


@endpoint(('POST',),public=True)
def activate(request):
    account_context(request,unsafe=True)
    if request.POST.get('confirmed')!='on' or not has_patient_access(request.user):raise PermissionDenied('请先完成本人档案核验，并明确进入患者服务。')
    begin_login_workspace(request,channel='PATIENT')
    return result(request,session_data(request))


@sensitive_post_parameters()
@endpoint(('POST',),public=True)
def submit_preview(request):
    account_context(request,unsafe=True);d=validated(forms.EnrollmentForm(request.POST,restore_only=account_data(request)['self_binding_needs_review']))
    details={k:d[k].isoformat() if k=='date_of_birth' else d[k] for k in PATIENT_FIELDS|{'patient_reference'}}
    from scheduling.service_content import positive_id
    raw=request.POST.get('case','');pk=positive_id(raw) if raw else None
    if raw and pk is None:
        from adc_core.rules import RuleError
        raise RuleError('请从当前待补充申请继续办理。')
    p=enrollment.prepare_submit(actor=request.user,clinic_id=d['clinic'].pk,kind=d['kind'],details=details,case_id=pk)
    return result(request,p)


@endpoint(('POST',),public=True)
def submit_confirm(request):
    account_context(request,unsafe=True);d=validated(forms.ConfirmForm(request.POST))
    row,repeated=enrollment.confirm_submit(actor=request.user,token=d['proposal_token'],confirmed=d['confirmed'])
    return result(request,dict(case=case_data(row),repeated=repeated))


@endpoint(('POST',),public=True)
def withdraw(request,pk):
    account_context(request,unsafe=True)
    from adc_core.rules import RuleError
    if request.POST.get('confirmed')!='on':raise RuleError('请明确确认撤回本次申请。')
    try:revision=int(request.POST.get('revision',''))
    except ValueError:raise RuleError('申请版本无效，请刷新。') from None
    row=enrollment.withdraw(actor=request.user,case_id=pk,expected_revision=revision)
    return result(request,case_data(row))
