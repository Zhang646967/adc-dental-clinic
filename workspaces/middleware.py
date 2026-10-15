"""HTTP workspace boundary: role, scope, stale tabs and typed route allowlists."""
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import resolve, Resolver404
from accounts.models import UserAccount
from workspaces.context import (ensure_context, attach, valid_context, check_token, SESSION_KEY)
from workspaces.models import WorkspaceContext
from workspaces.rules import CLINIC_ROLES

PUBLIC={'login','portal_login','logout','health'}
ROLE_FREE={'select_role','activate_role','own_password_change'}
ROLE_HOME={'manager_home','frontdesk_home','select_clinic','activate_clinic'}
ALL={'PATIENT','FRONT_DESK','DENTIST','MANAGER','HQ','FINANCE','SYSADMIN'}
ROUTES={
 'equipment_cost_queue':{'MANAGER','FINANCE','HQ'},'equipment_cost_history':{'MANAGER','FINANCE','HQ'},
 'equipment_cost_request':{'MANAGER'},'equipment_cost_review':{'FINANCE'},
 'equipment_expenses':{'MANAGER','FINANCE','HQ'},'equipment_schedule':{'MANAGER'},
 'equipment_list':{'MANAGER','FINANCE','HQ'},'equipment_detail':{'MANAGER','FINANCE','HQ'},
 'equipment_register':{'MANAGER'},'equipment_change':{'MANAGER'},
 'cash_list':{'FRONT_DESK','MANAGER','FINANCE','HQ'},'cash_detail':{'FRONT_DESK','MANAGER','FINANCE'},
 'cash_invoice_request':{'FRONT_DESK'},'cash_equipment_request':{'MANAGER'},
 'cash_reversal':{'FRONT_DESK','MANAGER'},'cash_review':{'FINANCE'},
 'cash_receivables':{'FRONT_DESK','FINANCE','HQ'},
 'notification_inbox':{'MANAGER','FRONT_DESK'},
 'notification_read':{'MANAGER','FRONT_DESK'},
 'notification_status':{'MANAGER'},
 'notification_retry':{'MANAGER'},
 'coordination_task_list':{'MANAGER','FRONT_DESK'},
 'coordination_task_detail':{'MANAGER','FRONT_DESK'},
 'coordination_task_open':{'MANAGER','FRONT_DESK'},
 'coordination_task_action':{'MANAGER','FRONT_DESK'},
 'coordination_task_confirm_new':{'MANAGER','FRONT_DESK'},
 'coordination_task_confirm':{'MANAGER','FRONT_DESK'},
 'intake_change':{'MANAGER'},'intake_confirm':{'MANAGER'},
 'front_coordination_list':{'FRONT_DESK'},'front_coordination_detail':{'FRONT_DESK'},
 'availability_list':{'MANAGER'},'availability_detail':{'MANAGER'},
 'availability_change':{'MANAGER'},'availability_confirm':{'MANAGER'},
 'directory_home':{'SYSADMIN'},'directory_list':{'SYSADMIN'},'directory_detail':{'SYSADMIN'},
 'directory_create':{'SYSADMIN'},'directory_confirm':{'SYSADMIN'},
 'directory_attach':{'SYSADMIN'},'directory_withdraw_preview':{'SYSADMIN'},
 'patient_contact_edit':{'FRONT_DESK'},'patient_contact_confirm':{'FRONT_DESK'},
 'guide_result_wait':{'PATIENT','FRONT_DESK'},
 'catalogue_list':{'FINANCE','HQ'},'catalogue_create':{'FINANCE'},'catalogue_price':{'FINANCE'},
 'account_manage_list':{'SYSADMIN'},'account_manage_detail':{'SYSADMIN'},
 'account_manage_create':{'SYSADMIN'},'account_manage_change':{'SYSADMIN'},
 'dashboard':ALL,'doctor_home':{'DENTIST'},'frontdesk_home':{'FRONT_DESK'},
 'manager_home':{'MANAGER'},'hq_home':{'HQ'},'finance_home':{'FINANCE'},'technical_home':{'SYSADMIN'},
 'select_clinic':{'MANAGER','FRONT_DESK'},'activate_clinic':{'MANAGER','FRONT_DESK'},
 'patients':{'FRONT_DESK','DENTIST'},'patient_create':{'FRONT_DESK'},'patient_lookup':{'FRONT_DESK'},
 'patient_detail':{'FRONT_DESK','DENTIST'},'visits':{'FRONT_DESK','DENTIST','MANAGER','HQ'},
 'visit_detail':{'FRONT_DESK','DENTIST'},'visit_create':{'FRONT_DESK'},'visit_reschedule':{'FRONT_DESK'},
 'slot_create':{'MANAGER'},'care_workspace':{'DENTIST'},'care_complete':{'DENTIST'},
 'invoice_detail':{'FRONT_DESK','DENTIST','FINANCE'},'corrections':{'DENTIST','FINANCE'},
 'correction_create':{'DENTIST'},'correction_detail':{'DENTIST','FINANCE'},
 'finance_quarters':{'FINANCE','HQ'},'quarter_detail':{'FINANCE','HQ'},'quarter_cost':{'FINANCE'},'quarter_export':{'FINANCE','HQ'},
 'operations_dashboard':{'MANAGER','HQ'},'staff_assistant':{'FRONT_DESK','DENTIST','MANAGER','HQ','FINANCE'},
 'guide_index':ALL,'guide_task':ALL,
 'waitlist':{'PATIENT','FRONT_DESK','MANAGER'},'waitlist_join':{'PATIENT','FRONT_DESK'},
 'waitlist_withdraw':{'PATIENT','FRONT_DESK'},'wait_offer':{'PATIENT','FRONT_DESK'},
 'schedule_plans':{'MANAGER'},'schedule_plan':{'MANAGER'},'expire_offers':{'MANAGER','FRONT_DESK'},
}

def route_roles(name,kwargs):
    if name=='assistant_api':
        return {'PATIENT'} if kwargs.get('audience')=='patient' else {'FRONT_DESK','DENTIST','MANAGER','HQ','FINANCE'}
    if name and name.startswith('portal_'): return {'PATIENT'}
    return ROUTES.get(name,set())

class WorkspaceMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def error(self,request,text,status=403):
        if request.path.startswith('/api/'):
            return JsonResponse({'error':text},status=status)
        return render(request,'workspaces/error.html',{'problem':text},status=status)
    def __call__(self,request):
        try: match=resolve(request.path_info)
        except Resolver404:return self.get_response(request)
        name=match.url_name
        if name in PUBLIC or not request.user.is_authenticated:
            return self.get_response(request)
        ctx=ensure_context(request);attach(request,ctx)
        unsafe=request.method not in ('GET','HEAD','OPTIONS')
        # The command's require_writable locks user + context and rechecks revision.
        # Keeping report reads and external AI outside that transaction avoids lock leaks.
        return self.dispatch(request,match,ctx,unsafe=unsafe)
    def dispatch(self,request,match,ctx,unsafe):
        name=match.url_name
        if name not in ROLE_FREE:
            if not valid_context(request.user,ctx):
                if unsafe:return self.error(request,'身份已失效或未选择。请返回身份选择页。',409)
                return redirect('select_role')
            if ctx.role not in route_roles(name,match.kwargs):
                return self.error(request,'此页面不属于当前工作台。请通过“切换身份”选择已授权身份。')
            if ctx.role in CLINIC_ROLES and ctx.clinic_id is None and name not in ROLE_HOME and name not in {'dashboard','guide_index','guide_task'}:
                if unsafe:return self.error(request,'尚未选择诊所；本次操作未执行。',409)
                return redirect('manager_home' if ctx.role=='MANAGER' else 'frontdesk_home')
        if unsafe:
            token=request.headers.get('X-ADC-Workspace','') if name=='assistant_api' else request.POST.get('workspace_token','')
            if not check_token(ctx,token):
                return self.error(request,'工作身份或诊所已切换，或页面已过期。本次操作未执行；请刷新后核对再提交。',409)
        return self.get_response(request)
