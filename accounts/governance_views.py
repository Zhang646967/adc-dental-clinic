from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.debug import sensitive_post_parameters
from accounts.models import UserAccount
from accounts.policies import require_writable
from accounts import governance as svc
from accounts.governance_forms import CreateAccountForm, AccountActionForm
from adc_core.http_support import EXPECTED_ERRORS, add_error
from care.audit import emit
from workspaces.context import available_roles
from workspaces.rules import ROLES

ACTION_LABELS={'grant':'授予身份','revoke':'撤回身份','reset_password':'重置密码','disable':'停用账号',
               'security_suspend':'紧急安全封禁','enable':'启用账号','bind_patient':'绑定演示患者','disable_patient_access':'停用患者入口','identity_reviewer':'配置患者关系核验职责'}

@login_required
@require_GET
def listing(request):
    svc.require_technical(request.user)
    q=request.GET.get('q','').strip()[:150]
    qs=UserAccount.objects.all().order_by('username')
    if q:qs=qs.filter(username__icontains=q)
    page=Paginator(qs,30).get_page(request.GET.get('page'))
    rows=[{'id':u.pk,'username':u.username,'active':u.is_active,
           'roles':'、'.join(ROLES[r][0] for r in available_roles(u)) or '无有效身份'} for u in page]
    return render(request,'accounts/manage_list.html',{'rows':rows,'page':page,'q':q})

@login_required
@require_GET
def detail(request,pk):
    svc.require_technical(request.user)
    target=get_object_or_404(UserAccount,pk=pk)
    protected=False
    try:svc.protected_target(request.user,target)
    except PermissionDenied:protected=True
    return render(request,'accounts/manage_detail.html',{'target':target,'protected':protected,
        'roles':[ROLES[r][0] for r in available_roles(target)],'actions':list(ACTION_LABELS.items())})

@sensitive_post_parameters('password1','password2','operator_password')
@login_required
@require_http_methods(['GET','POST'])
def create(request):
    svc.require_technical(request.user)
    form=CreateAccountForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:
            u=svc.create_account(actor=request.user,username=d['username'],password=d['password1'],
                dentist_id=d['dentist'].pk if d['dentist'] else None,operator_password=d['operator_password'],reason=d['reason'])
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            messages.success(request,'账号已创建，尚未授予业务身份。请继续明确授权范围。')
            return redirect('account_manage_detail',pk=u.pk)
    return render(request,'accounts/manage_form.html',{'title':'创建演示账号','form':form,'description':'没有默认管理员权限。密码只由你在本地设置，不会显示在成功页。'})

@sensitive_post_parameters('password1','password2','operator_password')
@login_required
@require_http_methods(['GET','POST'])
def change(request,pk,action):
    svc.require_technical(request.user)
    if action not in ACTION_LABELS:raise PermissionDenied
    target=get_object_or_404(UserAccount,pk=pk);svc.protected_target(request.user,target)
    form=AccountActionForm(request.POST or None,action=action,target=target,token=svc.target_token(request.user,target))
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:
            svc.change_account(actor=request.user,target_id=target.pk,token=d['target_token'],action=action,
                operator_password=d['operator_password'],reason=d['reason'],role=d.get('role'),
                clinic_id=d['clinic'].pk if d.get('clinic') else None,
                grant_id=d['grant'].pk if d.get('grant') else None,
                patient_no=d.get('patient_no'),new_password=d.get('password1'),reviewer_enabled=d.get('reviewer_enabled',False))
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            if action == 'security_suspend':
                messages.success(request,'账号已安全封禁，原密码及旧会话失效。已有预约和历史保持不变；恢复需先重置密码再启用。')
            else:
                messages.success(request,'已保存账号变更。该账号旧工作上下文已失效，需要重新进入授权工作台。')
            return redirect('account_manage_detail',pk=target.pk)
    return render(request,'accounts/manage_form.html',{'title':f'{ACTION_LABELS[action]}：{target.username}',
        'description':('用于账号疑似泄露等安全事件：立即停止后续访问，不受未闭合业务阻挡，不自动转移或取消预约。恢复访问须先重置密码，再单独启用。'
                       if action=='security_suspend' else '变更需要你的技术管理密码、有效工作上下文及目标账号状态一致；不会删除患者或历史业务。'), 'form':form})

@sensitive_post_parameters('old_password','new_password1','new_password2')
@login_required
@require_http_methods(['GET','POST'])
def change_own_password(request):
    form=PasswordChangeForm(request.user,request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                require_writable(request.user)
                fresh=UserAccount.objects.select_for_update().get(pk=request.user.pk,is_active=True)
                if not fresh.check_password(form.cleaned_data['old_password']):
                    raise ValidationError('密码已变化，请重新登录后重试。')
                form.user=fresh;form.save()
                svc.invalidate_contexts(fresh)
                emit(fresh,'OWN_PASSWORD_CHANGED',fresh,summary={'reauthentication_required':True})
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            logout(request)
            messages.success(request,'密码已更改，请使用新密码重新登录。')
            return redirect('login')
    return render(request,'accounts/manage_form.html',{'title':'修改我的密码','form':form,
        'description':'输入原密码与两次新密码。保存成功后重新登录；不会改变你的角色或患者资料。',
        'self_password':True,'base_template':'portal/base.html' if request.workspace.role=='PATIENT' else 'base.html'})
