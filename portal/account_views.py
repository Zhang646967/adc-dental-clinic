from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login,update_session_auth_hash
from django.contrib.auth.forms import AuthenticationForm
from django.core.paginator import Paginator
from django.shortcuts import render,redirect,get_object_or_404
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods,require_POST
from accounts.external_identity import exchange_login,verify_phone,unlink_identity,set_login_password
from adc_core.http_support import EXPECTED_ERRORS,add_error
from patients.services import PATIENT_FIELDS
from portal import account_forms as forms,enrollment
from portal.account_access import account_context,account_data,remember_pending_service,resume_service
from portal.policies import has_patient_access
from workspaces.activation import begin_login_workspace
from portal.enrollment_display import detail_rows,ACTION_LABELS


@sensitive_post_parameters('code','password')
@require_http_methods(['GET','POST'])
def local_login(request):
    if not (settings.ADC_CLINICAL_SYNTHETIC and settings.ADC_PATIENT_IDENTITY_PROVIDER=='local'):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('本环境未启用本地授权替身，请使用已分配账号。')
    form=forms.LocalLoginForm(request.POST or None,initial={'booking_service':request.GET.get('service')})
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data;existing=None
        if d['username']:
            original=AuthenticationForm(request,data={'username':d['username'],'password':d['password']})
            if not original.is_valid():form.add_error(None,'原账号或密码不正确，或账号已停用。')
            else:existing=original.get_user()
        if not form.errors:
            try:user=exchange_login(code=d['code'],existing_user=existing,existing_password=d['password'])
            except EXPECTED_ERRORS as exc:add_error(form,exc)
            else:
                login(request,user,backend='django.contrib.auth.backends.ModelBackend');request.session.set_expiry(3600)
                route=begin_login_workspace(request,channel='PATIENT');remember_pending_service(request,d['booking_service'])
                if has_patient_access(user):return redirect(resume_service(request) or route)
                return redirect('patient_account')
    return render(request,'portal/account_login.html',{'form':form})


@sensitive_post_parameters('code','password','new_password','repeat_password')
@require_http_methods(['GET','POST'])
def account(request):
    account_context(request,unsafe=request.method=='POST')
    phone_form=forms.PhoneCodeForm();password_form=forms.PasswordSetupForm();unlink_form=None
    if request.method=='POST':
        action=request.POST.get('action')
        form=forms.PhoneCodeForm(request.POST) if action=='phone' else forms.UnlinkForm(request.POST) if action=='unlink' else forms.PasswordSetupForm(request.POST) if action=='password_setup' else None
        if form and form.is_valid():
            try:
                d=form.cleaned_data
                if action=='phone':verify_phone(actor=request.user,code=d['code'],confirmed=d['confirmed'])
                elif action=='unlink':unlink_identity(actor=request.user,identity_id=d['identity'],expected_revision=d['revision'],password=d['password'],confirmed=d['confirmed'])
                else:
                    user=set_login_password(actor=request.user,code=d['code'],new_password=d['new_password'],confirmed=d['confirmed'])
                    update_session_auth_hash(request,user)
            except EXPECTED_ERRORS as exc:add_error(form,exc)
            else:messages.success(request,'账号资料已更新，原患者档案及预约保持。');return redirect('patient_account')
        if action=='phone':phone_form=form
        elif action=='password_setup':password_form=form
        else:unlink_form=form
    data=account_data(request)
    return render(request,'portal/account.html',dict(data,phone_form=phone_form,password_form=password_form,unlink_form=unlink_form,cases=enrollment.own_cases(request.user)[:10],can_activate=has_patient_access(request.user)))


@require_POST
def activate(request):
    account_context(request,unsafe=True)
    if request.POST.get('confirmed')!='on' or not has_patient_access(request.user):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('请先完成本人档案核验，并明确进入患者服务。')
    route=begin_login_workspace(request,channel='PATIENT')
    return redirect(resume_service(request) or route)


@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def enrollment_form(request,pk=None):
    account_context(request,unsafe=request.method=='POST')
    row=get_object_or_404(enrollment.own_cases(request.user),pk=pk) if pk else None
    own=account_data(request);restore_only=own['self_binding_needs_review']
    initial=dict(row.details,clinic=row.clinic_id,kind=row.kind) if row else {'kind':'EXISTING' if restore_only else 'NEW'}
    form=forms.EnrollmentForm(request.POST or None,initial=initial,restore_only=restore_only)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data;details={k:d[k].isoformat() if k=='date_of_birth' else d[k] for k in PATIENT_FIELDS|{'patient_reference'}}
        try:p=enrollment.prepare_submit(actor=request.user,clinic_id=d['clinic'].pk,kind=d['kind'],details=details,case_id=row.pk if row else None)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return render(request,'portal/enrollment_preview.html',dict(preview=p,form=forms.ConfirmForm(initial={'proposal_token':p['proposal_token']}),account_token=account_data(request)['account_token']))
    return render(request,'portal/enrollment_form.html',dict(form=form,case=row,account_token=account_data(request)['account_token']))


@require_POST
def enrollment_confirm(request):
    account_context(request,unsafe=True);form=forms.ConfirmForm(request.POST)
    if form.is_valid():
        try:enrollment.confirm_submit(actor=request.user,token=form.cleaned_data['proposal_token'],confirmed=form.cleaned_data['confirmed'])
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:messages.success(request,'申请已送至门店核验，尚未创建预约。');return redirect('patient_account')
    return render(request,'portal/enrollment_preview.html',dict(form=form,failed=True,account_token=account_data(request)['account_token']))


@require_POST
def enrollment_withdraw(request,pk):
    account_context(request,unsafe=True)
    try:revision=int(request.POST.get('revision',''))
    except ValueError:revision=-1
    if request.POST.get('confirmed')=='on':
        try:enrollment.withdraw(actor=request.user,case_id=pk,expected_revision=revision)
        except EXPECTED_ERRORS as exc:messages.error(request,str(exc))
        else:messages.success(request,'已撤回本次申请，原资料及其他业务保留。')
    return redirect('patient_account')


@require_http_methods(['GET'])
def review_list(request):
    rows=enrollment.clinic_cases(request.user)
    state=request.GET.get('state','PENDING')
    if state in dict(enrollment.PatientEnrollment.STATES):rows=rows.filter(state=state)
    return render(request,'portal/enrollment_queue.html',{'page':Paginator(rows,20).get_page(request.GET.get('page')),'state':state,'states':enrollment.PatientEnrollment.STATES})


@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def review_detail(request,pk):
    row=get_object_or_404(enrollment.clinic_cases(request.user),pk=pk);form=forms.EnrollmentReviewForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:token=enrollment.prepare_review(actor=request.user,case_id=pk,**form.cleaned_data)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            from adc_core.proposals import read_proposal
            review_data=read_proposal(request.user,enrollment.REVIEW,('FRONT_DESK',),token)['data']
            decision=dict(form.cleaned_data,action_label=ACTION_LABELS[form.cleaned_data['action']],basis_label=dict(enrollment.BASES)[form.cleaned_data['basis']])
            return render(request,'portal/enrollment_review_preview.html',dict(case=row,decision=decision,review_data=review_data,form=forms.ConfirmForm(initial={'proposal_token':token})))
    events=[dict(created_at=e.created_at,action=ACTION_LABELS[e.action],reference=e.reference) for e in row.events.order_by('pk')]
    return render(request,'portal/enrollment_review.html',{'case':row,'form':form,'events':events,'detail_rows':detail_rows(row.details)})


@require_POST
def review_confirm(request):
    form=forms.ConfirmForm(request.POST)
    if form.is_valid():
        try:row,_=enrollment.confirm_review(actor=request.user,token=form.cleaned_data['proposal_token'],confirmed=form.cleaned_data['confirmed'])
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:messages.success(request,'核验决定已保存。');return redirect('patient_enrollment_detail',pk=row.pk)
    return render(request,'portal/enrollment_review_preview.html',dict(form=form,failed=True))
