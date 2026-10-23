from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from accounts.models import UserAccount
from registry.models import Clinic
from accounts.policies import has_role
from workspaces.worklists import workspace_worklist
from workspaces.context import (ensure_context, available_roles, authorized_clinics,
    valid_context, attach, check_token, SESSION_KEY)
from workspaces.models import WorkspaceContext
from workspaces.rules import ROLES, CLINIC_ROLES

class WorkspaceLoginView(LoginView):
    def get_success_url(self):
        return reverse('select_role')

    def form_valid(self, form):
        # Django performs authentication/session rotation, then our scoped activation.
        super().form_valid(form)
        from workspaces.activation import begin_login_workspace
        return redirect(begin_login_workspace(self.request))

@login_required
@require_GET
def select_role(request):
    ctx = ensure_context(request)
    current_roles = available_roles(request.user)
    if len(current_roles) == 1 and valid_context(request.user, ctx):
        return redirect(ROLES[current_roles[0]][1])
    roles=[{'code':r,'label':ROLES[r][0]} for r in current_roles]
    return render(request,'workspaces/select_role.html',{'roles':roles})

@login_required
@require_POST
@transaction.atomic
def activate_role(request):
    from workspaces.activation import select_authorized_role
    route = select_authorized_role(request, request.POST.get('role'), request.POST.get('workspace_token', ''))
    from portal.booking_intent import destination_after_activation
    return redirect(destination_after_activation(request) or route)

@login_required
@require_GET
def select_clinic(request):
    ctx=request.workspace
    if ctx.role not in CLINIC_ROLES:raise PermissionDenied
    return render(request,'workspaces/clinics.html',{'clinics':authorized_clinics(request.user,ctx.role)})

@login_required
@require_POST
@transaction.atomic
def activate_clinic(request):
    UserAccount.objects.select_for_update().get(pk=request.user.pk)
    ctx=WorkspaceContext.objects.select_for_update().get(pk=request.workspace.pk,user=request.user)
    if not check_token(ctx,request.POST.get('workspace_token','')):raise PermissionDenied('诊所选择页已过期。')
    if not valid_context(request.user,ctx) or ctx.role not in CLINIC_ROLES:raise PermissionDenied
    try:clinic=authorized_clinics(request.user,ctx.role).get(pk=int(request.POST.get('clinic','0')))
    except (ValueError,TypeError,Clinic.DoesNotExist):raise PermissionDenied('没有目标诊所授权。')
    ctx.clinic=clinic;ctx.revision+=1;ctx.save();attach(request,ctx)
    return redirect(ROLES[ctx.role][1])

@login_required
@require_GET
def home(request):
    ctx=request.workspace
    if not valid_context(request.user,ctx):return redirect('select_role')
    if ctx.role=='PATIENT':return redirect('portal_home')
    if ctx.role in CLINIC_ROLES and ctx.clinic_id is None:return select_clinic(request)
    data={'worklist':workspace_worklist(request.user)}
    return render(request,{'DENTIST':'workspaces/doctor.html','FRONT_DESK':'workspaces/frontdesk.html',
        'MANAGER':'workspaces/manager.html','HQ':'workspaces/hq.html','FINANCE':'workspaces/finance.html',
        'SYSADMIN':'workspaces/technical.html'}[ctx.role],data)
